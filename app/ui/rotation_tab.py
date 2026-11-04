from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Step
from .widgets import NoWheelComboBox, dance_sequence_icon


class RotationTab(QWidget):
    def __init__(
        self, ctx: AppContext, main_window, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TabPage")
        self.ctx = ctx
        self.main = main_window
        self._loading = False
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)

        top = QFrame()
        top.setObjectName("Card")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(18, 14, 18, 14)
        top_layout.setSpacing(10)

        row = QHBoxLayout()
        title = QLabel("标准循环")
        title.setObjectName("PageTitle")
        self.job_label = QLabel("")
        self.job_label.setObjectName("Muted")
        row.addWidget(title)
        row.addSpacing(8)
        row.addWidget(self.job_label)
        row.addStretch(1)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("NextHint")
        row.addWidget(self.summary_label)
        top_layout.addLayout(row)

        settings = QHBoxLayout()
        settings.setSpacing(12)

        self.loop_check = QCheckBox("循环重复")
        self.loop_check.toggled.connect(self._on_loop_toggled)
        settings.addWidget(self.loop_check)

        settings.addWidget(QLabel("循环长度"))
        self.cycle_spin = QDoubleSpinBox()
        self.cycle_spin.setRange(0.1, 1800.0)
        self.cycle_spin.setDecimals(1)
        self.cycle_spin.setSingleStep(0.5)
        self.cycle_spin.setSuffix(" 秒")
        self.cycle_spin.setMinimumWidth(112)
        self.cycle_spin.valueChanged.connect(self._on_cycle_changed)
        settings.addWidget(self.cycle_spin)

        settings.addWidget(QLabel("GCD"))
        self.gcd_spin = QDoubleSpinBox()
        self.gcd_spin.setRange(0.5, 10.0)
        self.gcd_spin.setDecimals(2)
        self.gcd_spin.setSingleStep(0.01)
        self.gcd_spin.setSuffix(" 秒")
        self.gcd_spin.setMinimumWidth(112)
        self.gcd_spin.valueChanged.connect(self._on_gcd_changed)
        settings.addWidget(self.gcd_spin)

        settings.addStretch(1)

        add_btn = QPushButton("添加步骤")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(self._add_step)
        settings.addWidget(add_btn)
        top_layout.addLayout(settings)

        hint = QLabel(
            "期望时间自动推算：GCD 技能按当前 GCD 间隔推进，能力技不占 GCD、按 0.65 秒织入间隔排列，"
            "同一技能重复出现时受复唱时间限制。按循环长度重复标准循环；关闭「循环重复」只比较一轮。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        top_layout.addWidget(hint)
        root.addWidget(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "技能", "类型", "期望时间", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 90)
        root.addWidget(self.table, 1)

    def refresh(self) -> None:
        self._loading = True
        job = self.ctx.current_job()
        job.layout_rotation()
        self.job_label.setText(f"当前职业：{job.name}")
        self.loop_check.setChecked(job.loop)
        self.cycle_spin.setValue(max(job.cycle_length, 0.1))
        self.gcd_spin.setValue(job.gcd)

        self.table.setRowCount(0)
        for row, step in enumerate(job.rotation):
            self.table.insertRow(row)
            self.table.setRowHeight(row, 44)

            number = QTableWidgetItem(str(row + 1))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setForeground(QColor("#8d97a8"))
            self.table.setItem(row, 0, number)

            combo = NoWheelComboBox()
            combo.setIconSize(QSize(22, 22))
            names: list[str] = []
            for skill in job.skills:
                combo.addItem(dance_sequence_icon(skill, 22), skill.name)
                names.append(skill.name)
            if step.skill not in names:
                combo.addItem(step.skill)
                names.append(step.skill)
            combo.setCurrentIndex(max(0, combo.findText(step.skill)))
            combo.currentTextChanged.connect(
                lambda text, target=step: self._on_step_skill_changed(target, text)
            )
            self.table.setCellWidget(row, 1, combo)

            skill = job.skill(step.skill)
            is_gcd = skill is None or skill.gcd
            type_item = QTableWidgetItem("GCD" if is_gcd else "能力")
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setForeground(QColor("#c9a86a" if is_gcd else "#57c38a"))
            if skill is not None:
                if is_gcd:
                    type_item.setToolTip(
                        f"GCD 技能 · 复唱 {skill.recast:g}s"
                        if skill.recast
                        else "GCD 技能"
                    )
                else:
                    type_item.setToolTip(
                        f"能力技 · 复唱 {skill.recast:g}s" if skill.recast else "能力技"
                    )
            self.table.setItem(row, 2, type_item)

            time_item = QTableWidgetItem(f"{step.offset:.2f} s")
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setToolTip(
                f"自动推算：{'GCD 技能占一个 GCD' if is_gcd else '能力技不占 GCD'}"
            )
            self.table.setItem(row, 3, time_item)

            delete_btn = QPushButton("删除")
            delete_btn.setObjectName("Danger")
            delete_btn.clicked.connect(
                lambda _=False, target=step: self._delete_step(target)
            )
            self.table.setCellWidget(row, 4, delete_btn)

        self._update_summary()
        self._loading = False

    def _update_summary(self) -> None:
        job = self.ctx.current_job()
        if job.rotation:
            duration = job.layout_rotation()
            self.summary_label.setText(
                f"共 {len(job.rotation)} 步 · 一轮 {duration:.2f}s · 循环 {job.cycle_length:.2f}s"
            )
        else:
            self.summary_label.setText("尚未添加步骤")

    def _sync_layout(self) -> float:
        """按技能类型与复唱时间重算期望时间（循环长度仍由用户设置）。"""
        return self.ctx.current_job().layout_rotation()

    def _notify(self, rebuild: bool = False) -> None:
        if self._loading:
            return
        self.ctx.save_jobs()
        if self.main is not None:
            self.main.refresh_training_only()
        self._update_summary()
        if rebuild:
            self.refresh()

    def _on_loop_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        self.ctx.current_job().loop = bool(checked)
        self._notify()

    def _on_cycle_changed(self, value: float) -> None:
        if self._loading:
            return
        self.ctx.current_job().cycle_length = float(value)
        self._notify()

    def _on_gcd_changed(self, value: float) -> None:
        if self._loading:
            return
        self.ctx.current_job().gcd = float(value)
        self._sync_layout()
        self._notify(rebuild=True)

    def _on_step_skill_changed(self, step: Step, text: str) -> None:
        if self._loading or not text:
            return
        step.skill = text
        self._sync_layout()
        self._notify()
        QTimer.singleShot(0, self.refresh)

    def _add_step(self) -> None:
        job = self.ctx.current_job()
        if not job.skills:
            QMessageBox.information(self, "提示", "请先在「键位映射」页添加技能。")
            return
        skill = job.rotation[-1].skill if job.rotation else job.skills[0].name
        job.rotation.append(Step(skill=skill, offset=0.0))
        self._sync_layout()
        self._notify(rebuild=True)

    def _delete_step(self, step: Step) -> None:
        job = self.ctx.current_job()
        if step in job.rotation:
            job.rotation.remove(step)
            self._sync_layout()
            self._notify(rebuild=True)
