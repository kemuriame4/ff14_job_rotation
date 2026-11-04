from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..analyzer import AnalysisResult
from ..context import AppContext
from .widgets import MetricCard, TimelineWidget


GRADE_COLORS = {
    "S": "#57c38a",
    "A": "#c9a86a",
    "B": "#5c9fe0",
    "C": "#e0b45a",
    "D": "#e06a72",
}
STATUS_TEXT_COLORS = {
    "准确": "#4fbf8b",
    "偏早": "#e0b45a",
    "偏晚": "#e0b45a",
    "顺序错误": "#e08a5c",
    "多余": "#e06a72",
    "缺失": "#e06a72",
}


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds:5.1f}s"


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "—"
    return f"{delta * 1000:+.0f} ms"


class ReportTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabPage")
        self.ctx = ctx
        self.result: AnalysisResult | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("分析报告")
        title.setObjectName("PageTitle")
        self.subtitle = QLabel("尚未进行训练")
        self.subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addSpacing(8)
        header.addWidget(self.subtitle)
        header.addStretch(1)
        self.export_btn = QPushButton("导出 JSON")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        header.addWidget(self.export_btn)
        root.addLayout(header)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.addStretch(1)
        icon = QLabel("◎")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size:42px;color:#39465a;")
        placeholder_layout.addWidget(icon)
        message = QLabel("完成一次训练后，这里会显示循环对比分析")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setObjectName("PageTitle")
        placeholder_layout.addWidget(message)
        hint = QLabel(
            "训练页设置统计时间 → 开始训练 → 自动生成时间轴、评分与逐项差异。"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("Muted")
        placeholder_layout.addWidget(hint)
        placeholder_layout.addStretch(1)
        self.stack.addWidget(placeholder)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.score_card = MetricCard("综合评分", "—")
        self.grade_card = MetricCard("等级", "—")
        self.sequence_card = MetricCard("顺序准确率", "—")
        self.timing_card = MetricCard("时机准确率", "—")
        self.deviation_card = MetricCard("平均绝对偏差", "—")
        self.miss_card = MetricCard("漏按 / 多余", "—")
        self.rule_card = MetricCard("冷却 / 连击", "—")
        self.potency_card = MetricCard("威力总值", "—")
        for card in (
            self.score_card,
            self.grade_card,
            self.sequence_card,
            self.timing_card,
            self.deviation_card,
            self.miss_card,
            self.rule_card,
            self.potency_card,
        ):
            metrics.addWidget(card)
        content_layout.addLayout(metrics)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Muted")
        self.summary_label.setWordWrap(True)
        content_layout.addWidget(self.summary_label)

        timeline_card = QFrame()
        timeline_card.setObjectName("Card")
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(18, 14, 18, 16)
        timeline_layout.setSpacing(8)
        timeline_title = QLabel("循环时间轴对比")
        timeline_title.setObjectName("CardTitle")
        timeline_layout.addWidget(timeline_title)
        self.timeline = TimelineWidget()
        self.timeline.setFixedHeight(210)
        timeline_layout.addWidget(self.timeline, 1)
        content_layout.addWidget(timeline_card)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        advice_card = QFrame()
        advice_card.setObjectName("Card")
        advice_card.setFixedWidth(330)
        advice_layout = QVBoxLayout(advice_card)
        advice_layout.setContentsMargins(18, 14, 18, 16)
        advice_layout.setSpacing(8)
        advice_title = QLabel("改进建议")
        advice_title.setObjectName("CardTitle")
        advice_layout.addWidget(advice_title)
        self.advice_label = QLabel("")
        self.advice_label.setWordWrap(True)
        self.advice_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.advice_label.setStyleSheet(
            "color:#b8c2d0;font-size:13px;line-height:170%;"
        )
        advice_layout.addWidget(self.advice_label, 1)
        bottom.addWidget(advice_card)

        table_card = QFrame()
        table_card.setObjectName("Card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 14, 18, 16)
        table_layout.setSpacing(8)
        table_title = QLabel("逐项差异")
        table_title.setObjectName("CardTitle")
        table_layout.addWidget(table_title)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "标准时间", "标准技能", "实际时间", "实际技能", "偏差", "判定"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 82)
        self.table.setColumnWidth(3, 82)
        self.table.setColumnWidth(5, 88)
        self.table.setColumnWidth(6, 84)
        table_layout.addWidget(self.table, 1)
        bottom.addWidget(table_card, 1)
        content_layout.addLayout(bottom, 1)

        self.stack.addWidget(content)

    def show_result(self, result: AnalysisResult) -> None:
        self.result = result
        self.subtitle.setText(
            f"{result.job_name}  ·  时长 {result.duration:.1f}s  ·  容差 ±{result.tolerance * 1000:.0f}ms"
        )
        color = GRADE_COLORS.get(result.grade, "#e6e8ec")
        self.score_card.set_value(str(result.score), color)
        self.grade_card.set_value(result.grade, color)
        self.sequence_card.set_value(f"{result.sequence_accuracy * 100:.0f}%")
        self.timing_card.set_value(f"{result.timing_accuracy * 100:.0f}%")
        self.deviation_card.set_value(f"{result.avg_abs_delta * 1000:.0f} ms")
        self.miss_card.set_value(f"{result.missing_count} / {result.extra_count}")
        rule_total = result.cooldown_clashes + result.gcd_clashes
        self.rule_card.set_value(
            f"{rule_total} / {result.combo_breaks}",
            "#e06a72" if rule_total or result.combo_breaks else None,
        )
        potency_colors = {
            "优秀": "#57c38a",
            "良好": "#c9a86a",
            "一般": "#e0b45a",
            "偏低": "#e06a72",
        }
        self.potency_card.set_value(
            f"{result.actual_potency:.0f}",
            potency_colors.get(result.potency_grade),
        )
        direction = "偏晚" if result.mean_delta > 0 else "偏早"
        potency_basis = (
            f"标准 {result.expected_potency:.0f}"
            if result.expected_potency > 0
            else f"理论上限 {result.actual_potency / max(result.potency_ratio, 1e-9):.0f}"
            if result.potency_ratio > 0
            else "理论上限 —"
        )
        self.summary_label.setText(
            f"匹配 {result.matched_count} / {result.expected_count} 步  ·  总按键 {result.press_count}  ·  "
            f"顺序错误 {result.order_issue_count}  ·  GCD 冲突 {result.gcd_clashes}  ·  "
            f"冷却冲突 {result.cooldown_clashes}  ·  连击中断 {result.combo_breaks}  ·  "
            f"状态不足 {len(result.state_issues)}  ·  "
            f"威力 {result.actual_potency:.0f} / {potency_basis}"
            f"（{result.potency_ratio * 100:.0f}% · {result.potency_grade}）  ·  "
            f"PPS {result.actual_pps:.1f}  ·  "
            f"平均{direction} {abs(result.mean_delta) * 1000:.0f} ms  ·  "
            f"节奏标准差 {result.std_delta * 1000:.0f} ms"
        )

        self.timeline.set_data(
            expected=result.expected,
            actual=result.actual,
            expected_statuses=result.expected_statuses,
            actual_statuses=result.actual_statuses,
            duration=max(result.duration, 1.0),
            gcd=result.gcd,
        )

        items = "".join(
            f"<li style='margin-bottom:6px'>{html.escape(text)}</li>"
            for text in result.suggestions
        )
        self.advice_label.setText(f"<ul style='margin-left:-18px;'>{items}</ul>")

        self.table.setRowCount(0)
        for row_index, row in enumerate(result.rows):
            self.table.insertRow(row_index)
            self.table.setRowHeight(row_index, 34)
            number = "—" if row.expected_index is None else str(row.expected_index)
            values = [
                number,
                _fmt_time(row.expected_t),
                row.expected_skill or "—",
                _fmt_time(row.actual_t),
                row.actual_skill or "—",
                _fmt_delta(row.delta),
                row.status,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if col in (0, 1, 3, 5, 6)
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                if col == 6:
                    item.setForeground(
                        QColor(STATUS_TEXT_COLORS.get(row.status, "#e6e8ec"))
                    )
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif col == 5 and row.delta is not None:
                    item.setForeground(
                        QColor(STATUS_TEXT_COLORS.get(row.status, "#e6e8ec"))
                    )
                self.table.setItem(row_index, col, item)

        self.export_btn.setEnabled(True)
        self.stack.setCurrentIndex(1)

    def _export(self) -> None:
        if self.result is None:
            return
        job = self.ctx.current_job()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"ff14_rotation_report_{job.id}_{stamp}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", str(Path.home() / default), "JSON 文件 (*.json)"
        )
        if not path:
            return
        rows = [
            {
                "expected_index": row.expected_index,
                "expected_time": (
                    None if row.expected_t is None else round(row.expected_t, 3)
                ),
                "expected_skill": row.expected_skill,
                "actual_time": None if row.actual_t is None else round(row.actual_t, 3),
                "actual_skill": row.actual_skill,
                "delta_ms": None if row.delta is None else round(row.delta * 1000, 1),
                "status": row.status,
            }
            for row in self.result.rows
        ]
        payload = {
            "job": self.result.job_name,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "duration_sec": round(self.result.duration, 2),
            "tolerance_ms": round(self.result.tolerance * 1000, 1),
            "score": self.result.score,
            "grade": self.result.grade,
            "sequence_accuracy": round(self.result.sequence_accuracy, 4),
            "timing_accuracy": round(self.result.timing_accuracy, 4),
            "matched": self.result.matched_count,
            "expected": self.result.expected_count,
            "presses": self.result.press_count,
            "missing": self.result.missing_count,
            "extra": self.result.extra_count,
            "order_issues": self.result.order_issue_count,
            "gcd_clashes": self.result.gcd_clashes,
            "cooldown_clashes": self.result.cooldown_clashes,
            "combo_breaks": self.result.combo_breaks,
            "potency": {
                "actual": round(self.result.actual_potency, 1),
                "expected": round(self.result.expected_potency, 1),
                "actual_pps": round(self.result.actual_pps, 2),
                "expected_pps": round(self.result.expected_pps, 2),
                "ratio": round(self.result.potency_ratio, 3),
                "grade": self.result.potency_grade,
            },
            "state_issues": [
                {"time": round(t, 3), "skill": name, "reason": reason}
                for t, name, reason in self.result.state_issues
            ],
            "avg_abs_delta_ms": round(self.result.avg_abs_delta * 1000, 1),
            "mean_delta_ms": round(self.result.mean_delta * 1000, 1),
            "std_delta_ms": round(self.result.std_delta * 1000, 1),
            "suggestions": self.result.suggestions,
            "differences": rows,
        }
        try:
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"报告已保存到：\n{path}")
