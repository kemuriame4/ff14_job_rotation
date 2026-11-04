from __future__ import annotations

import json
import math

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..analyzer import EARLY, EXTRA, LATE, MISSING, OK, ORDER
from ..gamedata import game_data, icon_file
from ..jobs.dnc import DANCE_STEPS
from ..keys import canonical_from_qt, pretty_key
from ..models import Skill

STATUS_COLORS: dict[str, tuple[str, str]] = {
    OK: ("#173a2a", "#4fbf8b"),
    EARLY: ("#3d311a", "#e0b45a"),
    LATE: ("#3d311a", "#e0b45a"),
    ORDER: ("#3f2a1a", "#e08a5c"),
    EXTRA: ("#3e1f27", "#e06a72"),
    MISSING: ("#1b2230", "#e06a72"),
}
NEUTRAL = ("#202b3b", "#55647c")
DEFAULT_ACTUAL = ("#1b3049", "#5590c9")


class NoWheelComboBox(QComboBox):
    """禁用滚轮切换选项的下拉框（标准循环等表格内使用）。"""

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class TimelineWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        self._expected: list[tuple[float, str]] = []
        self._actual: list[tuple[float, str]] = []
        self._expected_status: list[str | None] = []
        self._actual_status: list[str | None] = []
        self._duration = 60.0
        self._playhead: float | None = None
        self._gcd = 2.5
        self._hit: list[tuple[QRectF, str]] = []
        self._last_tip = ""

    def set_data(
        self,
        expected: list[tuple[float, str]] | None = None,
        actual: list[tuple[float, str]] | None = None,
        expected_statuses: list[str | None] | None = None,
        actual_statuses: list[str | None] | None = None,
        duration: float = 60.0,
        playhead: float | None = None,
        gcd: float = 2.5,
    ) -> None:
        self._expected = list(expected or [])
        self._actual = list(actual or [])
        self._expected_status = list(expected_statuses or [])
        self._actual_status = list(actual_statuses or [])
        self._duration = max(0.1, float(duration))
        self._playhead = playhead
        self._gcd = max(0.1, float(gcd))
        self.update()

    def clear(self) -> None:
        self.set_data(duration=max(self._duration, 1.0), gcd=self._gcd)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#28313f"), 1))
        painter.setBrush(QColor("#11161f"))
        painter.drawRoundedRect(outer, 10, 10)

        left = 64.0
        right = self.width() - 16.0
        if right <= left + 10:
            return
        top_axis = 26.0
        std_top = 36.0
        lane_h = 38.0
        act_top = std_top + lane_h + 16.0
        legend_y = act_top + lane_h + 16.0
        px = (right - left) / self._duration
        self._hit = []

        tick = self._tick_step()
        tick_t = 0.0
        tick_font = QFont(self.font())
        tick_font.setPointSize(9)
        painter.setFont(tick_font)
        while tick_t <= self._duration + 1e-6:
            x = left + tick_t * px
            painter.setPen(QPen(QColor("#232c39"), 1))
            painter.drawLine(QPointF(x, top_axis - 4), QPointF(x, act_top + lane_h))
            painter.setPen(QColor("#75808f"))
            label_rect = QRectF(x - 32, 4, 64, 18)
            if x + 32 > right:
                label_rect = QRectF(right - 64, 4, 64, 18)
            painter.drawText(
                label_rect, Qt.AlignmentFlag.AlignCenter, _fmt_time(tick_t)
            )
            tick_t += tick
        painter.setPen(QPen(QColor("#2c3644"), 1))
        painter.drawLine(
            QPointF(left, std_top - 5), QPointF(left, act_top + lane_h + 5)
        )

        lane_font = QFont(self.font())
        lane_font.setPointSize(11)
        lane_font.setBold(True)
        painter.setFont(lane_font)
        painter.setPen(QColor("#8d97a8"))
        painter.drawText(
            QRectF(8, std_top, 50, lane_h), Qt.AlignmentFlag.AlignCenter, "标准"
        )
        painter.drawText(
            QRectF(8, act_top, 50, lane_h), Qt.AlignmentFlag.AlignCenter, "实际"
        )

        self._draw_lane(
            painter,
            self._expected,
            self._expected_status,
            left,
            std_top,
            lane_h,
            px,
            self._duration,
            expected_lane=True,
        )
        self._draw_lane(
            painter,
            self._actual,
            self._actual_status,
            left,
            act_top,
            lane_h,
            px,
            self._duration,
            expected_lane=False,
        )

        if self._playhead is not None:
            x = left + min(max(self._playhead, 0.0), self._duration) * px
            pen = QPen(QColor("#c9a86a"), 1.5)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, std_top - 9), QPointF(x, act_top + lane_h + 3))
            painter.setBrush(QColor("#c9a86a"))
            painter.drawPolygon(
                [
                    QPointF(x - 4, std_top - 12),
                    QPointF(x + 4, std_top - 12),
                    QPointF(x, std_top - 6),
                ]
            )

        self._draw_legend(painter, legend_y, right)

    def _draw_lane(
        self,
        painter: QPainter,
        events: list[tuple[float, str]],
        statuses: list[str | None],
        left: float,
        lane_top: float,
        lane_h: float,
        px: float,
        duration: float,
        expected_lane: bool,
    ) -> None:
        text_font = QFont(self.font())
        text_font.setPointSize(10)
        metrics = QFontMetrics(text_font)
        block_h = 26.0
        y = lane_top + (lane_h - block_h) / 2
        for index, (t, skill) in enumerate(events):
            if t > duration + 0.001:
                continue
            next_t = events[index + 1][0] if index + 1 < len(events) else t + self._gcd
            gap = next_t - t if next_t > t else self._gcd
            gap = min(gap, 6.0)
            width = max(7.0, min(px * gap * 0.85, 80.0))
            x = left + t * px
            rect = QRectF(x, y, width, block_h)
            status = statuses[index] if index < len(statuses) else None
            fill, border = self._colors(expected_lane, status)
            pen = QPen(QColor(border), 1.2)
            if status == MISSING:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, 5, 5)
            if width >= metrics.horizontalAdvance(skill) + 8:
                painter.setFont(text_font)
                painter.setPen(QColor(border if status else "#d3d9e2"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, skill)
            time_label = _fmt_time(t)
            detail = f"{'标准' if expected_lane else '实际'} {time_label} · {skill}"
            if status:
                detail += f"\n判定：{status}"
            self._hit.append((rect, detail))

    @staticmethod
    def _colors(expected_lane: bool, status: str | None) -> tuple[str, str]:
        if expected_lane:
            if status in (MISSING, ORDER):
                return STATUS_COLORS[status]
            return NEUTRAL
        if status and status in STATUS_COLORS:
            return STATUS_COLORS[status]
        return DEFAULT_ACTUAL

    def _tick_step(self) -> float:
        target = self._duration / max(1, int((max(self.width() - 90, 200)) / 110))
        for step in (1, 2, 5, 10, 15, 20, 30, 60, 120, 180, 300, 600):
            if step >= target:
                return float(step)
        return 600.0

    def _draw_legend(self, painter: QPainter, y: float, right: float) -> None:
        statuses = [s for s in self._actual_status if s] + [
            s for s in self._expected_status if s
        ]
        if not statuses:
            return
        entries: list[tuple[str, str]] = []
        if OK in statuses:
            entries.append((OK, STATUS_COLORS[OK][1]))
        if EARLY in statuses or LATE in statuses:
            entries.append(("偏早 / 偏晚", STATUS_COLORS[EARLY][1]))
        if MISSING in statuses:
            entries.append((MISSING, STATUS_COLORS[MISSING][1]))
        if ORDER in statuses:
            entries.append((ORDER, STATUS_COLORS[ORDER][1]))
        if EXTRA in statuses:
            entries.append((EXTRA, STATUS_COLORS[EXTRA][1]))
        font = QFont(self.font())
        font.setPointSize(9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        x = right
        for label, color in reversed(entries):
            width = metrics.horizontalAdvance(label) + 18
            x -= width
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, y - 5, 8, 8), 2, 2)
            painter.setPen(QColor("#8d97a8"))
            painter.drawText(
                QRectF(x + 12, y - 8, width - 12, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            x -= 10

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        for rect, text in self._hit:
            if rect.contains(pos):
                if text != self._last_tip:
                    self._last_tip = text
                    QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        self._last_tip = ""
        QToolTip.hideText()


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes:02d}:{rest:04.1f}"


_PIXMAP_CACHE: dict[tuple[int, int], QPixmap] = {}


def skill_tooltip(skill: Skill, show_key: bool = True) -> str:
    lines = [skill.name]
    kind = "GCD" if skill.gcd else "能力（oGCD）"
    recast = skill.recast if skill.recast > 0 else (2.5 if skill.gcd else 0.0)
    lines.append(f"{kind} · 复唱 {recast:g}s" if recast > 0 else kind)
    if skill.charges > 1:
        lines.append(f"充能 {skill.charges} 层")
    if skill.level:
        lines.append(f"习得等级 {skill.level}")
    if skill.combo:
        lines.append(f"连击前置：{skill.combo}")
    if skill.transform:
        lines.append("变化为：" + " / ".join(skill.transform))
    if show_key:
        if skill.key:
            lines.append(f"热键：{pretty_key(skill.key)}")
        else:
            lines.append("未绑定按键")
    return "\n".join(lines)


def compact_key(key: str) -> str:
    """热键栏角标用的紧凑键位文本，如 ctrl+shift+1 → C+S+1。"""
    parts = [p for p in key.split("+") if p]
    if not parts:
        return ""
    mods = {"ctrl": "C", "alt": "A", "shift": "S"}
    labels = [
        mods.get(p, p.upper() if len(p) == 1 and p.isalpha() else p) for p in parts[:-1]
    ]
    tail = parts[-1]
    if len(tail) == 1 and tail.isalpha():
        tail = tail.upper()
    return "+".join(labels + [tail])


SKILL_MIME = "application/x-ff14-skill"


def encode_skill_mime(skill_name: str, source: int) -> QMimeData:
    mime = QMimeData()
    mime.setData(
        SKILL_MIME,
        QByteArray(json.dumps({"skill": skill_name, "source": source}).encode("utf-8")),
    )
    return mime


def decode_skill_mime(mime: QMimeData) -> tuple[str, int] | None:
    if not mime.hasFormat(SKILL_MIME):
        return None
    try:
        data = json.loads(bytes(mime.data(SKILL_MIME)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    name = str(data.get("skill") or "")
    if not name:
        return None
    return name, int(data.get("source", -1))


def skill_pixmap(skill: Skill, size: int = 40) -> QPixmap | None:
    path = icon_file(skill.icon)
    if path is None:
        return None
    key = (skill.icon, size)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    pixmap = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _PIXMAP_CACHE[key] = pixmap
    return pixmap


# 四个舞步共用一个四象限图标：蔷薇 / 小鸟 / 绿叶 / 金冠 → 左上 / 右上 / 左下 / 右下。
_DANCE_STEP_QUADRANTS = {
    name: (index % 2, index // 2) for index, name in enumerate(DANCE_STEPS)
}
_DANCE_ICON_CACHE: dict[int, QPixmap] = {}
_DANCE_ICON_IDS: dict[str, int] | None = None


def _dance_icon_ids() -> dict[str, int]:
    global _DANCE_ICON_IDS
    if _DANCE_ICON_IDS is None:
        ids: dict[str, int] = {}
        data = game_data() or {}
        for row in data.get("skills", []):
            name = row.get("name")
            if name in _DANCE_STEP_QUADRANTS:
                ids[name] = int(row.get("icon") or 0)
        _DANCE_ICON_IDS = ids
    return _DANCE_ICON_IDS


def dance_step_pixmap(size: int) -> QPixmap | None:
    """把四个舞步图标各取一角，拼成一个四象限技能图标。"""
    cached = _DANCE_ICON_CACHE.get(size)
    if cached is not None:
        return cached
    ids = _dance_icon_ids()
    if len(ids) < 4:
        return None
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    half = size / 2.0
    for name, (col, row) in _DANCE_STEP_QUADRANTS.items():
        path = icon_file(ids.get(name, 0))
        if path is None:
            continue
        source = QPixmap(str(path))
        if source.isNull():
            continue
        source = source.scaled(
            size,
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        src_rect = QRectF(col * half, row * half, half, half)
        dst_rect = QRectF(col * half, row * half, half, half)
        painter.drawPixmap(dst_rect, source, src_rect)
    painter.end()
    _DANCE_ICON_CACHE[size] = canvas
    return canvas


def skill_icon(skill: Skill, size: int = 24) -> QIcon:
    pixmap = skill_pixmap(skill, size)
    return QIcon(pixmap) if pixmap is not None else QIcon()


def dance_sequence_icon(skill: Skill, size: int = 24) -> QIcon:
    """标准循环页专用：四个舞步共用四象限图标，代表随机舞步。"""
    if skill.name in DANCE_STEPS:
        pixmap = dance_step_pixmap(size)
        if pixmap is not None:
            return QIcon(pixmap)
    return skill_icon(skill, size)


def paint_cooldown(
    painter: QPainter,
    rect: QRectF,
    remaining: float,
    total: float,
    corner: float = 5.0,
) -> None:
    """圆形顺序转圈的冷却蒙版与剩余秒数：黑色扇形随倒计时顺时针收缩。"""
    if remaining <= 0.05 or total <= 0.05:
        return
    fraction = min(1.0, remaining / total)
    center = QPointF(rect.center())
    radius = math.hypot(rect.width(), rect.height()) / 2.0 + 1.0
    circle = QRectF(
        center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0
    )
    path = QPainterPath()
    path.moveTo(center)
    path.arcTo(circle, 90.0, -360.0 * fraction)
    path.lineTo(center)

    clip = QPainterPath()
    clip.addRoundedRect(rect, corner, corner)
    painter.save()
    painter.setClipPath(clip)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 178))
    painter.drawPath(path)

    font = QFont(painter.font())
    font.setPointSize(max(8, int(rect.width()) // 3))
    font.setBold(True)
    painter.setFont(font)
    # 统一按秒计数，超过 60s 也显示总秒数（如 90、120）。
    text = str(int(math.ceil(remaining)))
    painter.setPen(QColor("#000000"))
    painter.drawText(rect.translated(1, 1), Qt.AlignmentFlag.AlignCenter, text)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


def paint_charges(
    painter: QPainter,
    rect: QRectF,
    count: int,
    maximum: int,
) -> None:
    """右下角充能层数角标（仅对有积蓄次数的技能显示）。"""
    if maximum <= 1:
        return
    font = QFont(painter.font())
    font.setPointSize(max(8, int(rect.width()) // 5))
    font.setBold(True)
    painter.setFont(font)
    text = str(max(0, int(count)))
    metrics = QFontMetrics(font)
    badge = QRectF(
        rect.right() - metrics.horizontalAdvance(text) - 10,
        rect.bottom() - metrics.height() - 2,
        metrics.horizontalAdvance(text) + 8,
        metrics.height() + 1,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(9, 13, 19, 225))
    painter.drawRoundedRect(badge, 3, 3)
    painter.setPen(QColor("#e3c07f" if count > 0 else "#8d97a8"))
    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)


class SkillIconTile(QWidget):
    """技能图标，带 FF14 风格的冷却扇形蒙版与剩余秒数。"""

    def __init__(
        self, skill: Skill, size: int = 40, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._skill = skill
        self._size = size
        self._pixmap = skill_pixmap(skill, size)
        self._remaining = 0.0
        self._total = 0.0
        self._charges = 0
        self._max_charges = 0
        self._locked = False
        self._highlight = False
        self.setFixedSize(size, size)

    def skill_name(self) -> str:
        return self._skill.name

    def set_cooldown(self, remaining: float, total: float) -> None:
        remaining = max(0.0, float(remaining))
        total = max(0.0, float(total))
        if abs(remaining - self._remaining) < 0.05 and abs(total - self._total) < 0.05:
            return
        self._remaining = remaining
        self._total = total
        self.update()

    def set_charges(self, count: int, maximum: int) -> None:
        count = max(0, int(count))
        maximum = max(0, int(maximum))
        if count == self._charges and maximum == self._max_charges:
            return
        self._charges = count
        self._max_charges = maximum
        self.update()

    def set_locked(self, locked: bool) -> None:
        if locked != self._locked:
            self._locked = bool(locked)
            self.update()

    def set_highlight(self, highlight: bool) -> None:
        if highlight != self._highlight:
            self._highlight = bool(highlight)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self._size, self._size)

        clip = QPainterPath()
        clip.addRoundedRect(rect, 6, 6)
        painter.setClipPath(clip)

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(rect, self._pixmap, QRectF(self._pixmap.rect()))
        else:
            painter.fillRect(rect, QColor(self._skill.color))
            painter.setPen(QColor("#0d1219"))
            font = QFont(self.font())
            font.setPointSize(max(9, self._size // 3))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._skill.name[:1])

        painter.setClipping(False)
        if self._locked:
            painter.fillRect(rect, QColor(120, 132, 148, 78))

        paint_cooldown(painter, rect, self._remaining, self._total, 6.0)
        paint_charges(painter, rect, self._charges, self._max_charges)

        painter.setClipping(False)
        painter.setPen(
            QPen(
                QColor("#c9a86a" if self._highlight else "#2a3444"),
                2 if self._highlight else 1,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)


class SkillChip(QFrame):
    clicked = Signal(str)

    def __init__(self, skill: Skill, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._skill = skill
        self._active = False
        self._hover = False
        self.setObjectName("SkillChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 12, 8)
        layout.setSpacing(8)

        self.tile = SkillIconTile(skill, 40, self)
        layout.addWidget(self.tile)

        key_text = pretty_key(skill.key).replace(" + ", "+")
        badge = QLabel(key_text if skill.key else "?", self)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setMinimumWidth(32)
        badge.setToolTip(pretty_key(skill.key))
        badge.setStyleSheet(
            "background:#232b38;color:%s;border-radius:5px;padding:2px 6px;font-weight:600;font-size:11px;"
            % ("#c9a86a" if skill.key else "#6b7484")
        )
        layout.addWidget(badge)

        name = QLabel(skill.name, self)
        name.setStyleSheet("font-size:13px;font-weight:600;color:#e6e8ec;")
        name.setToolTip(self._tooltip())
        layout.addWidget(name, 1)

        self.setToolTip(self._tooltip())
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(lambda: self._set_active(False))
        self._apply_style()

    def _tooltip(self) -> str:
        return skill_tooltip(self._skill)

    def skill_name(self) -> str:
        return self._skill.name

    def set_cooldown(self, remaining: float, total: float) -> None:
        self.tile.set_cooldown(remaining, total)

    def set_charges(self, count: int, maximum: int) -> None:
        self.tile.set_charges(count, maximum)

    def set_locked(self, locked: bool) -> None:
        self.tile.set_locked(locked)

    def set_highlight(self, highlight: bool) -> None:
        self.tile.set_highlight(highlight)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.flash()
            self.clicked.emit(self._skill.name)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._apply_style()
        super().leaveEvent(event)

    def flash(self) -> None:
        self._set_active(True)
        self._flash_timer.start(260)

    def _set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            border, background = self._skill.color, "#202b3a"
        elif self._hover:
            border, background = "#3f4d62", "#1a2230"
        else:
            border, background = "#2a3444", "#161c25"
        self.setStyleSheet(
            f"QFrame#SkillChip {{ background:{background}; border:1px solid {border}; border-radius:9px; }}"
        )


class KeyCaptureDialog(QDialog):
    def __init__(self, current_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result_key: str | None = None
        self.cleared = False
        self.setWindowTitle("设置键位")
        self.setModal(True)
        self.setFixedSize(380, 210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        title = QLabel("设置键位")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        tip = QLabel("请按下要绑定的按键（支持 Ctrl / Alt / Shift 组合键）")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        current = QLabel(f"当前：{pretty_key(current_key)}")
        current.setObjectName("NextHint")
        layout.addWidget(current)

        layout.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(8)
        clear_btn = QPushButton("清除绑定")
        clear_btn.setObjectName("Ghost")
        clear_btn.clicked.connect(self._clear)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("Ghost")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(clear_btn)
        row.addStretch(1)
        row.addWidget(cancel_btn)
        layout.addLayout(row)

    def _clear(self) -> None:
        self.cleared = True
        self.result_key = ""
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.isAutoRepeat():
            return
        canonical = canonical_from_qt(event)
        if canonical:
            self.result_key = canonical
            self.accept()
            return
        super().keyPressEvent(event)


class MetricCard(QFrame):
    def __init__(
        self, title: str, value: str = "—", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setMinimumHeight(74)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addStretch(1)

    def set_value(self, text: str, color: str | None = None) -> None:
        self.value_label.setText(text)
        if color:
            self.value_label.setStyleSheet(f"color:{color};")
        else:
            self.value_label.setStyleSheet("")


class HotbarSlot(QFrame):
    """热键栏栏位：图标 + 左上角热键角标，支持改键、右键菜单与拖拽交换。

    read_only 模式用于训练页：保留热键角标与冷却蒙版，但禁止改键、拖拽与右键菜单，
    左键点击直接触发 activated （用于记录施放）。
    """

    selected = Signal(int)
    activated = Signal(int)
    context_requested = Signal(int, QPoint)
    dropped_skill = Signal(str, int, int)  # 技能名, 来源栏位（-1 表示技能池）, 目标栏位

    def __init__(
        self,
        index: int,
        read_only: bool = False,
        size: int = 62,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.index = index
        self._skill: Skill | None = None
        self._key = ""
        self._conflict = False
        self._selected = False
        self._drop_hover = False
        self._press_pos: QPoint | None = None
        self._read_only = bool(read_only)
        self._size = size
        self._icon_margin = 9 if size >= 62 else 8
        self._icon_size = size - self._icon_margin * 2
        self._remaining = 0.0
        self._total = 0.0
        self._charges = 0
        self._max_charges = 0
        self._locked = False
        self._highlight = False
        self._proc = False
        self._combo = False
        self._active = False
        self.setObjectName("HotbarSlot")
        self.setFixedSize(size, size)
        self.setAcceptDrops(not self._read_only)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "空栏位" if self._read_only else "空栏位 · 从下方技能池拖入技能"
        )
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)

    def skill_name(self) -> str:
        return self._skill.name if self._skill else ""

    def set_skill(
        self, skill: Skill | None, key: str = "", conflict: bool = False
    ) -> None:
        self._skill = skill
        self._key = key
        self._conflict = conflict
        if skill is not None:
            tip = skill_tooltip(skill, show_key=False)
            if key:
                tip += f"\n热键: {pretty_key(key)}"
            if self._read_only:
                tip += "\n训练页只读, 键位请在「键位映射」页修改。"
            self.setToolTip(tip)
        elif key:
            tip = f"空栏位 · 热键 {pretty_key(key)}"
            if not self._read_only:
                tip += "（拖入技能后生效）"
            self.setToolTip(tip)
        else:
            self.setToolTip(
                "空栏位" if self._read_only else "空栏位 · 从下方技能池拖入技能"
            )
        self.update()

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = bool(selected)
            self.update()

    def set_cooldown(self, remaining: float, total: float) -> None:
        remaining = max(0.0, float(remaining))
        total = max(0.0, float(total))
        if abs(remaining - self._remaining) < 0.05 and abs(total - self._total) < 0.05:
            return
        self._remaining = remaining
        self._total = total
        self.update()

    def set_charges(self, count: int, maximum: int) -> None:
        count = max(0, int(count))
        maximum = max(0, int(maximum))
        if count == self._charges and maximum == self._max_charges:
            return
        self._charges = count
        self._max_charges = maximum
        self.update()

    def set_locked(self, locked: bool) -> None:
        if locked != self._locked:
            self._locked = bool(locked)
            self.update()

    def set_highlight(self, highlight: bool) -> None:
        if highlight != self._highlight:
            self._highlight = bool(highlight)
            self.update()

    def set_proc(self, proc: bool) -> None:
        """buff 触发 / 强化状态：使用接近游戏原生的金色发光边框。"""
        if proc != self._proc:
            self._proc = bool(proc)
            self.update()

    def set_combo(self, combo: bool) -> None:
        """连击可延续：使用蓝色高亮，与下一步（金色）和强化（金光）区分。"""
        if combo != self._combo:
            self._combo = bool(combo)
            self.update()

    def flash(self) -> None:
        self._active = True
        self._flash_timer.start(260)
        self.update()

    def _end_flash(self) -> None:
        self._active = False
        self.update()

    # painting
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._drop_hover:
            fill, border, width = "#1e2736", "#c9a86a", 2.0
        elif self._combo:
            fill, border, width = "#142130", "#5fb3e8", 2.0
        elif self._proc:
            fill, border, width = "#282111", "#f3da95", 2.0
        elif self._highlight:
            fill, border, width = "#1b2330", "#c9a86a", 2.0
        elif self._active:
            fill, border, width = "#202b3a", "#c9a86a", 2.0
        elif self._selected:
            fill, border, width = "#1b2330", "#c9a86a", 2.0
        elif self._skill:
            fill, border, width = "#151c26", "#2c3644", 1.0
        else:
            fill, border, width = "#11161f", "#232c39", 1.0
        painter.setPen(QPen(QColor(border), width))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 7, 7)

        inner = QRectF(
            rect.x() + self._icon_margin,
            rect.y() + self._icon_margin,
            self._icon_size,
            self._icon_size,
        )
        if self._skill is None:
            painter.setPen(QColor("#39465a"))
            font = QFont(self.font())
            font.setPointSize(15)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "+")
        else:
            pixmap = skill_pixmap(self._skill, self._icon_size)
            if pixmap is not None:
                if self._locked:
                    # 不可使用：图标转灰度，再叠加暗色蒙版。
                    image = pixmap.toImage().convertToFormat(
                        QImage.Format.Format_Grayscale8
                    )
                    pixmap = QPixmap.fromImage(image)
                painter.drawPixmap(inner.toRect(), pixmap)
            else:
                color = "#4a525e" if self._locked else self._skill.color
                painter.setBrush(QColor(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(inner, 5, 5)
                painter.setPen(QColor("#0d1219"))
                font = QFont(self.font())
                font.setPointSize(12)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(
                    inner, Qt.AlignmentFlag.AlignCenter, self._skill.name[:1]
                )
            if self._locked:
                painter.fillRect(inner, QColor(0, 0, 0, 110))
            paint_cooldown(painter, inner, self._remaining, self._total, 5.0)
            paint_charges(painter, inner, self._charges, self._max_charges)
            if self._combo:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(120, 200, 255, 28))
                painter.drawRoundedRect(inner, 5, 5)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for offset, alpha in ((1.0, 96), (2.0, 54), (3.2, 28)):
                    painter.setPen(QPen(QColor(120, 205, 255, alpha), 2.0))
                    painter.drawRoundedRect(
                        inner.adjusted(-offset, -offset, offset, offset),
                        5 + offset,
                        5 + offset,
                    )
            elif self._proc:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 232, 150, 28))
                painter.drawRoundedRect(inner, 5, 5)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for offset, alpha in ((1.0, 100), (2.0, 62), (3.2, 32)):
                    painter.setPen(QPen(QColor(255, 231, 150, alpha), 2.0))
                    painter.drawRoundedRect(
                        inner.adjusted(-offset, -offset, offset, offset),
                        5 + offset,
                        5 + offset,
                    )

        key_text = compact_key(self._key)
        if key_text:
            font = QFont(self.font())
            font.setPointSize(7)
            font.setBold(True)
            metrics = QFontMetrics(font)
            badge = QRectF(
                rect.x() + 2.5,
                rect.y() + 2.5,
                metrics.horizontalAdvance(key_text) + 8,
                14,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(9, 13, 19, 225))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setFont(font)
            painter.setPen(QColor("#e06a72" if self._conflict else "#e3c07f"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, key_text)

        if self._skill is not None and self._skill.transform:
            font = QFont(self.font())
            font.setPointSize(7)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#c9a86a"))
            painter.drawText(
                QRectF(
                    rect.right() - 16 - (20 if self._max_charges > 1 else 0),
                    rect.bottom() - 15,
                    13,
                    13,
                ),
                Qt.AlignmentFlag.AlignCenter,
                "变",
            )

    # drag
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._read_only:
                if self._skill is not None:
                    self.activated.emit(self.index)
                return
            self._press_pos = event.position().toPoint()
            self.selected.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._read_only:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.index)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._read_only:
            return
        if self._press_pos is None or self._skill is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton == 0:
            return
        if (
            event.position().toPoint() - self._press_pos
        ).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        drag.setMimeData(encode_skill_mime(self._skill.name, self.index))
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap)
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint())
        self._press_pos = None
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._read_only:
            return
        if decode_skill_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            self._drop_hover = True
            self.update()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_hover = False
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        if self._read_only:
            return
        payload = decode_skill_mime(event.mimeData())
        self._drop_hover = False
        self.update()
        if payload is None:
            return
        skill_name, source = payload
        self.dropped_skill.emit(skill_name, source, self.index)
        event.acceptProposedAction()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if self._read_only:
            return
        self.context_requested.emit(self.index, event.globalPos())


class SkillPoolItem(QWidget):
    """技能池图标：只显示图标，可拖入热键栏，也可接收从热键栏拖出的技能。"""

    activated = Signal(str)
    remove_requested = Signal(str, int)  # 技能名, 来源栏位

    def __init__(
        self, skill: Skill, placed: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._skill = skill
        self._placed = placed
        self._hover = False
        self._drop_hover = False
        self._press_pos: QPoint | None = None
        self.setFixedSize(46, 46)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(skill_tooltip(skill, show_key=False))

    def skill_name(self) -> str:
        return self._skill.name

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._drop_hover:
            fill, border, width = "#1d2432", "#c9a86a", 2.0
        elif self._hover:
            fill, border, width = "#1a2230", "#3f4d62", 1.0
        else:
            fill = "#141a22"
            border, width = ("#26303d", 1.0) if self._placed else ("#3a4658", 1.0)
        painter.setPen(QPen(QColor(border), width))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 7, 7)

        pixmap = skill_pixmap(self._skill, 38)
        inner = QRectF(rect.x() + 4, rect.y() + 4, 38, 38)
        if pixmap is not None:
            painter.drawPixmap(inner.toRect(), pixmap)
        else:
            painter.setBrush(QColor(self._skill.color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(inner, 5, 5)
            painter.setPen(QColor("#0d1219"))
            font = QFont(self.font())
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, self._skill.name[:1])

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._skill.name)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton == 0:
            return
        if (
            event.position().toPoint() - self._press_pos
        ).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        drag.setMimeData(encode_skill_mime(self._skill.name, -1))
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap)
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint())
        self._press_pos = None
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        payload = decode_skill_mime(event.mimeData())
        if payload is not None and payload[1] >= 0:
            event.acceptProposedAction()
            self._drop_hover = True
            self.update()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_hover = False
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        payload = decode_skill_mime(event.mimeData())
        self._drop_hover = False
        self.update()
        if payload is None:
            return
        skill_name, source = payload
        if source >= 0:
            self.remove_requested.emit(skill_name, source)
        event.acceptProposedAction()
