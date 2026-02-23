#!/usr/bin/env python3
import subprocess
import sys
import threading
import pystray
from dataclasses import dataclass
from PIL import Image, ImageDraw

_lock = threading.Lock()
available_sources: list = []   # list[SourceInfo]
active_modules: dict = {}      # source_name -> pactl module_id


@dataclass
class SourceInfo:
    name: str
    description: str


# --- Icon rendering ---

def create_icon(active: bool) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (80, 220, 80, 255) if active else (180, 180, 180, 255)

    # Mic body
    draw.rounded_rectangle([22, 4, 42, 36], radius=10, fill=color)
    # Mic stand arc
    draw.arc([12, 20, 52, 48], start=0, end=180, fill=color, width=4)
    # Stand stem
    draw.line([32, 48, 32, 58], fill=color, width=4)
    # Stand base
    draw.line([20, 58, 44, 58], fill=color, width=4)

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
    names = get_short_sources()
    descriptions = get_source_descriptions()
    sources = [
        SourceInfo(name=n, description=descriptions.get(n, n))
        for n in names
    ]
    with _lock:
        available_sources.clear()
        available_sources.extend(sources)
    if icon is not None:
        update_icon(icon)


def update_icon(icon) -> None:
    with _lock:
        count = len(active_modules)
    if count > 0:
        icon.icon = create_icon(True)
        icon.title = f"Mic Monitor: ON ({count} active)"
    else:
        icon.icon = create_icon(False)
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


# --- Menu ---

def build_menu_items():
    with _lock:
        sources_snapshot = list(available_sources)
        modules_snapshot = dict(active_modules)

    items = []
    if not sources_snapshot:
        items.append(pystray.MenuItem("No sources found", None, enabled=False))
    else:
        for src in sources_snapshot:
            name = src.name
            items.append(pystray.MenuItem(
                src.description,
                make_toggle_callback(name),
                checked=lambda item, n=name: n in modules_snapshot,
            ))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Refresh Sources", refresh_callback))
    items.append(pystray.MenuItem("Quit", quit_app))
    return tuple(items)


def refresh_callback(icon, item) -> None:
    threading.Thread(target=refresh_sources, args=(icon,), daemon=True).start()


def quit_app(icon, item) -> None:
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
    )
    icon.run()


if __name__ == "__main__":
    main()
