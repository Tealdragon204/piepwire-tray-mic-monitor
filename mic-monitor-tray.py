#!/usr/bin/env python3
import configparser
import os
import struct
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
_audio_active: bool = False     # audio signal detected above threshold
_audio_proc: subprocess.Popen | None = None
left_click_toggle: bool = False
_mute_poll_stop = threading.Event()

# Color/threshold defaults — overridden by load_config()
_colors: dict = {
    "active":   (80, 220, 80, 255),
    "inactive": (180, 180, 180, 255),
    "accent":   (220, 60, 60, 255),
}
_AUDIO_THRESHOLD: float = 400.0

CONFIG_PATH = os.path.expanduser("~/.config/mic-monitor.conf")
_DEFAULT_CONFIG = """\
[colors]
# Mic color when audio is detected above the noise floor
active = #50DC50
# Mic color when silent or muted
inactive = #B4B4B4
# Color for the recording dot badge and the mute slash
accent = #DC3C3C

[audio]
# RMS threshold (0-32768). Lower = more sensitive. Default is ~-38 dB.
threshold = 400
"""


@dataclass
class SourceInfo:
    name: str
    description: str


# --- Config ---

def _hex_to_rgba(hex_str: str) -> tuple:
    h = hex_str.strip().lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def load_config() -> None:
    global _colors, _AUDIO_THRESHOLD
    if not os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "w") as f:
                f.write(_DEFAULT_CONFIG)
        except OSError:
            pass
        return

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    try:
        _colors["active"]   = _hex_to_rgba(cfg.get("colors", "active",   fallback="#50DC50"))
        _colors["inactive"] = _hex_to_rgba(cfg.get("colors", "inactive", fallback="#B4B4B4"))
        _colors["accent"]   = _hex_to_rgba(cfg.get("colors", "accent",   fallback="#DC3C3C"))
        _AUDIO_THRESHOLD    = float(cfg.get("audio", "threshold", fallback="400"))
    except (ValueError, configparser.Error) as e:
        print(f"Warning: config parse error ({e}), using defaults.", file=sys.stderr)


# --- Icon rendering ---

def create_icon(monitoring: bool, audio_active: bool, muted: bool = False) -> Image.Image:
    """
    monitoring   — draws red dot badge (loopback/monitoring on)
    audio_active — green mic when True and not muted, grey otherwise
    muted        — draws red diagonal slash through the mic body
    """
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    mic_color = _colors["active"] if (audio_active and not muted) else _colors["inactive"]

    # Mic body
    draw.rounded_rectangle([22, 4, 42, 36], radius=10, fill=mic_color)
    # Mic stand arc
    draw.arc([12, 20, 52, 48], start=0, end=180, fill=mic_color, width=4)
    # Stand stem
    draw.line([32, 48, 32, 58], fill=mic_color, width=4)
    # Stand base
    draw.line([20, 58, 44, 58], fill=mic_color, width=4)

    # Mute slash: diagonal line through the mic body
    if muted:
        draw.line([44, 4, 20, 38], fill=_colors["accent"], width=4)

    # Recording dot badge: filled circle in top-right corner when monitoring is active
    if monitoring:
        draw.ellipse([46, 2, 62, 18], fill=_colors["accent"])

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


def _get_mute_from_list(source_name: str) -> bool:
    """Fallback: parse mute state from `pactl list sources`."""
    result = _run_pactl("list", "sources")
    if result is None or result.returncode != 0:
        return False
    in_source = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            in_source = source_name in stripped
        elif in_source and stripped.startswith("Mute:"):
            return "yes" in stripped.lower()
        elif in_source and stripped.startswith("Name:"):
            break  # moved past the target source
    return False


def get_default_source_muted() -> bool:
    with _lock:
        src = default_source_name
    if not src:
        return False
    result = _run_pactl("get-source-mute", src)
    if result is None or result.returncode != 0:
        return _get_mute_from_list(src)
    output = result.stdout.strip().lower()
    # Handles "Mute: yes", "mute: yes", or bare "yes"
    return output == "yes" or output.endswith(": yes")


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


def _audio_level_loop(icon) -> None:
    """Persist a parecord process and update _audio_active from RMS level."""
    global _audio_active, _audio_proc
    CHUNK = 1600  # 100 ms at 8 kHz, int16 = 800 samples × 2 bytes
    try:
        _audio_proc = subprocess.Popen(
            ["parecord", "--raw", "--channels=1", "--format=s16le",
             "--rate=8000", "--latency-msec=100"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("Warning: parecord not found; audio activity detection disabled.", file=sys.stderr)
        return

    try:
        while True:
            data = _audio_proc.stdout.read(CHUNK)
            if not data:
                break  # process was terminated
            n = len(data) // 2
            if n == 0:
                continue
            samples = struct.unpack(f"{n}h", data[:n * 2])
            rms = (sum(s * s for s in samples) / n) ** 0.5
            new_active = rms > _AUDIO_THRESHOLD
            with _lock:
                changed = new_active != _audio_active
                _audio_active = new_active
            if changed:
                update_icon(icon)
    finally:
        try:
            _audio_proc.terminate()
            _audio_proc.wait(timeout=2)
        except Exception:
            pass


def update_icon(icon) -> None:
    with _lock:
        count = len(active_modules)
        muted = is_muted
        audio = _audio_active
    icon.icon = create_icon(count > 0, audio, muted)
    icon.title = f"Mic Monitor: ON ({count} active)" if count > 0 else "Mic Monitor: OFF"


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

    # Stop the audio level subprocess so its thread unblocks and exits
    global _audio_proc
    if _audio_proc is not None:
        try:
            _audio_proc.terminate()
        except Exception:
            pass

    with _lock:
        modules_to_unload = dict(active_modules)

    for module_id in modules_to_unload.values():
        disable_monitor(module_id)

    with _lock:
        active_modules.clear()

    icon.stop()


# --- Entry point ---

def main():
    load_config()

    # Clean up any loopback modules left over from a crashed previous instance
    _run_pactl("unload-module", "module-loopback")

    refresh_sources()

    menu = pystray.Menu(build_menu_items)
    icon = pystray.Icon(
        "mic-monitor",
        create_icon(False, False),
        "Mic Monitor: OFF",
        menu=menu,
        on_activate=_on_activate,
    )

    threading.Thread(target=_mute_poll_loop,    args=(icon,), daemon=True).start()
    threading.Thread(target=_audio_level_loop,  args=(icon,), daemon=True).start()

    icon.run()
    _mute_poll_stop.set()


if __name__ == "__main__":
    main()
