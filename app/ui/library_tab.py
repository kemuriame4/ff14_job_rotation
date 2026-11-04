from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..gamedata import game_data, game_jobs
from .widgets import skill_icon


class _SortItem(QTableWidgetItem):
    """按数值/文本排序的表格单元格（显示文本与排序键分离）。"""

    def __init__(self, text: str, sort_key: object) -> None:
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortItem):
            try:
                return self._sort_key < other._sort_key
            except TypeError:
                pass
        return super().__lt__(other)


class LibraryTab(QWidget):
    """全部职业的技能与图标一览（来自游戏数据，只读）。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabPage")
        self.ctx = ctx
        self._rows: list[dict] = []
        self._build_ui()
        self.reload()

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
        title = QLabel("技能库")
        title.setObjectName("PageTitle")
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        row.addWidget(title)
        row.addSpacing(8)
        row.addWidget(self.count_label)
        row.addStretch(1)
        top_layout.addLayout(row)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索技能、职业或 ID，例如 火 / BLM / 连击")
        self.search.textChanged.connect(self._apply_filter)
        self.search.setClearButtonEnabled(True)
        search_row.addWidget(self.search, 1)
        top_layout.addLayout(search_row)
        root.addWidget(top)

        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            [
                "技能",
                "职业",
                "类型",
                "威力",
                "距离",
                "半径",
                "目标",
                "复唱",
                "充能",
                "连击前置",
                "变化为",
                "等级",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setIconSize(QSize(24, 24))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 12):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 66)
        self.table.setColumnWidth(3, 56)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 60)
        self.table.setColumnWidth(6, 60)
        self.table.setColumnWidth(7, 68)
        self.table.setColumnWidth(8, 54)
        self.table.setColumnWidth(9, 120)
        self.table.setColumnWidth(10, 150)
        self.table.setColumnWidth(11, 54)
        header.setSortIndicatorShown(True)
        self.table.setSortingEnabled(True)
        root.addWidget(self.table, 1)

    def reload(self) -> None:
        self._rows = []
        jobs = {job.abbrev: job for job in game_jobs()}
        data = game_data()
        if not data:
            self.count_label.setText(
                "未找到 data/game_data.json，请先运行 tools/fetch_game_data.py"
            )
            self.table.setRowCount(0)
            return
        for meta in data.get("jobs", []):
            abbrev = meta.get("abbrev", "")
            job = jobs.get(abbrev)
            if job is None:
                continue
            for skill in job.skills:
                search_text = f"{abbrev} {meta.get('name', '')} {skill.name} {' '.join(skill.transform)}"
                self._rows.append(
                    {
                        "skill": skill,
                        "job": f"{meta.get('name', '')} {abbrev}".strip(),
                        "search": search_text.lower(),
                    }
                )
        self.count_label.setText(
            f"{len(data.get('jobs', []))} 个职业 · {len(self._rows)} 个技能 · 数据版本 {data.get('fetched_at', '')}"
        )
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str) -> None:
        keyword = (text or "").strip().lower()
        shown = (
            [row for row in self._rows if keyword in row["search"]]
            if keyword
            else self._rows
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for index, row in enumerate(shown):
            skill = row["skill"]
            self.table.insertRow(index)
            self.table.setRowHeight(index, 34)

            name_item = _SortItem(skill.name, skill.name)
            icon = skill_icon(skill, 24)
            if not icon.isNull():
                name_item.setIcon(icon)
            if skill.combo:
                name_item.setToolTip(f"连击前置：{skill.combo}")
            if skill.transform:
                name_item.setToolTip(
                    (name_item.toolTip() + "\n" if name_item.toolTip() else "")
                    + "变化为："
                    + " / ".join(skill.transform)
                )
            range_text = (
                f"距离 {skill.attack_range:g}y · 半径 {skill.effect_range:g}y"
                + (f" · 威力 {skill.potency:g}" if skill.potency else "")
            )
            name_item.setToolTip(
                (name_item.toolTip() + "\n" if name_item.toolTip() else "") + range_text
            )
            self.table.setItem(index, 0, name_item)

            target = "群伤" if skill.is_aoe else "单体"
            values = [
                row["job"],
                "GCD" if skill.gcd else "能力",
                f"{skill.potency:g}" if skill.potency else "—",
                f"{skill.attack_range:g} y" if skill.attack_range else "—",
                f"{skill.effect_range:g} y" if skill.effect_range else "—",
                target,
                f"{skill.recast:g}s" if skill.recast else "—",
                str(skill.charges) if skill.charges > 1 else "—",
                skill.combo or "—",
                "、".join(skill.transform) or "—",
                str(skill.level) if skill.level else "—",
            ]
            sort_keys = [
                row["job"],
                1 if skill.gcd else 0,
                skill.potency if skill.potency else -1.0,
                skill.attack_range if skill.attack_range else -1.0,
                skill.effect_range if skill.effect_range else -1.0,
                1 if skill.is_aoe else 0,
                skill.recast if skill.recast else -1.0,
                skill.charges if skill.charges > 1 else 0,
                skill.combo or "",
                "、".join(skill.transform) or "~",
                skill.level if skill.level else -1,
            ]
            for offset, (value, sort_key) in enumerate(zip(values, sort_keys)):
                item = _SortItem(value, sort_key)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if offset != 0
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                if offset == 1:
                    item.setForeground(QColor(skill.color))
                if offset == 2:
                    item.setToolTip(
                        f"单体威力 {skill.potency:g}"
                        + (
                            f"，连击威力 {skill.combo_potency:g}"
                            if skill.combo_potency
                            else ""
                        )
                        if skill.potency
                        else "说明中未记录威力（增益/位移等技能）"
                    )
                if offset == 3 and skill.attack_range:
                    item.setToolTip(f"攻击/施法距离 {skill.attack_range:g} 米")
                if offset == 4:
                    item.setToolTip(
                        f"作用半径 {skill.effect_range:g} 米"
                        if skill.effect_range
                        else "无作用半径（单体）"
                    )
                if offset == 5:
                    item.setForeground(QColor("#e0794a" if skill.is_aoe else "#8d97a8"))
                    item.setToolTip(
                        "按作用半径判定为群伤（范围治疗/增益也归入此类）"
                        if skill.is_aoe
                        else "作用半径为 0，单体技能"
                    )
                if offset == 9 and skill.transform:
                    item.setForeground(QColor("#c9a86a"))
                    item.setToolTip("变化为：" + " / ".join(skill.transform))
                self.table.setItem(index, offset + 1, item)
        self.table.setSortingEnabled(True)
