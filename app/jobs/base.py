"""职业专属逻辑的基类。

各职业的动态量谱、技能替换规则与训练页状态机放在 ``app/jobs/<职业>.py``，
训练页只通过本基类的方法与职业逻辑交互。
"""

from __future__ import annotations

from ..gauge import GaugeSpec


class JobLogic:
    """职业专属逻辑：量谱规格 + 训练页的动态显示 / 状态校验。"""

    abbrev = ""
    gauge: GaugeSpec | None = None
    # 栏位显示是否完全由职业状态驱动（如 DNC 舞步），而非技能变换表。
    state_driven_display = False

    def reset(self) -> None:
        """重置职业状态（开始训练 / 切换职业时调用）。"""

    def tick(self, t: float) -> str:
        """随时间推进状态，返回需要展示的提示文本（无则空串）。"""
        return ""

    def on_cast(self, name: str, t: float, hotbar_bases: set[str]) -> str:
        """通知职业逻辑一次成功施放，返回需要展示的提示文本。"""
        return ""

    def block_reason(self, name: str, t: float) -> str:
        """返回该技能在当前职业状态下不可施放的原因（可施放则为空串）。"""
        return ""

    def allows(self, name: str, t: float) -> bool:
        """栏位是否允许点击（用于跳舞模式等整体限制）。"""
        return True

    def suppress_proc(self, name: str) -> bool:
        """该技能是否不使用金光强化高亮（如舞步与结束技能）。"""
        return False

    def queued_skill(self, t: float) -> str:
        """当前应高亮的“下一步”技能名（无则为空串）。"""
        return ""

    def progress_hint(self, t: float) -> str:
        """训练中的进度提示文本（无则为空串）。"""
        return ""

    def display(self, base: str, t: float, gauge) -> str:
        """按职业状态决定栏位应显示的动作名。"""
        return base

    def status_text(self, t: float, icon_uri) -> str:
        """量谱上方的富文本状态（如舞步序列），无则为空串。"""
        return ""
