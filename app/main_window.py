from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .analyzer import AnalysisResult
from .context import AppContext
from .keys import canonical_from_qt
from .ui.keymap_tab import KeymapTab
from .ui.library_tab import LibraryTab
from .ui.report_tab import ReportTab
from .ui.rotation_tab import RotationTab
from .ui.training_tab import TrainingTab


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("FF14 循环训练器")
        self.resize(1180, 900)

        self._build_ui()
        # 窗口最小宽度以训练页为基准，保证设置卡与 12 列热键栏可完整显示。
        self.setMinimumSize(max(1040, self.training_tab.minimumWidth() + 44), 720)
        self.ctx.job_changed.connect(self._on_job_changed)
        QApplication.instance().installEventFilter(self)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("HeaderBar")
        header.setFixedHeight(74)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)
        header_layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("FF14 循环训练器")
        title.setObjectName("AppTitle")
        subtitle = QLabel("职业技能循环 · 键位映射 · 时间轴对比分析")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header_layout.addLayout(titles)
        header_layout.addStretch(1)

        job_label = QLabel("职业")
        job_label.setObjectName("Muted")
        self.job_combo = QComboBox()
        self.job_combo.setMinimumWidth(230)
        self.job_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for job in self.ctx.jobs:
            self.job_combo.addItem(job.name, job.id)
            if job.role:
                self.job_combo.setItemData(
                    self.job_combo.count() - 1, job.role, Qt.ItemDataRole.ToolTipRole
                )
        self._sync_job_combo()
        self.job_combo.currentIndexChanged.connect(self._on_combo_changed)
        header_layout.addWidget(job_label)
        header_layout.addWidget(self.job_combo)
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 10, 18, 0)
        body_layout.setSpacing(0)
        self.tabs = QTabWidget()
        self.training_tab = TrainingTab(self.ctx)
        self.keymap_tab = KeymapTab(self.ctx, self)
        self.rotation_tab = RotationTab(self.ctx, self)
        self.report_tab = ReportTab(self.ctx)
        self.library_tab = LibraryTab(self.ctx)
        self.tabs.addTab(self.training_tab, "训练")
        self.tabs.addTab(self.keymap_tab, "键位映射")
        self.tabs.addTab(self.rotation_tab, "标准循环")
        self.tabs.addTab(self.report_tab, "分析报告")
        self.tabs.addTab(self.library_tab, "技能库")
        body_layout.addWidget(self.tabs)
        layout.addWidget(body, 1)

        self.training_tab.session_finished.connect(self._on_session_finished)
        self.training_tab.busy_changed.connect(self._on_busy)

    def _sync_job_combo(self) -> None:
        index = self.job_combo.findData(self.ctx.current_job_id())
        if index >= 0:
            self.job_combo.blockSignals(True)
            self.job_combo.setCurrentIndex(index)
            self.job_combo.blockSignals(False)

    def _on_combo_changed(self, index: int) -> None:
        job_id = self.job_combo.itemData(index)
        if job_id:
            self.ctx.set_current_job(str(job_id))

    def _on_job_changed(self) -> None:
        self._sync_job_combo()
        self.training_tab.refresh_job()
        self.keymap_tab.refresh()
        self.rotation_tab.refresh()

    def _on_session_finished(self, result: AnalysisResult) -> None:
        self.report_tab.show_result(result)
        self.tabs.setCurrentWidget(self.report_tab)

    def _on_busy(self, busy: bool) -> None:
        self.job_combo.setEnabled(not busy)
        for index in range(1, self.tabs.count()):
            widget = self.tabs.widget(index)
            widget.setEnabled(not busy)
            try:
                self.tabs.setTabEnabled(index, not busy)
            except AttributeError:
                pass

    def refresh_training_only(self) -> None:
        self.training_tab.refresh_preview()

    def refresh_from_keymap(self) -> None:
        self.training_tab.refresh_job()
        self.rotation_tab.refresh()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and self.training_tab.is_recording():
            if (
                not event.isAutoRepeat()
                and self.isActiveWindow()
                and QApplication.activeModalWidget() is None
            ):
                canonical = canonical_from_qt(event)
                if canonical:
                    self.training_tab.handle_qt_key(canonical)
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.training_tab.shutdown()
        super().closeEvent(event)
