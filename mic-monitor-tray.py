#!/usr/bin/env python3
import subprocess
import threading
import pystray
from PIL import Image, ImageDraw

SOURCE = "alsa_input.usb-Blue_Microphones_Yeti_X_2230SG001N68_888-000313110306-00.analog-stereo"
module_id = None


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


def enable_monitor():
    global module_id
    result = subprocess.run(
        ["pactl", "load-module", "module-loopback", "latency_msec=1", f"source={SOURCE}"],
        capture_output=True, text=True
    )
    try:
        module_id = int(result.stdout.strip())
    except ValueError:
        module_id = None


def disable_monitor():
    global module_id
    if module_id is not None:
        subprocess.run(["pactl", "unload-module", str(module_id)])
        module_id = None
    else:
        # Fallback: unload all loopback modules
        subprocess.run(["pactl", "unload-module", "module-loopback"])


def toggle(icon=None, item=None):
    global module_id
    if module_id is None:
        enable_monitor()
        if icon:
            icon.icon = create_icon(True)
            icon.title = "Mic Monitor: ON"
    else:
        disable_monitor()
        if icon:
            icon.icon = create_icon(False)
            icon.title = "Mic Monitor: OFF"


def quit_app(icon, item):
    disable_monitor()
    icon.stop()


def main():
    # Kill any leftover loopback modules from a previous crashed instance
    subprocess.run(["pactl", "unload-module", "module-loopback"],
                   capture_output=True)

    menu = pystray.Menu(
        pystray.MenuItem("Toggle Monitor", toggle, default=True, visible=False),
        pystray.MenuItem("Toggle Monitor", toggle),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon(
        "mic-monitor",
        create_icon(False),
        "Mic Monitor: OFF",
        menu=menu,
    )
    icon.run()


if __name__ == "__main__":
    main()
