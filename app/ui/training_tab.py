from __future__ import annotations

import math
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..analyzer import (
    ExpectedEvent,
    analyze,
    build_expected,
    update_actual_potency,
)
from ..capture import GlobalKeyListener
from ..context import AppContext
from ..cooldowns import CooldownTracker
from ..gamedata import icon_file, status_info
from ..gauge import COMBO_WINDOW, GaugeTracker
from ..jobs import gauge_spec_for, new_job_logic
from ..jobs.base import JobLogic
from ..models import Skill, normalize_key_text
from ..session import InputEvent, TrainingSession
from .widgets import HotbarSlot

HOTBAR_COLUMNS = 12
HOTBAR_ROWS = 4
HOTBAR_SLOT_SIZE = 56


def _fmt_clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


class GaugePanel(QFrame):
    """训练页的职业量谱面板（数值为近似模拟）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(4)
        head = QHBoxLayout()
        self.title = QLabel("职业量谱")
        self.title.setObjectName("Muted")
        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        head.addWidget(self.title)
        head.addSpacing(8)
        head.addWidget(self.hint, 1)
        layout.addLayout(head)

        # 随机舞步序列显示在量谱数值上方。
        self.dance_line = QLabel("")
        self.dance_line.setObjectName("NextHint")
        self.dance_line.setTextFormat(Qt.TextFormat.RichText)
        self.dance_line.setWordWrap(True)
        self.dance_line.hide()
        layout.addWidget(self.dance_line)

        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(3)
        layout.addWidget(self.rows_host)

        self.buff_line = QLabel("")
        self.buff_line.setObjectName("Muted")
        self.buff_line.setWordWrap(True)
        self.buff_line.hide()
        layout.addWidget(self.buff_line)

        self.issue = QLabel("")
        self.issue.setObjectName("WarnText")
        self.issue.setWordWrap(True)
        self.issue.hide()
        layout.addWidget(self.issue)

        self._bars: dict[str, QProgressBar] = {}
        self._spec = None

    def set_spec(self, spec, tracker: GaugeTracker | None) -> None:
        self._spec = spec
        self._bars = {}
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget() is not None:
                        child.widget().deleteLater()
        self.title.setText("职业量谱")
        self.hint.setText(spec.hint)
        for resource in spec.resources:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(resource.label)
            label.setObjectName("Muted")
            label.setFixedWidth(76)
            bar = QProgressBar()
            bar.setObjectName("GaugeBar")
            bar.setRange(0, max(1, int(round(resource.maximum))))
            bar.setFormat("%v / " + f"{resource.maximum:g}")
            bar.setFixedHeight(15)
            bar.setTextVisible(True)
            row.addWidget(label)
            row.addWidget(bar, 1)
            self.rows.addLayout(row)
            self._bars[resource.key] = bar
        self.rows_host.setVisible(bool(spec.resources))
        if not spec.resources:
            self.hint.setText(spec.hint or "该职业没有量谱")

        self.buff_line.setVisible(bool(spec.buffs))
        self.refresh(tracker)
        self.clear_issue()

    def refresh(self, tracker: GaugeTracker | None, now: float | None = None) -> None:
        if tracker is None:
            for bar in self._bars.values():
                bar.setValue(0)
            self.buff_line.setText("")
            return
        for resource, value in tracker.snapshot():
            bar = self._bars.get(resource.key)
            if bar is not None:
                bar.setValue(max(0, int(round(value))))
        active = tracker.active_buffs(now)
        self.buff_line.setText(self._buff_html(active))
        tips = [
            f"{buff.label}：{status_info(buff.label).get('description') or '无说明'}"
            for buff, _ in active
        ]
        self.buff_line.setToolTip("\n".join(tips))

    @staticmethod
    def _buff_html(active) -> str:
        if not active:
            return ""
        chips: list[str] = []
        for buff, remain in active:
            info = status_info(buff.label)
            path = icon_file(int(info.get("icon") or 0))
            icon = f'<img src="{path.as_uri()}" width="16" height="16">' if path else ""
            chips.append(
                f"{icon} {buff.label} "
                f'<span style="color:#d8b46a">{remain:.1f}s</span>'
            )
        return "&nbsp;&nbsp;".join(chips)

    def set_issue(self, text: str) -> None:
        self.issue.setText(text)
        self.issue.setVisible(bool(text))

    def clear_issue(self) -> None:
        self.set_issue("")

    def set_dance_text(self, text: str) -> None:
        if not hasattr(self, "dance_line"):
            return
        self.dance_line.setText(text)
        self.dance_line.setVisible(bool(text))


class TrainingTab(QWidget):
    session_finished = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabPage")
        self.ctx = ctx
        self.state = "idle"
        self.session: TrainingSession | None = None
        self.expected_plan: list[ExpectedEvent] = []
        self.slots: list[HotbarSlot] = []
        self._slot_base: dict[int, str] = {}
        self._slot_keys: dict[int, str] = {}
        self._slot_display: dict[int, str] = {}
        self._skill_slot: dict[str, int] = {}
        self._key_to_skill: dict[str, str] = {}
        self._key_to_slot: dict[str, int] = {}
        self._last_key_time: dict[str, float] = {}
        # 连击后续技能名 -> 窗口结束时间（隐式 30s，不打断其他技能）。
        self._combo_until: dict[str, float] = {}
        # 舞步名 -> 技能图标 file URI，用于量谱上方的舞步序列。
        self._step_icon_uris: dict[str, str] = {}
        self.tracker: CooldownTracker | None = None
        self._highlighted = ""
        self._countdown_end = 0.0
        self._duration = float(ctx.settings.duration)
        self._tolerance = ctx.settings.tolerance_ms / 1000.0
        self._live_lines: list[str] = []
        self.gauge: GaugeTracker | None = None
        self.state_issues: list[tuple[float, str, str]] = []
        # 当前职业的专属逻辑（DNC 舞步等），其他职业为 None。
        self.job_logic: JobLogic | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._on_tick)

        self.listener = GlobalKeyListener()
        self.listener.key_pressed.connect(self._on_global_key)
        self.listener.error.connect(self._on_listener_error)

        self._build_ui()
        self.refresh_job()

    # UI
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(14)

        self.settings_card = self._build_settings_card()
        root.addWidget(self.settings_card)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._build_status_card())
        self.skills_card = self._build_skills_card()
        right.addWidget(self.skills_card, 1)
        root.addLayout(right, 1)

        margins = root.contentsMargins()
        self.setMinimumWidth(
            self.settings_card.minimumWidth()
            + self.skills_card.minimumWidth()
            + root.spacing()
            + margins.left()
            + margins.right()
        )

    def _build_settings_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(320)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("训练设置")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.job_label = QLabel("")
        self.job_label.setObjectName("NextHint")
        layout.addWidget(self.job_label)

        self.notes_label = QLabel("")
        self.notes_label.setObjectName("Muted")
        self.notes_label.setWordWrap(True)
        layout.addWidget(self.notes_label)

        divider = QFrame()
        divider.setObjectName("Divider")
        layout.addWidget(divider)

        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 1800)
        self.duration_spin.setSingleStep(5)
        self.duration_spin.setSuffix(" 秒")
        self.duration_spin.setValue(int(self.ctx.settings.duration))
        self.duration_spin.valueChanged.connect(self._on_duration_changed)

        duration_box = QWidget()
        duration_layout = QVBoxLayout(duration_box)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.setSpacing(6)
        duration_layout.addWidget(self.duration_spin)
        presets = QHBoxLayout()
        presets.setSpacing(6)
        for seconds in (30, 60, 120, 180):
            btn = QPushButton(f"{seconds}s")
            btn.setObjectName("Small")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _=False, s=seconds: self.duration_spin.setValue(s)
            )
            presets.addWidget(btn)
        duration_layout.addLayout(presets)
        form.addRow("统计时间", duration_box)

        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(50, 1500)
        self.tolerance_spin.setSingleStep(50)
        self.tolerance_spin.setSuffix(" ms")
        self.tolerance_spin.setValue(int(self.ctx.settings.tolerance_ms))
        self.tolerance_spin.valueChanged.connect(self._on_tolerance_changed)
        form.addRow("时间容差", self.tolerance_spin)

        self.global_check = QCheckBox("启用全局键盘监听")
        self.global_check.setChecked(bool(self.ctx.settings.global_hook))
        self.global_check.toggled.connect(self._on_global_toggled)
        form.addRow("", self.global_check)

        layout.addLayout(form)

        self.hook_hint = QLabel("")
        self.hook_hint.setObjectName("Hint")
        self.hook_hint.setWordWrap(True)
        layout.addWidget(self.hook_hint)

        layout.addStretch(1)

        self.start_btn = QPushButton("开始训练")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._start)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止训练")
        self.stop_btn.setObjectName("Ghost")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_clicked)
        layout.addWidget(self.stop_btn)

        divider2 = QFrame()
        divider2.setObjectName("Divider")
        layout.addWidget(divider2)

        tip = QLabel(
            "开始后有 3 秒倒计时。全局监听开启时可直接在游戏内按键；"
            "关闭时在本窗口按映射键。结束后自动跳到「分析报告」。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        return card

    def _build_status_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.state_label = QLabel("待机")
        self.state_label.setObjectName("StateLabel")
        self.timer_label = QLabel("00:00")
        self.timer_label.setObjectName("BigTimer")
        top.addWidget(self.state_label)
        top.addStretch(1)
        top.addWidget(self.timer_label)
        layout.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(14)
        layout.addWidget(self.progress)

        self.next_label = QLabel("准备就绪")
        self.next_label.setObjectName("NextHint")
        layout.addWidget(self.next_label)

        self.ticker = QLabel("")
        self.ticker.setObjectName("Ticker")
        self.ticker.setWordWrap(True)
        self.ticker.setMinimumHeight(18)
        layout.addWidget(self.ticker)

        self.gauge_panel = GaugePanel()
        layout.addWidget(self.gauge_panel)
        return card

    def _build_skills_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        row = QHBoxLayout()
        title = QLabel("技能键位")
        title.setObjectName("CardTitle")
        hint = QLabel("热键栏为只读；键位请在「键位映射」页修改")
        hint.setObjectName("Hint")
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(hint)
        layout.addLayout(row)

        self.grid_host = QWidget()
        self.grid_host.setObjectName("SkillGrid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnMinimumWidth(0, 40)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # 完整显示 12 列热键栏所需的最小宽度：栏位 + 列间距 + 右侧留白。
        grid_width = (
            HOTBAR_COLUMNS * HOTBAR_SLOT_SIZE
            + (HOTBAR_COLUMNS - 1) * self.grid.horizontalSpacing()
            + self.grid.contentsMargins().right()
        )
        self.grid_host.setMinimumWidth(grid_width)
        margins = layout.contentsMargins()
        card.setMinimumWidth(margins.left() + margins.right() + grid_width)

        self.skill_scroll = QScrollArea()
        self.skill_scroll.setWidgetResizable(True)
        self.skill_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.skill_scroll.setWidget(self.grid_host)
        self.skill_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        layout.addWidget(self.skill_scroll, 1)

        self.no_skill_label = QLabel("尚未配置技能，请到「键位映射」页添加。")
        self.no_skill_label.setObjectName("Muted")
        layout.addWidget(self.no_skill_label)
        return card

    # state
    def is_recording(self) -> bool:
        return self.state == "recording"

    def refresh_job(self) -> None:
        job = self.ctx.current_job()
        job.apply_hotbar_keys()
        self.job_label.setText(f"当前：{job.name}  ·  GCD {job.gcd:g}s")
        self.notes_label.setText(job.notes or "可在「标准循环」页编辑标准时间点。")

        self._rebuild_hotbar(job)

        if GlobalKeyListener.available():
            self.hook_hint.setText(
                "全局监听已就绪；如游戏以管理员权限运行，本工具也需以管理员身份启动。"
            )
            self.hook_hint.setObjectName("Hint")
        else:
            self.hook_hint.setText(
                "未检测到 pynput，全局监听不可用；仍可在本窗口按键训练。"
            )
            self.hook_hint.setObjectName("WarnText")
        self.hook_hint.style().unpolish(self.hook_hint)
        self.hook_hint.style().polish(self.hook_hint)

        if self.state == "idle":
            self._reset_display()

    def _rebuild_hotbar(self, job) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.slots = []
        self._slot_base = {}
        self._slot_keys = {}
        self._slot_display = {}
        self._skill_slot = {}
        self._key_to_skill = {}
        self._key_to_slot = {}

        names = list(job.hotbar)
        keys = list(job.hotbar_keys)
        rows = max(
            HOTBAR_ROWS,
            (len(names) + HOTBAR_COLUMNS - 1) // HOTBAR_COLUMNS,
        )
        for index in range(rows * HOTBAR_COLUMNS):
            name = names[index] if index < len(names) else ""
            key = normalize_key_text(keys[index]) if index < len(keys) else ""
            skill = job.skill(name) if name else None
            slot = HotbarSlot(
                index, read_only=True, size=HOTBAR_SLOT_SIZE, parent=self.grid_host
            )
            slot.set_skill(skill, key)
            if key:
                self._slot_keys[index] = key
            if skill is not None:
                slot.activated.connect(self._on_slot_activated)
                self._slot_base[index] = skill.name
                self._slot_display[index] = skill.name
                self._skill_slot.setdefault(skill.name, index)
            self.grid.addWidget(slot, index // HOTBAR_COLUMNS, index % HOTBAR_COLUMNS)
            self.slots.append(slot)

        self._rebuild_key_map()
        self.no_skill_label.setVisible(not names)

    def _rebuild_key_map(self) -> None:
        self._key_to_skill = {}
        self._key_to_slot = {}
        for index, key in self._slot_keys.items():
            name = self._slot_display.get(index, "")
            if key and name:
                self._key_to_skill.setdefault(key, name)
                self._key_to_slot.setdefault(key, index)

    def _set_slot_display(self, index: int, skill_name: str) -> None:
        job = self.ctx.current_job()
        skill = job.skill(skill_name)
        if skill is None or index >= len(self.slots):
            return
        self._slot_display[index] = skill_name
        self._skill_slot = {}
        for slot_index, name in self._slot_display.items():
            self._skill_slot.setdefault(name, slot_index)
        self.slots[index].set_skill(skill, self._slot_keys.get(index, ""))
        self._rebuild_key_map()

    def _reset_transforms(self) -> None:
        for index, base in self._slot_base.items():
            if self._slot_display.get(index, "") != base:
                self._set_slot_display(index, base)

    def _apply_transform(self, skill_name: str, t: float, index: int = -1) -> None:
        """施放后刷新栏位：职业状态驱动的（如 DNC ）优先，其他沿用变化技能表。"""
        if self.job_logic is not None and self.job_logic.state_driven_display:
            self._sync_job_state(t)
            return
        if index < 0:
            index = self._skill_slot.get(skill_name, -1)
        if index < 0:
            return
        job = self.ctx.current_job()
        skill = job.skill(skill_name)
        base = self._slot_base.get(index, skill_name)
        if skill is not None:
            target = self._pick_transform(skill, t)
            if target:
                self._set_slot_display(index, target)
            elif self._slot_display.get(index, "") != base:
                self._set_slot_display(index, base)

    def _pick_transform(self, skill: Skill, t: float) -> str:
        """在多个变化目标中优先选择标准循环接下来会使用的技能。"""
        job = self.ctx.current_job()
        targets = [name for name in skill.transform if job.skill(name)]
        if not targets:
            return ""
        upcoming = [e.skill for e in self.expected_plan if e.t > t + 0.01][:12]
        for name in upcoming:
            if name in targets:
                return name
        return targets[0]

    # 职业专属状态（DNC 舞步等，由 app/jobs 下的职业逻辑维护）
    def _sync_job_state(self, t: float) -> None:
        logic = self.job_logic
        if logic is None:
            return
        message = logic.tick(t)
        if message:
            self.ticker.setText(message)
        for index, base in self._slot_base.items():
            display = logic.display(base, t, self.gauge)
            if display and self._slot_display.get(index, "") != display:
                self._set_slot_display(index, display)

    def _job_status_text(self, t: float) -> str:
        if self.job_logic is None:
            return ""
        return self.job_logic.status_text(t, self._step_icon_uri)

    def _update_combo_window(self, used: str, t: float) -> None:
        """维护连击后续技能的隐式 30s 窗口；使用其他技能不会清除窗口。"""
        self._combo_until.pop(used, None)
        expired = [name for name, until in self._combo_until.items() if until <= t]
        for name in expired:
            self._combo_until.pop(name, None)
        for skill in self.ctx.current_job().skills:
            if skill.combo == used:
                self._combo_until[skill.name] = t + COMBO_WINDOW

    def _step_icon_uri(self, name: str) -> str:
        cached = self._step_icon_uris.get(name)
        if cached is not None:
            return cached
        skill = self.ctx.current_job().skill(name)
        path = icon_file(skill.icon) if skill is not None else None
        uri = path.as_uri() if path else ""
        self._step_icon_uris[name] = uri
        return uri

    def refresh_preview(self) -> None:
        job = self.ctx.current_job()
        self.job_label.setText(f"当前：{job.name}  ·  GCD {job.gcd:g}s")
        self.notes_label.setText(job.notes or "可在「标准循环」页编辑标准时间点。")
        if self.state == "idle":
            self._reset_display()

    def _setup_gauge(self, job) -> None:
        self.gauge = GaugeTracker(gauge_spec_for(job))
        self.state_issues = []
        self._combo_until.clear()
        self.job_logic = new_job_logic(job)
        self.gauge_panel.set_spec(self.gauge.spec, self.gauge)
        self.gauge_panel.set_dance_text("")

    def _reset_display(self) -> None:
        job = self.ctx.current_job()
        self._setup_gauge(job)
        duration = float(self.duration_spin.value())
        self._duration = duration
        self.expected_plan = build_expected(job, duration)
        self.state_label.setText("待机")
        self.timer_label.setText(f"00:00 / {_fmt_clock(duration)}")
        self.progress.setValue(0)
        self.next_label.setText("准备就绪")
        self.ticker.setText("")
        self.tracker = None
        self._clear_masks()

    def _clear_masks(self) -> None:
        if self.job_logic is not None:
            self.job_logic.reset()
        self._reset_transforms()
        self._combo_until.clear()
        for slot in self.slots:
            slot.set_cooldown(0.0, 0.0)
            slot.set_charges(0, 0)
            slot.set_locked(False)
            slot.set_highlight(False)
            slot.set_proc(False)
            slot.set_combo(False)
        self._highlighted = ""
        self.gauge_panel.set_dance_text("")

    def _update_masks(self, elapsed: float) -> None:
        job = self.ctx.current_job()
        tracker = self.tracker
        if tracker is None:
            return
        self._sync_job_state(elapsed)
        next_skill = (
            self.job_logic.queued_skill(elapsed) if self.job_logic is not None else ""
        )
        gcd_left = tracker.gcd_remaining(elapsed)
        gcd_span = tracker.gcd_span
        gauge = self.gauge
        for index, name in self._slot_display.items():
            if index >= len(self.slots):
                continue
            slot = self.slots[index]
            skill = job.skill(name)
            if skill is None:
                continue
            recast = tracker.recast_of(skill)
            charges = tracker.max_charges(name)
            if charges > 1:
                # 充能技能：显示可用层数与正在恢复那一层的倒计时。
                ready_charges = tracker.ready_charges(name, elapsed)
                recharge = tracker.recharge_remaining(name, elapsed)
                slot.set_charges(ready_charges, charges)
                if recharge > 0.05:
                    slot.set_cooldown(recharge, recast)
                elif skill.gcd and gcd_left > 0.05:
                    slot.set_cooldown(gcd_left, gcd_span)
                else:
                    slot.set_cooldown(0.0, 0.0)
            else:
                slot.set_charges(0, 0)
                own = tracker.remaining(name, elapsed)
                if skill.gcd:
                    # GCD 技能同步显示公共复唱；自身复唱更长时（如舞步）显示自身复唱。
                    if own > gcd_left:
                        slot.set_cooldown(own, recast)
                    else:
                        slot.set_cooldown(gcd_left, gcd_span)
                else:
                    # 能力技只使用自身复唱，不参与公共复唱。
                    slot.set_cooldown(own, recast)
            available = gauge.available(name, elapsed) if gauge is not None else True
            allowed = (
                self.job_logic.allows(name, elapsed)
                if self.job_logic is not None
                else True
            )
            unusable = not available or not allowed
            slot.set_locked(unusable)
            slot.set_highlight(name == next_skill)
            slot.set_combo(
                bool(skill.combo)
                and not unusable
                and self._combo_until.get(name, 0.0) > elapsed
            )
            base = self._slot_base.get(index, "")
            proc = False
            if available and allowed and gauge is not None:
                if self.job_logic is not None and self.job_logic.suppress_proc(name):
                    proc = False
                elif gauge.empowered(name, elapsed):
                    proc = True
                elif name != base:
                    proc = True
            slot.set_proc(proc)
        self._highlighted = next_skill
        self.gauge_panel.set_dance_text(self._job_status_text(elapsed))

    def _on_duration_changed(self, value: int) -> None:
        self.ctx.settings.duration = int(value)
        self.ctx.save_settings()
        if self.state == "idle":
            self._reset_display()

    def _on_tolerance_changed(self, value: int) -> None:
        self.ctx.settings.tolerance_ms = int(value)
        self.ctx.save_settings()

    def _on_global_toggled(self, checked: bool) -> None:
        self.ctx.settings.global_hook = bool(checked)
        self.ctx.save_settings()

    def _set_controls_busy(self, busy: bool) -> None:
        self.duration_spin.setEnabled(not busy)
        self.tolerance_spin.setEnabled(not busy)
        self.global_check.setEnabled(not busy)
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    # train
    def _start(self) -> None:
        if self.state != "idle":
            return
        job = self.ctx.current_job()
        if not job.rotation:
            QMessageBox.warning(
                self,
                "无法开始",
                "当前职业还没有标准循环，请先在「标准循环」页添加步骤。",
            )
            return
        if not job.skills:
            QMessageBox.warning(
                self, "无法开始", "当前职业还没有技能，请先在「键位映射」页添加技能。"
            )
            return
        if not any(s.key for s in job.skills):
            QMessageBox.warning(
                self,
                "无法开始",
                "当前职业还没有绑定任何键位，请先在「键位映射」页配置。",
            )
            return

        self._duration = float(self.duration_spin.value())
        self._tolerance = self.tolerance_spin.value() / 1000.0
        self.expected_plan = build_expected(job, self._duration)
        self.session = TrainingSession(job, self._duration)
        self.tracker = CooldownTracker(job)
        self._setup_gauge(job)
        self._clear_masks()
        self._live_lines = []
        self._last_key_time.clear()
        self.ticker.setText("")
        self.next_label.setText("倒计时结束后开始记录")

        if self.global_check.isChecked():
            if not self.listener.start():
                QMessageBox.warning(
                    self,
                    "全局监听启动失败",
                    "无法启动全局键盘监听，本次仅记录本窗口内的按键。\n\n"
                    "可尝试以管理员身份运行本工具，或在训练设置中关闭全局监听。",
                )

        self.state = "countdown"
        self._countdown_end = time.monotonic() + 3.0
        self._timer.start()
        self._set_controls_busy(True)
        self.busy_changed.emit(True)
        self.timer_label.setText("00:00 / " + _fmt_clock(self._duration))
        self.progress.setValue(0)

    def _begin_recording(self) -> None:
        if self.session is None:
            return
        self.session.start()
        self.state = "recording"
        self.state_label.setText("录制中")
        self.next_label.setText("开始记录，按职业技能循环施放")

    def _on_tick(self) -> None:
        if self.state == "countdown":
            remain = self._countdown_end - time.monotonic()
            if remain <= 0:
                self._begin_recording()
            else:
                count = int(math.ceil(remain))
                self.state_label.setText(f"倒计时 {count}")
                self.timer_label.setText(f"{count}")
            return
        if self.state != "recording" or self.session is None:
            return

        elapsed = self.session.elapsed
        self.timer_label.setText(
            f"{_fmt_clock(elapsed)} / {_fmt_clock(self._duration)}"
        )
        self.progress.setValue(int(elapsed / self._duration * 1000))
        hint = (
            self.job_logic.progress_hint(elapsed)
            if self.job_logic is not None
            else ""
        )
        self.next_label.setText(hint or "录制中")
        self._update_masks(elapsed)
        if self.gauge is not None:
            self.gauge_panel.refresh(self.gauge, elapsed)

        if elapsed >= self._duration:
            self._finish()

    def _stop_clicked(self) -> None:
        if self.state == "countdown":
            self._cancel_countdown()
        elif self.state == "recording":
            self._finish()

    def _cancel_countdown(self) -> None:
        self._timer.stop()
        self.listener.stop()
        self.state = "idle"
        self.session = None
        self.tracker = None
        self._clear_masks()
        self._set_controls_busy(False)
        self.busy_changed.emit(False)
        self._reset_display()

    def _finish(self) -> None:
        if self.state != "recording" or self.session is None:
            return
        job = self.ctx.current_job()
        elapsed = self.session.stop()
        self._timer.stop()
        self.listener.stop()
        self.state = "idle"
        self._set_controls_busy(False)
        self.busy_changed.emit(False)

        result = analyze(job, self.session.events, elapsed, self._tolerance)
        result.state_issues = list(self.state_issues)
        update_actual_potency(
            job,
            result,
            {(round(t, 2), name) for t, name, _ in self.state_issues},
        )
        if self.state_issues:
            examples = "、".join(
                f"{name}（{reason}）" for _, name, reason in self.state_issues[:3]
            )
            result.suggestions.append(
                f"状态不足 {len(self.state_issues)} 次：{examples}。请先补足量谱再施放这些技能。"
            )
        if result.potency_ratio > 0 and result.potency_ratio < 0.9:
            basis = "标准循环" if result.expected_potency > 0 else "理论威力上限"
            reference = (
                f"{result.expected_potency:.0f}"
                if result.expected_potency > 0
                else f"{result.actual_potency / max(result.potency_ratio, 1e-9):.0f}"
            )
            result.suggestions.append(
                f"有效威力 {result.actual_potency:.0f} / {basis} {reference}"
                f"（{result.potency_ratio * 100:.0f}%，实用性{result.potency_grade}）："
                "减少空转与低威力技能，优先打满高威力连击。"
            )
        self.state_label.setText("已生成报告")
        self.timer_label.setText(
            f"{_fmt_clock(elapsed)} / {_fmt_clock(self._duration)}"
        )
        self.progress.setValue(int(min(elapsed / self._duration, 1.0) * 1000))
        self.next_label.setText("训练结束，已生成循环对比分析")
        self.session = None
        self.tracker = None
        self._clear_masks()
        self.session_finished.emit(result)

    # input
    def handle_qt_key(self, canonical: str) -> None:
        self._on_key(canonical, source="app")

    def _on_global_key(self, canonical: str) -> None:
        self._on_key(canonical, source="global")

    def _on_key(self, canonical: str, source: str) -> None:
        if not self.is_recording() or self.session is None:
            return
        key = normalize_key_text(canonical)
        skill_name = self._key_to_skill.get(key, "")
        if not skill_name:
            return
        # 应用内与全局监听可能对同一次按键各上报一次，先去重。
        now = time.monotonic()
        if now - self._last_key_time.get(key, 0.0) < 0.09:
            return
        self._last_key_time[key] = now
        self._try_cast(skill_name, key, source, self._key_to_slot.get(key, -1))

    def _on_slot_activated(self, index: int) -> None:
        name = self._slot_display.get(index, "")
        if name:
            self._try_cast(name, self._slot_keys.get(index, ""), "click", index)

    def _try_cast(
        self, skill_name: str, key: str, source: str, slot_index: int = -1
    ) -> None:
        if not self.is_recording() or self.session is None:
            return
        job = self.ctx.current_job()
        skill = job.skill(skill_name)
        if skill is None:
            return
        t = self.session.elapsed
        self._sync_job_state(t)
        if self.job_logic is not None:
            reason = self.job_logic.block_reason(skill_name, t)
            if reason:
                self._blocked(skill_name, reason)
                return

        if self.tracker is not None:
            gcd_left = self.tracker.gcd_remaining(t)
            if skill.gcd and gcd_left > 0.12:
                self._blocked(skill_name, "公共复唱中", gcd_left)
                return
            own_left = self.tracker.remaining(skill_name, t)
            if own_left > 0.12:
                self._blocked(skill_name, "复唱中", own_left)
                return
        if self.gauge is not None:
            reason = self.gauge.check(skill_name, t)
            if reason:
                self._blocked(skill_name, f"状态不足 · {reason}")
                return
        event = self.session.add_skill(skill_name, source=source, key=key)
        if event is not None:
            self._on_event(event, slot_index)

    def _blocked(
        self, skill_name: str, reason: str, remain: float | None = None
    ) -> None:
        text = f"{skill_name} 无法施放：{reason}"
        if remain is not None:
            text += f"，剩余 {max(remain, 0):.1f}s"
        self.ticker.setText(text)

    def _on_event(self, event: InputEvent, slot_index: int = -1) -> None:
        if self.tracker is not None:
            self.tracker.on_cast(event.skill, event.t)
        if self.gauge is not None:
            skill = self.ctx.current_job().skill(event.skill)
            ok, reason = self.gauge.cast(
                event.skill, is_gcd=bool(skill and skill.gcd), t=event.t
            )
            if not ok:
                self.state_issues.append((event.t, event.skill, reason))
                self.gauge_panel.set_issue(
                    f"{event.t:5.2f}s  {event.skill}：状态不足 · {reason}"
                )
            else:
                self.gauge_panel.clear_issue()
                self._update_combo_window(event.skill, event.t)
            self.gauge_panel.refresh(self.gauge, event.t)
        else:
            self._update_combo_window(event.skill, event.t)
        if slot_index < 0:
            slot_index = self._skill_slot.get(event.skill, -1)
        if slot_index >= 0 and slot_index < len(self.slots):
            self.slots[slot_index].flash()
        if self.job_logic is not None:
            message = self.job_logic.on_cast(
                event.skill, event.t, set(self._slot_base.values())
            )
            if message:
                self.ticker.setText(message)
        self._apply_transform(event.skill, event.t, slot_index)
        if self.tracker is not None:
            self._update_masks(event.t)
        line = f"{event.t:5.2f}s  {event.skill}"
        if (
            self.gauge is not None
            and self.state_issues
            and self.state_issues[-1][0] == event.t
            and self.state_issues[-1][1] == event.skill
        ):
            line += "（状态不足）"
        self._live_lines.append(line)
        self._live_lines = self._live_lines[-6:]
        self.ticker.setText("    ·    ".join(self._live_lines))

    def _on_listener_error(self, message: str) -> None:
        self.hook_hint.setText(f"全局监听错误：{message}")
        self.hook_hint.setObjectName("WarnText")
        self.hook_hint.style().unpolish(self.hook_hint)
        self.hook_hint.style().polish(self.hook_hint)

    def shutdown(self) -> None:
        self._timer.stop()
        self.listener.stop()
