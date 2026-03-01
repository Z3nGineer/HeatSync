<p align="center">
  <img src="assets/icon.png" width="128" alt="HeatSync Logo">
</p>

<h1 align="center">HeatSync</h1>

<p align="center">
  Real-time system monitor for Linux, Windows, and macOS
</p>

<p align="center">
  <a href="https://gitlab.com/vibesmiths/HeatSync/-/releases"><img src="https://img.shields.io/badge/download-latest-blue?style=for-the-badge" alt="Download"></a>
  <a href="https://aur.archlinux.org/packages/heatsync-bin"><img src="https://img.shields.io/badge/AUR-heatsync--bin-1793d1?style=for-the-badge&logo=archlinux&logoColor=white" alt="AUR"></a>
  <img src="https://img.shields.io/badge/python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License">
</p>

---

![HeatSync](assets/screenshot.png)

![HeatSync under load](assets/screenshot-load.png)

![HeatSync compact mode](assets/screenshot-compact.png)

---

## Download

| Platform | Download | |
|---|---|---|
| **Linux** | [HeatSync.AppImage](https://gitlab.com/vibesmiths/HeatSync/-/releases) | Works on any distro |
| **Linux (Arch)** | `paru -S heatsync-bin` | AUR package |
| **Windows** | [HeatSync.exe](https://gitlab.com/vibesmiths/HeatSync/-/releases) | No install needed |
| **macOS** | [HeatSync.dmg](https://gitlab.com/vibesmiths/HeatSync/-/releases) | Drag to Applications |

---

## Features

- **Circular arc gauges** -- 300 degree sweep per metric; color shifts white to orange to red with load
- **Sparkline history** -- 90-point rolling graph per metric
- **Vendor-aware labels** -- AMD, NVIDIA, and Intel names color-coded in the title bar
- **Status bar** -- RAM, VRAM, CPU frequency, thread count, and disk usage
- **10 built-in themes** -- Dark, Light, Synthwave, Midnight, Dracula, Nord, Solarized, Forest, Amber, AMOLED
- **Compact mode** -- slim bar with all key stats for minimal screen footprint
- **Dock mode** -- snaps to the top edge as a full-width bar; double-click to toggle
- **Window memory** -- remembers position, size, and dock state between sessions
- **System tray** -- no taskbar icon; hides to tray on close
- **GPU auto-detection** -- NVIDIA via pynvml; AMD and Intel via sysfs (no extra drivers needed)
- **Intel CPU temperature** -- via `coretemp` kernel driver, works out of the box

---

## Installation

### Linux

**AppImage** -- recommended, works on any distro (Ubuntu 18.04+, Fedora 32+, Arch, etc.):

```bash
chmod +x HeatSync.AppImage
./HeatSync.AppImage
```

**Arch Linux / AUR:**

```bash
paru -S heatsync-bin
```

**From source:**

```bash
git clone https://gitlab.com/vibesmiths/HeatSync.git
cd HeatSync
bash install.sh
```

`install.sh` creates a `.venv`, installs dependencies, and sets up autostart.

### Windows

Download **[HeatSync.exe](https://gitlab.com/vibesmiths/HeatSync/-/releases)** and run it -- no installation required.

> CPU temperature on Windows requires [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) running in the background.

### macOS

Download **[HeatSync.dmg](https://gitlab.com/vibesmiths/HeatSync/-/releases)**, open it, and drag HeatSync.app to your Applications folder.

---

## Themes

HeatSync ships with 10 themes. Switch themes from the settings menu in the title bar.

| Theme | Style |
|---|---|
| Dark | Default dark theme |
| Light | Clean light mode |
| Synthwave | Retro neon purple/pink |
| Midnight | Deep blue/black |
| Dracula | Classic Dracula palette |
| Nord | Arctic, north-bluish |
| Solarized | Solarized Dark |
| Forest | Earthy greens |
| Amber | Warm amber/orange |
| AMOLED | Pure black for OLED displays |

---

## GPU Support

| GPU | Driver | Notes |
|-----|--------|-------|
| NVIDIA | pynvml | Requires `nvidia-utils` |
| AMD | amdgpu sysfs | No extra drivers |
| Intel Arc / iGPU | xe / i915 sysfs | No extra drivers |

When multiple GPUs are present, priority is NVIDIA then AMD then Intel.

---

## Verifying Downloads

All release artifacts are GPG-signed and include SHA256 checksums.

```bash
# Import the signing key
gpg --import heatsync-signing-key.asc

# Verify a binary
gpg --verify HeatSync.AppImage.asc HeatSync.AppImage

# Verify checksums
sha256sum -c SHA256SUMS
```

---

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## License

[MIT](LICENSE)
