"""
heatsync/statusbar.py — StatusBar widget.
"""

import os

import psutil

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt

from .theme import _THEME, _font
from .sensors import (
    s_ram, s_ram_info, s_gpu_vram, s_cpu_freq,
    s_disk_all, s_gpu_power, s_nvme_temps,
)


def _sb_html(key: str, val: str) -> str:
    """Render a status-bar item as '<KEY> <val>' with cyan key, white value."""
    return (f'<span style="color:{_THEME.cyan};">{key}</span>'
            f'<span style="color:{_THEME.txt_hi};"> {val}</span>')


class StatusBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(0)

        self._lbs: dict[str, QLabel] = {}
        keys = ("RAM", "Swap", "VRAM", "Freq", "Cores", "Disk", "GPU Power", "NVMe")
        for i, key in enumerate(keys):
            if i > 0:
                lay.addSpacing(14)
            lb = QLabel()
            lb.setTextFormat(Qt.TextFormat.RichText)
            lb.setFont(_font(11))
            lb.setMinimumWidth(0)
            lb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            lb.setStyleSheet("background: transparent;")
            self._lbs[key] = lb
            lay.addWidget(lb)
        lay.addStretch(1)

    def _apply_theme_styles(self):
        for lb in self._lbs.values():
            lb.setStyleSheet("background: transparent;")
        # re-render all labels with updated theme colors
        self.refresh()

    def refresh(self):
        used_r, tot_r, pct_r = s_ram()
        ram_type, ram_speed = s_ram_info()
        if ram_speed:
            spd = f"{ram_speed // 1000}G" if ram_speed >= 1000 else f"{ram_speed}M"
            ram_sfx = f" {ram_type}@{spd}" if ram_type != "RAM" else f" @{spd}"
        elif ram_type != "RAM":
            ram_sfx = f" {ram_type}"
        else:
            ram_sfx = ""
        self._lbs["RAM"].setText(
            _sb_html("RAM", f"{used_r:.1f}/{tot_r:.0f}G ({pct_r:.0f}%){ram_sfx}"))

        sw = psutil.swap_memory()
        self._lbs["Swap"].setText(
            _sb_html("Swap", f"{sw.used/1e9:.1f}/{sw.total/1e9:.0f}G")
            if sw.total else _sb_html("Swap", "N/A"))

        used_v, tot_v, pct_v = s_gpu_vram()
        self._lbs["VRAM"].setText(
            _sb_html("VRAM", f"{used_v/1024:.1f}/{tot_v/1024:.0f}G ({pct_v:.0f}%)")
            if tot_v else _sb_html("VRAM", "N/A"))

        freq = s_cpu_freq()
        cores = psutil.cpu_count(logical=True)
        self._lbs["Freq"].setText(_sb_html("CPU", f"{freq:.2f}GHz"))
        self._lbs["Cores"].setText(_sb_html("×", f"{cores}"))

        # Multi-disk: show up to 2 mounts compactly
        disks = s_disk_all()
        if disks:
            parts = []
            for mount, used, total, pct in disks[:2]:
                base = os.path.basename(mount.rstrip("/\\")) or mount
                short = base if len(base) <= 6 else base[:6]
                parts.append(f"{short} {used:.0f}/{total:.0f}G")
            self._lbs["Disk"].setText(_sb_html("Disk", "  ".join(parts)))
        else:
            self._lbs["Disk"].setText(_sb_html("Disk", "N/A"))

        pwr = s_gpu_power()
        self._lbs["GPU Power"].setText(
            _sb_html("GPU", f"{pwr:.0f}W") if pwr > 0 else _sb_html("GPU", "N/A"))

        nvme = s_nvme_temps()
        if nvme:
            parts = [f"{name[:8]} {temp:.0f}°C" for name, temp in nvme[:2]]
            self._lbs["NVMe"].setText(_sb_html("NVMe", "  ".join(parts)))
        else:
            self._lbs["NVMe"].setText(_sb_html("NVMe", "N/A"))
