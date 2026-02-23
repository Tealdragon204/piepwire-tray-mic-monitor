#!/usr/bin/env python3
import subprocess
import sys
import threading
import pystray
from dataclasses import dataclass
from PIL import Image, ImageDraw

_lock = threading.Lock()
available_sources: list = []    # list[SourceInfo]
active_modules: dict = {}       # source_name -> pactl module_id
default_source_name: str = ""   # system default input source
is_muted: bool = False          # mute state of the default source
left_click_toggle: bool = False
_mute_poll_stop = threading.Event()


@dataclass
class SourceInfo:
    name: str
    description: str


# --- Icon rendering ---

def create_icon(active: bool, muted: bool = False) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Green when monitoring and unmuted, grey otherwise
    mic_color = (80, 220, 80, 255) if (active and not muted) else (180, 180, 180, 255)

    # Mic body
    draw.rounded_rectangle([22, 4, 42, 36], radius=10, fill=mic_color)
    # Mic stand arc
    draw.arc([12, 20, 52, 48], start=0, end=180, fill=mic_color, width=4)
    # Stand stem
    draw.line([32, 48, 32, 58], fill=mic_color, width=4)
    # Stand base
    draw.line([20, 58, 44, 58], fill=mic_color, width=4)

    # Mute slash: red diagonal line through the mic body
    if muted:
        draw.line([44, 4, 20, 38], fill=(220, 60, 60, 255), width=4)

    # Recording dot badge: filled red circle in top-right corner when monitoring is active
    if active:
        draw.ellipse([46, 2, 62, 18], fill=(220, 60, 60, 255))

    return img


# --- pactl interface ---

def _run_pactl(*args) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["pactl", *args],
            capture_output=True, text=True, timeout=5
        )
    except FileNotFoundError:
        print("Warning: pactl not found. Install pipewire-pulse or pulseaudio-utils.", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("Warning: pactl timed out.", file=sys.stderr)
        return None


def get_short_sources() -> list:
    result = _run_pactl("list", "short", "sources")
    if result is None or result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            name = parts[1]
            if "input" in name.lower() and "monitor" not in name.lower():
                names.append(name)
    return names


def get_source_descriptions() -> dict:
    result = _run_pactl("list", "sources")
    if result is None or result.returncode != 0:
        return {}
    descriptions = {}
    current_name = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            current_name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Description:") and current_name:
            descriptions[current_name] = stripped.split(":", 1)[1].strip()
            current_name = None
    return descriptions


def get_default_source() -> str:
    result = _run_pactl("get-default-source")
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_default_source_muted() -> bool:
    result = _run_pactl("get-source-mute", "@DEFAULT_SOURCE@")
    if result is None or result.returncode != 0:
        return False
    return "yes" in result.stdout.lower()


def enable_monitor(source_name: str) -> int | None:
    result = _run_pactl(
        "load-module", "module-loopback", "latency_msec=1", f"source={source_name}"
    )
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def disable_monitor(module_id: int) -> bool:
    result = _run_pactl("unload-module", str(module_id))
    return result is not None and result.returncode == 0


# --- State management ---

def refresh_sources(icon=None) -> None:
    global default_source_name
    names = get_short_sources()
    descriptions = get_source_descriptions()
    sources = [
        SourceInfo(name=n, description=descriptions.get(n, n))
        for n in names
    ]
    default = get_default_source()
    with _lock:
        available_sources.clear()
        available_sources.extend(sources)
        default_source_name = default
    if icon is not None:
        update_icon(icon)


def _mute_poll_loop(icon) -> None:
    global is_muted
    while not _mute_poll_stop.wait(1.5):
        new_muted = get_default_source_muted()
        with _lock:
            changed = new_muted != is_muted
            is_muted = new_muted
        if changed:
            update_icon(icon)


def update_icon(icon) -> None:
    with _lock:
        count = len(active_modules)
        muted = is_muted
    if count > 0:
        icon.icon = create_icon(True, muted)
        icon.title = f"Mic Monitor: ON ({count} active)"
    else:
        icon.icon = create_icon(False, muted)
        icon.title = "Mic Monitor: OFF"


def make_toggle_callback(source_name: str):
    def callback(icon, item):
        toggle_source(source_name, icon)
    return callback


def toggle_source(source_name: str, icon) -> None:
    with _lock:
        current_id = active_modules.get(source_name)

    if current_id is not None:
        disable_monitor(current_id)
        with _lock:
            active_modules.pop(source_name, None)
    else:
        new_id = enable_monitor(source_name)
        if new_id is not None:
            with _lock:
                active_modules[source_name] = new_id

    update_icon(icon)


def _on_activate(icon) -> None:
    """Left-click: turn all monitors off if any are active, else enable the default source."""
    with _lock:
        lct = left_click_toggle
        has_active = len(active_modules) > 0
        default = default_source_name

    if not lct:
        return

    if has_active:
        with _lock:
            modules_to_unload = dict(active_modules)
        for mod_id in modules_to_unload.values():
            disable_monitor(mod_id)
        with _lock:
            active_modules.clear()
    elif default:
        new_id = enable_monitor(default)
        if new_id is not None:
            with _lock:
                active_modules[default] = new_id

    update_icon(icon)


# --- Menu ---

def toggle_left_click_setting(icon, item) -> None:
    global left_click_toggle
    with _lock:
        left_click_toggle = not left_click_toggle


def build_menu_items():
    with _lock:
        sources_snapshot = list(available_sources)
        modules_snapshot = dict(active_modules)
        default_name = default_source_name
        lct = left_click_toggle

    items = []

    # Pinned default source at top
    if default_name:
        items.append(pystray.MenuItem(
            "Default (System Default)",
            make_toggle_callback(default_name),
            checked=lambda item, n=default_name: n in modules_snapshot,
        ))
        items.append(pystray.Menu.SEPARATOR)

    # Remaining sources (deduplicated against default)
    remaining = [s for s in sources_snapshot if s.name != default_name]
    if not remaining and not default_name:
        items.append(pystray.MenuItem("No sources found", None, enabled=False))
    else:
        for src in remaining:
            name = src.name
            items.append(pystray.MenuItem(
                src.description,
                make_toggle_callback(name),
                checked=lambda item, n=name: n in modules_snapshot,
            ))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(
        "Left-click to toggle",
        toggle_left_click_setting,
        checked=lambda item: lct,
    ))
    items.append(pystray.MenuItem("Refresh Sources", refresh_callback))
    items.append(pystray.MenuItem("Quit", quit_app))
    return tuple(items)


def refresh_callback(icon, item) -> None:
    threading.Thread(target=refresh_sources, args=(icon,), daemon=True).start()


def quit_app(icon, item) -> None:
    _mute_poll_stop.set()
    with _lock:
        modules_to_unload = dict(active_modules)

    for module_id in modules_to_unload.values():
        disable_monitor(module_id)

    with _lock:
        active_modules.clear()

    icon.stop()


# --- Entry point ---

def main():
    # Clean up any loopback modules left over from a crashed previous instance
    _run_pactl("unload-module", "module-loopback")

    refresh_sources()

    menu = pystray.Menu(build_menu_items)
    icon = pystray.Icon(
        "mic-monitor",
        create_icon(False),
        "Mic Monitor: OFF",
        menu=menu,
        on_activate=_on_activate,
    )

    mute_thread = threading.Thread(target=_mute_poll_loop, args=(icon,), daemon=True)
    mute_thread.start()

    icon.run()
    _mute_poll_stop.set()


if __name__ == "__main__":
    main()
