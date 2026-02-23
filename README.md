# pipewire-tray-mic-monitor

A Linux system tray application for real-time microphone monitoring via PipeWire or PulseAudio. Routes any connected audio input source through a low-latency loopback so you can hear yourself in headphones while recording or on a call.

## Features

- Dynamically lists all connected audio input sources with human-readable names
- Toggle monitoring per-source independently — monitor one mic or several at once
- Tray icon reflects three independent states at once:
  - **Green mic** — audio signal detected above the noise floor; **grey** when silent or muted
  - **Red dot badge** — loopback/monitoring is currently active
  - **Red slash** — default input source is muted
- **Refresh Sources** to detect newly plugged-in devices without restarting
- Cleans up all loopback modules on quit (and on next launch if it crashed)
- Colors and sensitivity threshold configurable via `~/.config/mic-monitor.conf`

## Getting the Code

Clone the repository to your home folder (or wherever you like):
```sh
git clone https://github.com/Tealdragon204/pipewire-tray-mic-monitor.git
cd pipewire-tray-mic-monitor
```

> **Tip:** To grab future updates, run `git pull` from inside the folder.

---

## Dependencies

**System packages** (one of these audio stacks):
- PipeWire with `pipewire-pulse` (recommended on modern distros)
- PulseAudio with `pulseaudio-utils`

Either way you need `pactl` available in your PATH.

**Python 3.9+** with:
- [`pystray`](https://github.com/moses-palmer/pystray)
- [`Pillow`](https://pillow.readthedocs.io/)

## Installation

### 1. Install system dependencies

**Debian / Ubuntu (PipeWire):**
```sh
sudo apt install pipewire-pulse python3-pip
```

**Fedora (PipeWire):**
```sh
sudo dnf install pipewire-pulseaudio python3-pip
```

### 2. Install Python dependencies
```sh
pip3 install --user pystray Pillow
```

### 3. Install the script
```sh
sudo cp mic-monitor-tray.py /opt/mic-monitor-tray.py
sudo chmod +x /opt/mic-monitor-tray.py
```

### 4. Install the desktop entry

Copy the included `.desktop` file so the app appears in your application launcher:

```sh
cp mic-monitor.desktop ~/.local/share/applications/
```

### 5. Add to autostart (optional)

Use your desktop environment's built-in autostart manager to launch Mic Monitor at login:

| DE | Where to find it |
|---|---|
| **GNOME** | GNOME Tweaks → Startup Applications |
| **KDE Plasma** | System Settings → Autostart |
| **XFCE** | Session and Startup → Application Autostart |
| **MATE** | Control Center → Startup Applications |
| **Cinnamon** | System Settings → Startup Applications |

Search for **"Mic Monitor"** in the list — it will appear there once the desktop entry is installed.

## Usage

- A microphone icon appears in the system tray.
- The icon turns **green** when your mic is picking up audio above the noise floor, and **grey** when silent or muted.
- A small **red dot** appears in the top-right corner while loopback monitoring is active.
- A **red slash** overlays the mic when the default input source is muted.
- **Right-click** the icon to open the menu.
- The top menu entry **"Default (System Default)"** toggles monitoring on your current default input device.
- Other entries toggle per-source monitoring independently. A checkmark indicates active monitoring.
- **"Left-click to toggle"** (in the menu) enables a shortcut: left-clicking the icon turns all monitors off if any are active, or enables the default source if none are. See the note below about DE support.
- Click **Refresh Sources** after plugging in a new device.
- Click **Quit** to stop all monitoring and exit.

The tooltip shows how many sources are actively monitored.

### Customizing colors

On first launch, `~/.config/mic-monitor.conf` is created with the default settings:

```ini
[colors]
active   = #50DC50   # mic color when audio is detected
inactive = #B4B4B4   # mic color when silent or muted
accent   = #DC3C3C   # dot badge and mute slash color

[audio]
threshold = 400      # RMS noise floor (0–32768). Lower = more sensitive.
```

Edit the file with any hex color values, then restart the app.

## Troubleshooting

**No sources appear in the menu:**
- Run `pactl list short sources` in a terminal to see what devices pactl can find.
- Make sure your audio daemon is running: `systemctl --user status pipewire-pulse` or `pulseaudio --check`.

**Monitoring is active but I hear nothing:**
- Check that your output device (speakers/headphones) is set as the default sink in your system audio settings.
- The loopback uses `latency_msec=1`; some hardware may need a higher value. You can edit the script to change this.

**The icon does not appear:**
- Some desktop environments need a system tray applet (e.g. `gnome-shell-extension-appindicator` on GNOME).

**"Left-click to toggle" doesn't work:**
- This feature relies on the system tray distinguishing left-click from right-click. On **KDE Plasma** and **GNOME** (AppIndicator backend), both clicks open the menu — this is a platform limitation, not a bug. The **"Default (System Default)"** entry at the top of the menu is the one-click equivalent on those desktops. Left-click toggle works as expected on XFCE, MATE, Cinnamon, and similar DEs.

**Mic mute not detected:**
- The app polls the default input source's mute state via `pactl`. If hardware-level muting (e.g. a dedicated mic-mute key that bypasses PipeWire) is used, pactl may not see the change. Software muting via system audio settings or the keyboard volume keys should work reliably.

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).
