from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..keys import combine_key, pretty_key
from ..models import Skill, normalize_key_text
from .widgets import HotbarSlot, KeyCaptureDialog, SkillPoolItem

COLOR_PALETTE = [
    "#e0794a",
    "#e0603c",
    "#d9b55a",
    "#4fa3d1",
    "#9a7fe0",
    "#57c38a",
    "#d05a6b",
    "#5c9fe0",
]
DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
ROW_MODIFIERS: list[set[str]] = [
    set(),
    {"ctrl"},
    {"alt"},
    {"shift"},
    {"ctrl", "shift"},
    {"alt", "shift"},
    {"ctrl", "alt", "shift"},
]
POOL_COLUMNS = 12


class KeymapTab(QWidget):
    COLUMNS = 12
    MIN_ROWS = 4

    def __init__(
        self, ctx: AppContext, main_window, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TabPage")
        self.ctx = ctx
        self.main = main_window
        self._selected = 0
        self._conflicts: dict[str, list[str]] = {}
        self.slots: list[HotbarSlot] = []
        self._build_ui()
        self.refresh()

    # UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)

        top = QFrame()
        top.setObjectName("Card")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(18, 14, 18, 14)
        top_layout.setSpacing(8)

        row = QHBoxLayout()
        title = QLabel("键位映射 · 热键栏")
        title.setObjectName("PageTitle")
        self.job_label = QLabel("")
        self.job_label.setObjectName("Muted")
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        row.addWidget(title)
        row.addSpacing(8)
        row.addWidget(self.job_label)
        row.addWidget(self.count_label)
        top_layout.addLayout(row)

        hint = QLabel(
            "图标采用游戏原生热键栏布局：拖动图标可在栏位间调整位置，从下方技能池拖入空栏位；\n"
            "双击栏位改键，右键可清除热键、换色或重命名。热键属于栏位，拖拽图标不会改变栏位的热键。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        top_layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        auto_btn = QPushButton("自动分配热键")
        auto_btn.setObjectName("Ghost")
        auto_btn.clicked.connect(self._auto_assign)
        tidy_btn = QPushButton("整理栏位")
        tidy_btn.setObjectName("Ghost")
        tidy_btn.clicked.connect(self._tidy_hotbar)

        buttons.addWidget(auto_btn)
        buttons.addWidget(tidy_btn)
        buttons.addStretch(1)
        top_layout.addLayout(buttons)

        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("WarnText")
        self.conflict_label.setWordWrap(True)
        top_layout.addWidget(self.conflict_label)
        root.addWidget(top)

        bar = QFrame()
        bar.setObjectName("Card")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(14, 12, 14, 12)
        bar_layout.setSpacing(8)
        bar_head = QHBoxLayout()
        bar_title = QLabel("热键栏")
        bar_title.setObjectName("CardTitle")
        bar_head.addWidget(bar_title)
        bar_head.addSpacing(8)
        bar_head.addStretch(1)
        bar_layout.addLayout(bar_head)

        self.hotbar_host = QWidget()
        self.hotbar_grid = QGridLayout(self.hotbar_host)
        self.hotbar_grid.setContentsMargins(4, 2, 4, 2)
        self.hotbar_grid.setHorizontalSpacing(6)
        self.hotbar_grid.setVerticalSpacing(6)
        self.hotbar_grid.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        hotbar_scroll = QScrollArea()
        hotbar_scroll.setWidgetResizable(True)
        hotbar_scroll.setWidget(self.hotbar_host)
        hotbar_scroll.setMinimumHeight(150)
        bar_layout.addWidget(hotbar_scroll, 1)
        root.addWidget(bar, 3)

        pool = QFrame()
        pool.setObjectName("Card")
        pool_layout = QVBoxLayout(pool)
        pool_layout.setContentsMargins(12, 12, 12, 12)
        pool_layout.setSpacing(6)
        pool_head = QHBoxLayout()
        pool_title = QLabel("技能池")
        pool_title.setObjectName("CardTitle")
        self.pool_hint = QLabel(
            "拖拽图标到热键栏；双击放入空栏位；把栏位图标拖到此处可从栏位移除技能"
        )
        self.pool_hint.setObjectName("Hint")
        pool_head.addWidget(pool_title)
        pool_head.addSpacing(8)
        pool_head.addWidget(self.pool_hint)
        pool_head.addStretch(1)
        pool_layout.addLayout(pool_head)

        self.pool_host = QWidget()
        self.pool_grid = QGridLayout(self.pool_host)
        self.pool_grid.setContentsMargins(4, 2, 4, 2)
        self.pool_grid.setHorizontalSpacing(8)
        self.pool_grid.setVerticalSpacing(6)
        self.pool_grid.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        pool_scroll = QScrollArea()
        pool_scroll.setWidgetResizable(True)
        pool_scroll.setWidget(self.pool_host)
        pool_layout.addWidget(pool_scroll, 1)
        root.addWidget(pool, 2)

    # refresh
    def refresh(self) -> None:
        job = self.ctx.current_job()
        job.apply_hotbar_keys()
        self.job_label.setText(f"当前职业：{job.name}")
        self._conflicts = self._collect_conflicts()
        self._rebuild_hotbar(job)
        self._rebuild_pool(job)
        self._refresh_conflict_label()
        placed = sum(1 for name in job.hotbar if name)
        self.count_label.setText(
            f"{len(job.skills)} 个技能 · {placed} 个已上栏 · {len(self._conflicts)} 组键位冲突"
        )

    def _collect_conflicts(self) -> dict[str, list[str]]:
        job = self.ctx.current_job()
        seen: dict[str, list[str]] = {}
        for index, name in enumerate(job.hotbar):
            if not name:
                continue
            key = (
                normalize_key_text(job.hotbar_keys[index])
                if index < len(job.hotbar_keys)
                else ""
            )
            if key:
                seen.setdefault(key, []).append(name)
        return {key: names for key, names in seen.items() if len(names) > 1}

    def _refresh_conflict_label(self) -> None:
        if not self._conflicts:
            self.conflict_label.setText("")
            return
        detail = "；".join(
            f"{pretty_key(key)} → {'、'.join(names)}"
            for key, names in self._conflicts.items()
        )
        self.conflict_label.setText(f"键位冲突：{detail}")

    def _rebuild_hotbar(self, job) -> None:
        self._clear_grid(self.hotbar_grid)
        self.slots = []
        total = max(
            self.MIN_ROWS * self.COLUMNS,
            ((len(job.hotbar) + self.COLUMNS - 1) // self.COLUMNS) * self.COLUMNS,
        )
        for index in range(total):
            name = job.hotbar[index] if index < len(job.hotbar) else ""
            key = job.hotbar_keys[index] if index < len(job.hotbar_keys) else ""
            skill = job.skill(name) if name else None
            slot = HotbarSlot(index)
            slot.set_skill(
                skill, key, bool(key) and normalize_key_text(key) in self._conflicts
            )
            slot.selected.connect(self._select_slot)
            slot.activated.connect(self._bind_at)
            slot.context_requested.connect(self._slot_menu)
            slot.dropped_skill.connect(self._on_slot_dropped)
            slot.set_selected(index == self._selected)
            self.hotbar_grid.addWidget(
                slot, index // self.COLUMNS, index % self.COLUMNS
            )
            self.slots.append(slot)

    def _rebuild_pool(self, job) -> None:
        self._clear_grid(self.pool_grid)
        placed = set(job.hotbar)
        for index, skill in enumerate(job.skills):
            item = SkillPoolItem(skill, skill.name in placed)
            item.activated.connect(self._place_from_pool)
            item.remove_requested.connect(self._on_pool_removed)
            self.pool_grid.addWidget(item, index // POOL_COLUMNS, index % POOL_COLUMNS)

    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _select_slot(self, index: int) -> None:
        for slot in self.slots:
            slot.set_selected(slot.index == index)
        self._selected = index

    def _slot_at(self, index: int) -> tuple[Skill | None, int]:
        job = self.ctx.current_job()
        if index < 0 or index >= len(job.hotbar):
            return None, index
        name = job.hotbar[index]
        return (job.skill(name) if name else None), index

    # edits
    def _notify(self) -> None:
        self.ctx.save_jobs()
        self.refresh()
        if self.main is not None:
            self.main.refresh_from_keymap()

    def _bind_at(self, index: int) -> None:
        job = self.ctx.current_job()
        current = job.hotbar_keys[index] if index < len(job.hotbar_keys) else ""
        dialog = KeyCaptureDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        while len(job.hotbar) <= index:
            job.hotbar.append("")
        while len(job.hotbar_keys) <= index:
            job.hotbar_keys.append("")
        job.hotbar_keys[index] = "" if dialog.cleared else (dialog.result_key or "")
        job.normalize_hotbar()
        job.apply_hotbar_keys()
        self._notify()

    def _clear_key(self, index: int) -> None:
        job = self.ctx.current_job()
        if 0 <= index < len(job.hotbar_keys):
            job.hotbar_keys[index] = ""
            job.apply_hotbar_keys()
            self._notify()

    def _rename_skill(self, skill: Skill) -> None:
        job = self.ctx.current_job()
        old = skill.name
        name, ok = QInputDialog.getText(self, "重命名技能", "技能名称：", text=old)
        name = (name or "").strip()
        if not ok or not name or name == old:
            return
        if any(s.name == name for s in job.skills if s is not skill):
            QMessageBox.warning(self, "重命名失败", f"已存在技能「{name}」。")
            return
        skill.name = name
        job.hotbar = [name if slot == old else slot for slot in job.hotbar]
        for step in job.rotation:
            if step.skill == old:
                step.skill = name
        self._notify()

    def _pick_color(self, skill: Skill) -> None:
        color = QColorDialog.getColor(QColor(skill.color), self, "选择技能颜色")
        if color.isValid():
            skill.color = color.name()
            self._notify()

    def _slot_menu(self, index: int, position: QPoint) -> None:
        self._select_slot(index)
        job = self.ctx.current_job()
        skill, _ = self._slot_at(index)
        menu = QMenu(self)
        if skill is None:
            menu.addAction("设置热键…", lambda: self._bind_at(index))
            menu.addAction("清除热键", lambda: self._clear_key(index))
            menu.addSeparator()
            menu.addAction("在此添加技能…", lambda: self._add_skill(index))
        else:
            menu.addAction("设置热键…", lambda: self._bind_at(index))
            menu.addAction("清除热键", lambda: self._clear_key(index))
            menu.addSeparator()
            menu.addAction("选择颜色…", lambda: self._pick_color(skill))
            menu.addAction("重命名…", lambda: self._rename_skill(skill))
            menu.addSeparator()
            menu.addAction("移出热键栏", lambda: self._clear_slot(index))
            menu.addAction("从技能列表删除", lambda: self._delete_skill(skill))
        menu.exec(position)

    def _clear_slot(self, index: int) -> None:
        job = self.ctx.current_job()
        if 0 <= index < len(job.hotbar):
            job.hotbar[index] = ""
            job.normalize_hotbar()
            job.apply_hotbar_keys()
            self._notify()

    def _on_pool_removed(self, _name: str, source: int) -> None:
        self._clear_slot(source)

    # drag
    def _on_slot_dropped(self, skill_name: str, _source: int, target: int) -> None:
        self._place_skill(skill_name, target)

    def _place_from_pool(self, skill_name: str) -> None:
        job = self.ctx.current_job()
        target: int | None = None
        if 0 <= self._selected < len(job.hotbar) and not job.hotbar[self._selected]:
            target = self._selected
        if target is None:
            try:
                target = job.hotbar.index("")
            except ValueError:
                target = len(job.hotbar)
        self._place_skill(skill_name, target)

    def _place_skill(self, skill_name: str, target: int) -> None:
        job = self.ctx.current_job()
        hotbar = job.hotbar
        while len(hotbar) <= target:
            hotbar.append("")
        while len(job.hotbar_keys) <= target:
            job.hotbar_keys.append("")
        existing = hotbar.index(skill_name) if skill_name in hotbar else -1
        if 0 <= existing != target:
            hotbar[existing], hotbar[target] = hotbar[target], skill_name
        else:
            displaced = hotbar[target]
            if displaced and displaced != skill_name:
                try:
                    spare = hotbar.index("")
                except ValueError:
                    hotbar.append("")
                    job.hotbar_keys.append("")
                    spare = len(hotbar) - 1
                hotbar[spare] = displaced
            hotbar[target] = skill_name
        job.normalize_hotbar()
        job.apply_hotbar_keys()
        self._selected = target
        self._notify()

    # buttons
    def _add_skill(self, place_index: int | None = None) -> None:
        job = self.ctx.current_job()
        name, ok = QInputDialog.getText(self, "添加技能", "技能名称：")
        name = (name or "").strip()
        if not ok or not name:
            return
        if any(s.name == name for s in job.skills):
            QMessageBox.warning(self, "添加失败", f"已存在技能「{name}」。")
            return
        color = COLOR_PALETTE[len(job.skills) % len(COLOR_PALETTE)]
        job.skills.append(Skill(name=name, key="", color=color))
        if place_index is not None and place_index >= 0:
            while len(job.hotbar) <= place_index:
                job.hotbar.append("")
            while len(job.hotbar_keys) <= place_index:
                job.hotbar_keys.append("")
            job.hotbar[place_index] = name
            job.normalize_hotbar()
            job.apply_hotbar_keys()
            self._selected = place_index
        self._notify()

    def _delete_selected(self) -> None:
        skill, _ = self._slot_at(self._selected)
        if skill is None:
            QMessageBox.information(self, "提示", "请先选中一个已放置技能的栏位。")
            return
        self._delete_skill(skill)

    def _delete_skill(self, skill: Skill) -> None:
        job = self.ctx.current_job()
        used = any(step.skill == skill.name for step in job.rotation)
        text = f"确定删除技能「{skill.name}」吗？"
        if used:
            text += "\n\n该技能仍被标准循环引用 （循环步骤不会被自动删除）。"
        if (
            QMessageBox.question(self, "删除技能", text)
            != QMessageBox.StandardButton.Yes
        ):
            return
        job.skills = [s for s in job.skills if s is not skill]
        job.hotbar = ["" if slot == skill.name else slot for slot in job.hotbar]
        job.normalize_hotbar()
        job.apply_hotbar_keys()
        self._notify()

    def _tidy_hotbar(self) -> None:
        job = self.ctx.current_job()
        keys = list(job.hotbar_keys)
        while len(keys) < len(job.hotbar):
            keys.append("")
        names: list[str] = []
        name_keys: list[str] = []
        placed: set[str] = set()
        for name, key in zip(job.hotbar, keys):
            if name and name not in placed:
                names.append(name)
                name_keys.append(key)
                placed.add(name)
        job.hotbar = names
        job.hotbar_keys = name_keys
        job.normalize_hotbar()
        job.apply_hotbar_keys()
        self._notify()

    def _auto_assign(self) -> None:
        job = self.ctx.current_job()
        if not job.skills:
            QMessageBox.information(self, "提示", "还没有技能。")
            return
        if (
            QMessageBox.question(
                self,
                "自动分配热键",
                "将按热键栏顺序分配数字键（第 1 行 1 → 0 ，之后各行加 Ctrl / Alt / Shift 修饰）",
                "已有绑定会被覆盖。继续吗？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        keys = [""] * len(job.hotbar)
        for index, name in enumerate(job.hotbar):
            if not name:
                continue
            row, column = divmod(index, self.COLUMNS)
            mods = ROW_MODIFIERS[row] if row < len(ROW_MODIFIERS) else ROW_MODIFIERS[-1]
            base = DIGITS[column]
            keys[index] = combine_key(base, mods) if mods else base
        job.hotbar_keys = keys
        job.apply_hotbar_keys()
        self._notify()
