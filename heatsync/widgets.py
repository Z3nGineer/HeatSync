"""
heatsync/widgets.py — Sparkline, ArcGauge, MiniArcGauge, MonitorCard,
                      FanRow, PerCoreRow, NetworkPanel.
"""

import math
from collections import deque

import psutil

from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy,
    QGraphicsDropShadowEffect, QMenu, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush,
    QLinearGradient, QRadialGradient, QPainterPath,
)

from .constants import CYAN, GREEN, PURPLE, CPU_COLOR, GPU_COLOR, C_WARN, C_DANG
from .theme import _THEME, _font

# Gauge face text constants — always near-white regardless of theme
_GAUGE_TXT     = "#dde4f0"
_GAUGE_TXT_MID = "#6878a0"


# ── Arc Gauge ─────────────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    _DEG_START = 240
    _DEG_SPAN  = -300
    _HALOS = ((10, 8), (7, 20), (5, 38))

    def __init__(self, label, unit, lo=0, hi=100, color=None, warn=75, danger=90,
                 is_temp=False, invert_warn=False, is_usage=False):
        super().__init__()
        self._label   = label
        self._unit    = unit
        self._lo, self._hi = lo, hi
        self._col     = QColor(color or _THEME.cyan)
        self._warn    = warn
        self._danger  = danger
        self._is_temp = is_temp
        self._is_usage = is_usage
        self._invert_warn = invert_warn
        self._target  = 0.0
        self._cur     = 0.0
        self._compact = False
        self.setMinimumSize(190, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        t = QTimer(self); t.timeout.connect(self._tick); t.start(15)

    def set_value(self, v):
        self._target = max(self._lo, min(self._hi, v))

    def set_color(self, hex_color: str):
        self._col = QColor(hex_color)
        self.update()

    def set_compact(self, compact: bool):
        self._compact = compact
        self.setMinimumSize(120 if compact else 190, 130 if compact else 210)
        self.updateGeometry()

    def _tick(self):
        delta = self._target - self._cur
        if abs(delta) > 0.05:
            self._cur += delta * 0.18
            self.update()
        elif self._cur != self._target:
            self._cur = self._target
            self.update()

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red()   * (1.0 - t) + b.red()   * t),
            int(a.green() * (1.0 - t) + b.green()  * t),
            int(a.blue()  * (1.0 - t) + b.blue()   * t),
        )

    def _active_col(self):
        pct = max(0.0, min(1.0, (self._cur - self._lo) / max(self._hi - self._lo, 1e-9)))
        v   = self._cur

        # Warn / danger override — applies to every gauge type including temp
        if self._invert_warn:
            if v <= self._danger: return QColor(_THEME.c_dang)
            if v <= self._warn:   return QColor(_THEME.c_warn)
        else:
            if v >= self._danger: return QColor(_THEME.c_dang)
            if v >= self._warn:   return QColor(_THEME.c_warn)

        # Below warn threshold — use themed color for both usage and temp gauges
        warn_pct = self._warn / max(self._hi - self._lo, 1.0)
        t = min(1.0, pct / max(warn_pct, 0.01))
        dim = (QColor(100, 160, 200) if _THEME.is_light
               else QColor(_THEME.txt_lo))
        return self._lerp_color(dim, QColor(_THEME.cyan), t)

    def paintEvent(self, _e):
        W, H   = self.width(), self.height()
        margin = 14 if self._compact else 22
        side   = min(W, H) - margin * 2
        rx, ry = (W - side) / 2, (H - side) / 2 - 8
        rect   = QRectF(rx, ry, side, side)
        r2     = side / 2
        cx, cy = rx + r2, ry + r2

        a0    = self._DEG_START * 16
        a_end = self._DEG_SPAN  * 16
        pct   = max(0.0, min(1.0, (self._cur - self._lo) / max(self._hi - self._lo, 1e-9)))
        a_val = int(a_end * pct)
        col   = self._active_col()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)

        light = _THEME.is_light
        _bg   = QColor(_THEME.bg)
        _cbg  = QColor(_THEME.card_bg)
        _cbd  = QColor(_THEME.card_bd)

        # Outer bezel — derives from card colors
        bezel_rect = rect.adjusted(-5, -5, 5, 5)
        bezel_grad = QRadialGradient(cx, cy, r2 + 5)
        if light:
            bezel_grad.setColorAt(0,    QColor("#a0cce8"))
            bezel_grad.setColorAt(0.75, QColor("#68a0cc"))
            bezel_grad.setColorAt(1.0,  QColor("#4878a8"))
        else:
            _bz0 = _cbg.lighter(130); _bz0.setAlpha(255)
            bezel_grad.setColorAt(0,   _bz0)
            bezel_grad.setColorAt(0.8, _cbg)
            bezel_grad.setColorAt(1.0, _bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bezel_grad))
        p.drawEllipse(bezel_rect)
        rim_col = QColor("#4878a8") if light else QColor(_cbd)
        rim_col.setAlpha(200 if light else 100)
        p.setPen(QPen(rim_col, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(bezel_rect)
        trim = QColor(col); trim.setAlpha(35)
        p.setPen(QPen(trim, 1.0))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))

        # Gauge face — light: cool white-grey; dark: deep version of theme bg
        face_grad = QRadialGradient(cx, cy - r2 * 0.15, r2)
        if light:
            face_grad.setColorAt(0,    QColor("#d0e8f8"))
            face_grad.setColorAt(0.55, QColor("#aecce8"))
            face_grad.setColorAt(1.0,  QColor("#88aad0"))
        else:
            _f0 = _bg.darker(170); _f1 = _bg.darker(135)
            face_grad.setColorAt(0,    _f0)
            face_grad.setColorAt(0.55, _f1)
            face_grad.setColorAt(1.0,  _bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(face_grad))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        hi = QRadialGradient(cx, cy - r2 * 0.55, r2 * 0.5)
        hi.setColorAt(0, QColor(255, 255, 255, 50 if light else 12))
        hi.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(hi))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        vig = QRadialGradient(cx, cy, r2 * 0.72)
        vig.setColorAt(0,   QColor(0, 0, 0, 0))
        vig.setColorAt(0.6, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 30 if light else 70))
        p.setBrush(QBrush(vig))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        if pct > 0.02:
            atm = QRadialGradient(cx, cy, r2 * 0.96)
            ac0 = QColor(col); ac0.setAlpha(0)
            ac1 = QColor(col); ac1.setAlpha(int(pct * 60))
            atm.setColorAt(0.0,  ac0); atm.setColorAt(0.55, ac0)
            atm.setColorAt(0.82, ac1); atm.setColorAt(1.0,  ac0)
            p.setBrush(QBrush(atm)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Arc track
        inset    = 12
        trk_w    = 7
        arc_rect = rect.adjusted(inset, inset, -inset, -inset)
        arc_r2   = r2 - inset
        trk_col = QColor("#7ab8e0") if light else _bg.darker(165)
        trk = QPen(trk_col, trk_w); trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk); p.drawArc(arc_rect, a0, a_end)
        if pct < 0.99:
            hint_c = QColor(col); hint_c.setAlpha(35 if light else 22)
            hp = QPen(hint_c, trk_w - 2); hp.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(hp); p.drawArc(arc_rect, a0 + a_val, a_end - a_val)

        # Tick marks
        if not self._compact:
            t_outer = r2 - 2.5
            for i in range(21):
                t_val   = i / 20.0
                is_maj  = (i % 5 == 0)
                ang_rad = math.radians(self._DEG_START + self._DEG_SPAN * t_val)
                ca, sa  = math.cos(ang_rad), math.sin(ang_rad)
                t_len   = 6.5 if is_maj else 3.5
                t_inner = t_outer - t_len
                inactive = _THEME.txt_lo
                if is_maj:
                    tc = QColor(col) if t_val <= pct + 0.03 else QColor(inactive)
                    tc.setAlpha(210 if light else 190); pw = 1.5
                else:
                    tc = QColor(inactive); tc.setAlpha(100 if light else 80); pw = 1.0
                p.setPen(QPen(tc, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cx + t_outer * ca, cy - t_outer * sa),
                           QPointF(cx + t_inner * ca, cy - t_inner * sa))

        # Colored fill arc + glow
        if pct > 5e-3:
            for pw, al in self._HALOS:
                c = QColor(col); c.setAlpha(al)
                pk = QPen(c, pw); pk.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pk); p.drawArc(arc_rect, a0, a_val)
            pk = QPen(col, trk_w); pk.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pk); p.drawArc(arc_rect, a0, a_val)
            spec = QPen(QColor(255, 255, 255, 55), max(1.0, trk_w * 0.28))
            spec.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(spec); p.drawArc(arc_rect, a0, a_val)

            tip_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
            tip_x   = cx + arc_r2 * math.cos(tip_ang)
            tip_y   = cy - arc_r2 * math.sin(tip_ang)
            for dr, da in ((8, 18), (5, 60), (3, 255)):
                c = QColor(col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(tip_x, tip_y), dr, dr)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # Value + label badge — drawn BEFORE needle so needle renders on top
        gauge_txt = _THEME.txt_hi if light else _GAUGE_TXT
        val_str   = f"{self._cur:.0f}{self._unit}"
        fs        = max(8 if self._compact else 9,
                        int(side * 0.15 * (4 / max(len(val_str), 4))))

        # Position badge lower in the arc gap (near the open arc section)
        badge_h  = side * 0.20
        badge_w  = min(side * 0.46, W - 16)
        badge_cy = cy + arc_r2 * 0.50
        badge_x  = cx - badge_w / 2
        badge_y  = badge_cy - badge_h / 2
        badge_r  = 7.0

        bg_col = QColor(0xd0, 0xd8, 0xee, 210) if light else QColor(0x06, 0x08, 0x12, 218)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bg_col))
        p.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), badge_r, badge_r)
        sheen = QLinearGradient(0, badge_y, 0, badge_y + badge_h * 0.5)
        sheen.setColorAt(0, QColor(255, 255, 255, 18 if not light else 65))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), badge_r, badge_r)
        bdr = QColor(col); bdr.setAlpha(85)
        p.setPen(QPen(bdr, 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), badge_r, badge_r)

        p.setFont(_font(fs, bold=True)); p.setPen(QColor(gauge_txt))
        p.drawText(QRectF(badge_x, badge_y, badge_w, badge_h),
                   Qt.AlignmentFlag.AlignCenter, val_str)

        # Label sits just below badge in accent color
        lbl_col = QColor(col); lbl_col.setAlpha(210)
        lbl_fs  = max(6 if self._compact else 7, int(side * 0.060))
        p.setFont(_font(lbl_fs)); p.setPen(lbl_col)
        p.drawText(QRectF(badge_x, badge_y + badge_h + 1, badge_w, side * 0.12),
                   Qt.AlignmentFlag.AlignCenter, self._label)

        # Needle — drawn after badge so it renders on top
        n_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
        n_r   = arc_r2 - trk_w / 2 - 1
        n_tx  = cx + n_r * math.cos(n_ang)
        n_ty  = cy - n_r * math.sin(n_ang)
        for dr, da in ((7, 30), (4.5, 80), (2.5, 200)):
            c = QColor(col); c.setAlpha(da)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(cx, cy), dr, dr)
        p.setPen(QPen(QColor(col), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(n_tx, n_ty))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Hub cap — matches face center
        hub_col = QColor("#8bbfe0") if light else _bg.darker(170)
        p.setBrush(QBrush(hub_col))
        p.setPen(QPen(QColor(col), 0.8))
        p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        p.end()


# ── Mini Arc Gauge (for per-core row) ─────────────────────────────────────────
class MiniArcGauge(QWidget):
    _DEG_START = 240
    _DEG_SPAN  = -300

    def __init__(self, label: str):
        super().__init__()
        self._label  = label
        self._target = 0.0
        self._cur    = 0.0
        self.setFixedSize(80, 90)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        t = QTimer(self); t.timeout.connect(self._tick); t.start(30)

    def set_value(self, v: float):
        self._target = max(0.0, min(100.0, v))

    def _tick(self):
        delta = self._target - self._cur
        if abs(delta) > 0.05:
            self._cur += delta * 0.18
            self.update()
        elif self._cur != self._target:
            self._cur = self._target; self.update()

    def paintEvent(self, _e):
        W, H   = self.width(), self.height()
        margin = 6
        side   = min(W, H - 16) - margin * 2
        rx     = (W - side) / 2
        ry     = margin
        rect   = QRectF(rx, ry, side, side)
        r2     = side / 2
        cx, cy = rx + r2, ry + r2
        pct    = self._cur / 100.0
        a0     = self._DEG_START * 16
        a_end  = self._DEG_SPAN  * 16
        a_val  = int(a_end * pct)

        # Choose color based on value
        if pct >= 0.9:    col = QColor(_THEME.c_dang)
        elif pct >= 0.75: col = QColor(_THEME.c_warn)
        else:             col = QColor(_THEME.cyan)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Face
        face = QRadialGradient(cx, cy, r2)
        face.setColorAt(0, QColor("#0d1020")); face.setColorAt(1, QColor("#030406"))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(face))
        p.drawEllipse(rect)

        # Track
        inset    = 7
        arc_rect = rect.adjusted(inset, inset, -inset, -inset)
        trk = QPen(QColor("#0d1020"), 4); trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk); p.drawArc(arc_rect, a0, a_end)

        # Fill
        if pct > 0.01:
            fill = QPen(col, 4); fill.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(fill); p.drawArc(arc_rect, a0, a_val)

        # Value text — gauge face is always dark so always use bright text
        p.setFont(_font(10, bold=True)); p.setPen(QColor(_GAUGE_TXT))
        p.drawText(QRectF(0, cy - 2, W, side * 0.4),
                   Qt.AlignmentFlag.AlignCenter, f"{self._cur:.0f}%")

        # Label
        p.setFont(_font(8)); p.setPen(QColor(_THEME.txt_mid))
        p.drawText(QRectF(0, ry + side + 2, W, 14),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


# ── Sparkline ─────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    def __init__(self, color=None, max_pts=90, unit="", warn=75, danger=90, colour_coded=True):
        super().__init__()
        self._theme_color = color is None   # True → follows _THEME.cyan on theme change
        self._base_col    = QColor(color if color is not None else _THEME.cyan)
        self._col         = QColor(self._base_col)
        self._hist: deque = deque(maxlen=max_pts)
        self._unit       = unit
        self._hover_x    = -1.0
        self._warn       = warn
        self._danger     = danger
        self._colour_coded = colour_coded
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def _current_color(self) -> QColor:
        if not self._colour_coded or not self._hist:
            return self._base_col
        v = self._hist[-1]
        if v >= self._danger:
            return QColor(_THEME.c_dang)
        if v >= self._warn:
            return QColor(_THEME.c_warn)
        return self._base_col

    def _apply_theme_styles(self):
        if self._theme_color:
            self._base_col = QColor(_THEME.cyan)
            self._col = self._current_color()
            self.update()

    def push(self, v):
        self._hist.append(v)
        self._col = self._current_color()
        self.update()

    def mouseMoveEvent(self, e):
        if len(self._hist) < 2: return
        self._hover_x = e.position().x(); self.update()

    def leaveEvent(self, e):
        self._hover_x = -1.0; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        if len(self._hist) < 2: return
        W, H = self.width(), self.height()
        px, py = 3, 6
        vals = list(self._hist)
        hi   = max(max(vals), 1.0)
        n    = len(vals)
        fx   = lambda i: px + i / (n - 1) * (W - 2 * px)
        fy   = lambda v: H - py - v / hi * (H - 2 * py)
        pts  = [QPointF(fx(i), fy(v)) for i, v in enumerate(vals)]

        line = QPainterPath(); line.moveTo(pts[0])
        for i in range(1, n):
            mid = (pts[i-1].x() + pts[i].x()) / 2
            line.cubicTo(QPointF(mid, pts[i-1].y()), QPointF(mid, pts[i].y()), pts[i])

        area = QPainterPath(line)
        area.lineTo(QPointF(pts[-1].x(), H)); area.lineTo(QPointF(pts[0].x(), H))
        area.closeSubpath()

        grad = QLinearGradient(0, 0, 0, H)
        top  = QColor(self._col); top.setAlpha(55)
        bot  = QColor(self._col); bot.setAlpha(0)
        grad.setColorAt(0, top); grad.setColorAt(1, bot)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(area, QBrush(grad))
        p.setPen(QPen(self._col, 1.7, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)
        tip = pts[-1]
        for dr, da in ((7, 18), (4.5, 60), (2.5, 240)):
            c = QColor(self._col); c.setAlpha(da)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(tip, dr, dr)

        if self._hover_x >= 0:
            mx = max(pts[0].x(), min(pts[-1].x(), self._hover_x))
            hp, hval = pts[-1], vals[-1]
            for i in range(len(pts) - 1):
                x0, x1 = pts[i].x(), pts[i + 1].x()
                if x0 <= mx <= x1:
                    t    = (mx - x0) / (x1 - x0) if x1 > x0 else 0.0
                    hy   = pts[i].y()  + t * (pts[i + 1].y()  - pts[i].y())
                    hval = vals[i]     + t * (vals[i + 1]      - vals[i])
                    hp   = QPointF(mx, hy)
                    break
            vc = QColor(self._col); vc.setAlpha(40)
            p.setPen(QPen(vc, 1, Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(hp.x(), py), QPointF(hp.x(), H))
            for dr, da in ((6, 25), (3.5, 80), (2, 220)):
                c = QColor(self._col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(hp, dr, dr)

            label = f"{hval:.1f}{self._unit}"
            p.setFont(_font(10, bold=True))
            fm  = p.fontMetrics()
            pad = 4
            bw  = fm.horizontalAdvance(label) + pad * 2
            bh  = fm.height() + pad * 2
            off = 10
            bx  = hp.x() + off if hp.x() + off + bw < W else max(0.0, hp.x() - bw - off)
            by  = max(2.0, min(hp.y() - bh - 6, float(H - bh - 2)))
            bg  = QColor(_THEME.card_bg); bg.setAlpha(210)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bg))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            bc = QColor(self._col); bc.setAlpha(160)
            p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            p.setPen(QColor(_THEME.txt_hi))
            p.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        p.end()


# ── Monitor Card ──────────────────────────────────────────────────────────────
class MonitorCard(QFrame):
    _R = 22.0

    def __init__(self, label, unit, lo=0, hi=100, color=None,
                 warn=75, danger=90, is_temp=False, invert_warn=False, is_usage=False,
                 resource_key="", on_set_threshold=None):
        super().__init__()
        col = color or _THEME.cyan
        self._accent = QColor(col)
        self._warn   = warn
        self._danger = danger
        self._resource_key    = resource_key
        self._on_set_threshold = on_set_threshold
        self.gauge   = ArcGauge(label, unit, lo, hi, col, warn, danger,
                                is_temp=is_temp, invert_warn=invert_warn, is_usage=is_usage)
        self.spark   = Sparkline(unit=unit, warn=warn, danger=danger,
                                 colour_coded=True)

        self._sep = QFrame(); self._sep.setFixedHeight(1)
        self._sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none; border-radius: 0;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 10); lay.setSpacing(8)
        lay.addWidget(self.gauge, 1)
        lay.addWidget(self._sep)
        lay.addWidget(self.spark)

        self.setMinimumHeight(300)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(28); self._shadow.setOffset(0, 5)
        self._apply_shadow()
        self.setGraphicsEffect(self._shadow)

        # Stats tracking
        self._stat_min   = float("inf")
        self._stat_max   = float("-inf")
        self._stat_sum   = 0.0
        self._stat_count = 0

        # Threshold crossing indicator: "" / "warn" / "danger"
        self._cross_level = ""

    def push(self, v):
        self.gauge.set_value(v)
        self.spark.push(v)
        if v < self._stat_min: self._stat_min = v
        if v > self._stat_max: self._stat_max = v
        self._stat_sum   += v
        self._stat_count += 1
        new_level = ""
        if self.gauge._invert_warn:
            if v <= self._danger:   new_level = "danger"
            elif v <= self._warn:   new_level = "warn"
        else:
            if v >= self._danger:   new_level = "danger"
            elif v >= self._warn:   new_level = "warn"
        if new_level != self._cross_level:
            self._cross_level = new_level
            self.update()

    def set_color(self, hex_color: str):
        self._accent = QColor(hex_color)
        self.gauge.set_color(hex_color)

    def reset_stats(self):
        self._stat_min   = float("inf")
        self._stat_max   = float("-inf")
        self._stat_sum   = 0.0
        self._stat_count = 0

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        unit = self.gauge._unit

        if self._stat_count > 0:
            avg = self._stat_sum / self._stat_count
            menu.addAction(
                f"Min: {self._stat_min:.1f}{unit}  |  "
                f"Avg: {avg:.1f}{unit}  |  "
                f"Max: {self._stat_max:.1f}{unit}"
            ).setEnabled(False)
        else:
            menu.addAction("No data yet").setEnabled(False)

        menu.addSeparator()
        reset_act     = menu.addAction("Reset min/avg/max")
        threshold_act = None
        if self._on_set_threshold and self._resource_key in (
                "cpu_temp", "gpu_temp", "cpu_usage", "gpu_usage"):
            threshold_act = menu.addAction("Set alert threshold…")

        top_act = None
        key = self._resource_key
        if key in ("cpu_usage", "cpu_temp"):
            top_act = menu.addAction("Top CPU processes…")
        elif key in ("gpu_usage", "gpu_temp"):
            top_act = menu.addAction("Top GPU processes (nvidia-smi)…")

        chosen = menu.exec(event.globalPos())
        if chosen == reset_act:
            self.reset_stats()
        elif threshold_act and chosen == threshold_act:
            from PyQt6.QtWidgets import QInputDialog
            cur = self._danger
            val, ok = QInputDialog.getInt(
                self, "Alert Threshold",
                f"Alert threshold for {key.replace('_', ' ').title()} ({unit}):",
                cur, 1, 999, 1)
            if ok:
                self._on_set_threshold(self._resource_key, val)
        elif top_act and chosen == top_act:
            self._show_top_processes(key)

    def _show_top_processes(self, key: str):
        lines = []
        try:
            if key in ("cpu_usage", "cpu_temp"):
                procs = sorted(
                    psutil.process_iter(["pid", "name", "cpu_percent"]),
                    key=lambda p: p.info.get("cpu_percent") or 0, reverse=True,
                )[:8]
                lines.append("Top CPU processes:")
                for pr in procs:
                    pct = pr.info.get("cpu_percent") or 0
                    nm  = (pr.info.get("name") or "?")[:22]
                    lines.append(f"  {nm:<22}  {pct:5.1f}%")
            elif key in ("gpu_usage", "gpu_temp"):
                r = subprocess.run(
                    ["nvidia-smi",
                     "--query-compute-apps=pid,process_name,used_memory",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3,
                )
                if r.returncode == 0:
                    lines.append("GPU processes (nvidia-smi):")
                    for row in r.stdout.strip().splitlines():
                        parts = [x.strip() for x in row.split(",")]
                        if len(parts) >= 3:
                            lines.append(f"  PID {parts[0]}  {parts[1][:20]}  {parts[2]} MiB")
                else:
                    lines.append("nvidia-smi not available.")
        except Exception as ex:
            lines.append(f"Error: {ex}")
        msg = QMessageBox(self)
        msg.setWindowTitle("Process Details")
        msg.setText("\n".join(lines) if lines else "No data.")
        msg.exec()

    def set_compact(self, compact: bool):
        self.gauge.set_compact(compact)
        self.spark.setVisible(not compact)
        self._sep.setVisible(not compact)
        self.setMinimumHeight(155 if compact else 300)
        self.updateGeometry()

    def _apply_shadow(self):
        alpha = 60 if _THEME.is_light else 160
        self._shadow.setColor(QColor(0, 0, 0, alpha))

    def _apply_theme_styles(self):
        self._sep.setStyleSheet(
            f"background: {_THEME.card_bd}; border: none; border-radius: 0;")
        self._apply_shadow()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1); R = self._R

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_THEME.card_bg)))
        p.drawRoundedRect(r, R, R)

        top_grad = QLinearGradient(0, r.y(), 0, r.y() + 90)
        if _THEME.is_light:
            top_grad.setColorAt(0, QColor(200, 215, 245, 60))
        else:
            top_grad.setColorAt(0, QColor(_THEME.card_bd))
        top_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(top_grad)); p.drawRoundedRect(r, R, R)

        bot_grad = QLinearGradient(0, r.bottom() - 50, 0, r.bottom())
        bot_grad.setColorAt(0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1, QColor(0, 0, 0, 15 if _THEME.is_light else 50))
        p.setBrush(QBrush(bot_grad)); p.drawRoundedRect(r, R, R)

        sheen = QLinearGradient(0, r.y(), 0, r.y() + 28)
        sheen.setColorAt(0, QColor(255, 255, 255, 60 if _THEME.is_light else 16))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen)); p.drawRoundedRect(r, R, R)

        border_grad = QLinearGradient(0, r.y(), 0, r.bottom())
        if _THEME.is_light:
            border_grad.setColorAt(0, QColor(_THEME.card_bd).lighter(110))
            border_grad.setColorAt(1, QColor(_THEME.card_bd))
        else:
            border_grad.setColorAt(0, QColor(_THEME.card_bd).lighter(150))
            border_grad.setColorAt(1, QColor(_THEME.card_bd))
        p.setPen(QPen(QBrush(border_grad), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, R, R)

        if self._cross_level:
            bar_col = QColor(_THEME.c_dang if self._cross_level == "danger" else _THEME.c_warn)
            bar_col.setAlpha(220)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(r.x(), r.y(), r.width(), 3), R, R)
            p.drawRect(QRectF(r.x(), r.y() + 1.5, r.width(), 1.5))

        p.end()


# ── Fan Row ───────────────────────────────────────────────────────────────────
class FanRow(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(36)
        self.setStyleSheet("background: transparent;")
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(4, 0, 4, 0)
        self._lay.setSpacing(24)
        self._labels: dict[str, QLabel] = {}
        self._no_fan = QLabel("No fans detected")
        self._no_fan.setFont(_font(11))
        self._no_fan.setStyleSheet(f"color: {_THEME.txt_lo}; background: transparent;")
        self._lay.addWidget(self._no_fan)
        self._lay.addStretch()

    def update_fans(self, fans: "list[tuple[str, int]]"):
        if not fans:
            self._no_fan.setVisible(True)
            for lb in self._labels.values(): lb.setVisible(False)
            return
        self._no_fan.setVisible(False)
        existing = set(self._labels.keys())
        new_keys = {name for name, _ in fans}
        for key in existing - new_keys:
            self._labels[key].deleteLater(); del self._labels[key]
        for name, rpm in fans:
            if name not in self._labels:
                lb = QLabel()
                lb.setFont(_font(11))
                lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
                self._labels[name] = lb
                self._lay.insertWidget(self._lay.count() - 1, lb)
            self._labels[name].setText(f"⊛ {name}  {rpm:,} RPM")
            self._labels[name].setVisible(True)

    def _apply_theme_styles(self):
        self._no_fan.setStyleSheet(f"color: {_THEME.txt_lo}; background: transparent;")
        for lb in self._labels.values():
            lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")


# ── Per-core Row ──────────────────────────────────────────────────────────────
class PerCoreRow(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        from PyQt6.QtWidgets import QGridLayout
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(6)
        self._gauges: list[MiniArcGauge] = []
        self._core_count = 0

    def _ensure_gauges(self, count: int):
        if count == self._core_count:
            return
        for g in self._gauges:
            g.deleteLater()
        self._gauges.clear()
        cols = min(count, 8)
        for i in range(count):
            g = MiniArcGauge(f"C{i}")
            self._gauges.append(g)
            self._grid.addWidget(g, i // cols, i % cols)
        self._core_count = count
        h = 90 * math.ceil(count / max(cols, 1)) + 10
        self.setFixedHeight(int(h))

    def update_values(self, values: "list[float]"):
        self._ensure_gauges(len(values))
        for g, v in zip(self._gauges, values):
            g.set_value(v)


# ── Network Panel ─────────────────────────────────────────────────────────────
class NetworkPanel(QFrame):
    """Compact upload/download panel — two rows with value + sparkline."""
    _R = 14.0

    def __init__(self):
        super().__init__()
        self.setFixedHeight(96)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(18); self._shadow.setOffset(0, 4)
        self._apply_shadow()
        self.setGraphicsEffect(self._shadow)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 8); outer.setSpacing(0)

        self._rows: list[tuple[QLabel, QLabel, QLabel, Sparkline]] = []
        for arrow, label_text in [("↑", "UPLOAD"), ("↓", "DOWNLOAD")]:
            row = QHBoxLayout(); row.setSpacing(10)

            arr_lbl = QLabel(arrow)
            arr_lbl.setFont(_font(18, bold=True))
            arr_lbl.setFixedWidth(20)
            arr_lbl.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")

            name_lbl = QLabel(label_text)
            name_lbl.setFont(_font(10))
            name_lbl.setFixedWidth(62)
            name_lbl.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")

            spark = Sparkline(CYAN, max_pts=90, unit=" Mb/s")
            spark.setFixedHeight(38)

            val_lbl = QLabel("0 Mb/s")
            val_lbl.setFont(_font(13, bold=True))
            val_lbl.setFixedWidth(90)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")

            row.addWidget(arr_lbl)
            row.addWidget(name_lbl)
            row.addWidget(spark, 1)
            row.addWidget(val_lbl)
            self._rows.append((arr_lbl, name_lbl, val_lbl, spark))

            wrap = QWidget(); wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            wrap.setLayout(row)

            if not self._rows or len(self._rows) == 1:
                outer.addWidget(wrap, 1)
            else:
                sep = QFrame(); sep.setFixedWidth(1)
                sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
                self._sep = sep
                outer.addWidget(sep)
                outer.addWidget(wrap, 1)

    def update_network(self, up: float, down: float):
        for (arr, name, val, spark), value in zip(self._rows, (up, down)):
            val.setText(f"{value:.1f} Mb/s")
            spark.push(value)

    def _apply_shadow(self):
        alpha = 50 if _THEME.is_light else 140
        self._shadow.setColor(QColor(0, 0, 0, alpha))

    def _apply_theme_styles(self):
        for arr, name, val, spark in self._rows:
            arr.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")
            name.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")
            val.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        if hasattr(self, "_sep"):
            self._sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
        self._apply_shadow()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_THEME.card_bg)))
        p.drawRoundedRect(r, self._R, self._R)
        sheen = QLinearGradient(0, r.y(), 0, r.y() + 24)
        sheen.setColorAt(0, QColor(255, 255, 255, 14)); sheen.setColorAt(1, QColor(0,0,0,0))
        p.setBrush(QBrush(sheen)); p.drawRoundedRect(r, self._R, self._R)
        p.setPen(QPen(QBrush(QLinearGradient(0, r.y(), 0, r.bottom())), 1.5))
        border = QLinearGradient(0, r.y(), 0, r.bottom())
        border.setColorAt(0, QColor(_THEME.card_bd).lighter(110))
        border.setColorAt(1, QColor(_THEME.card_bd))
        p.setPen(QPen(QBrush(border), 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._R, self._R)
        p.end()
