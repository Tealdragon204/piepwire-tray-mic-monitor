# piepwire-tray-mic-monitor

A Linux system tray application for real-time microphone monitoring via PipeWire or PulseAudio. Routes any connected audio input source through a low-latency loopback so you can hear yourself in headphones while recording or on a call.

## Features

- Dynamically lists all connected audio input sources with human-readable names
- Toggle monitoring per-source independently — monitor one mic or several at once
- Green tray icon when any source is active, gray when idle
- **Refresh Sources** to detect newly plugged-in devices without restarting
- Cleans up all loopback modules on quit (and on next launch if it crashed)

## Getting the Code (New to GitHub? Start Here)

If you've never used Git or GitHub before, this section walks you through getting the files onto your computer.

### What is Git?

**Git** is a tool that tracks changes to files. **GitHub** is a website where people share code using Git.
**Cloning** a repository just means downloading a copy of the project to your computer so you can use or modify it.

### Step 1 — Install Git

Open a terminal (`Ctrl+Alt+T` on most desktops) and run the command for your distro:

**Debian / Ubuntu:**
```sh
sudo apt install git
```

**Fedora:**
```sh
sudo dnf install git
```

**Arch:**
```sh
sudo pacman -S git
```

You can confirm it installed correctly by running:
```sh
git --version
```
You should see something like `git version 2.x.x`.

### Step 2 — Clone this repository

Navigate to a folder where you want to keep the project (your home folder is fine):
```sh
cd ~
```

Then clone the repo:
```sh
git clone https://github.com/Tealdragon204/pipewire-tray-mic-monitor.git
```

This creates a new folder called `pipewire-tray-mic-monitor` with all the project files inside.

### Step 3 — Enter the project folder

```sh
cd pipewire-tray-mic-monitor
```

You're now inside the project and can follow the **Installation** steps below.

> **Tip:** If the project is ever updated and you want the latest version, just run `git pull` from inside the folder.

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

### 4. Add to autostart

Create a `.desktop` file so it launches with your session:

```sh
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/mic-monitor.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Mic Monitor
Exec=/usr/bin/python3 /opt/mic-monitor-tray.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
```

Or add it through your desktop environment's startup application manager (GNOME Tweaks, KDE System Settings → Autostart, etc.).

## Usage

- A microphone icon appears in the system tray.
- **Right-click** the icon to see all detected audio input sources.
- Click a source to **toggle monitoring on/off**. A checkmark indicates active monitoring.
- Click **Refresh Sources** after plugging in a new device.
- Click **Quit** to stop all monitoring and exit.

The icon turns green when at least one source is being monitored, and shows how many are active in the tooltip.

## Troubleshooting

**No sources appear in the menu:**
- Run `pactl list short sources` in a terminal to see what devices pactl can find.
- Make sure your audio daemon is running: `systemctl --user status pipewire-pulse` or `pulseaudio --check`.

**Monitoring is active but I hear nothing:**
- Check that your output device (speakers/headphones) is set as the default sink in your system audio settings.
- The loopback uses `latency_msec=1`; some hardware may need a higher value. You can edit the script to change this.

**The icon does not appear:**
- Some desktop environments need a system tray applet (e.g. `gnome-shell-extension-appindicator` on GNOME).

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).
