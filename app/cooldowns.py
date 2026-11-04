from __future__ import annotations

from .models import Job, Skill


class CooldownTracker:
    """按 FF14 规则追踪单个技能的复唱时间、充能与公共冷却（GCD）。

    时间基准与训练会话一致，使用秒为单位的相对时间。
    """

    def __init__(self, job: Job) -> None:
        self.job = job
        self.gcd_ready = 0.0
        self.gcd_span = max(0.1, float(job.gcd))
        self._ready: dict[str, list[float]] = {}
        self._skills: dict[str, Skill] = {s.name: s for s in job.skills}
        self.reset()

    def reset(self) -> None:
        self.gcd_ready = 0.0
        self.gcd_span = max(0.1, float(self.job.gcd))
        self._ready = {}

    def gcd_time_of(self, skill: Skill) -> float:
        """该 GCD 技能占用的公共冷却时长（舞步等短 GCD 技能按自身配置）。"""
        if skill.gcd_time > 0:
            return skill.gcd_time
        # 舞步等复唱时间短于职业 GCD 的技能，按自身复唱推进。
        if 0 < skill.recast < self.job.gcd:
            return skill.recast
        return max(0.1, float(self.job.gcd))

    def recast_of(self, skill: Skill) -> float:
        if skill.gcd:
            return max(self.gcd_time_of(skill), skill.recast)
        return max(0.0, skill.recast)

    def _slots(self, skill: Skill) -> list[float]:
        slots = self._ready.get(skill.name)
        if slots is None:
            count = max(1, skill.charges)
            slots = [0.0] * count
            self._ready[skill.name] = slots
        return slots

    def on_cast(self, skill_name: str, t: float) -> None:
        skill = self._skills.get(skill_name)
        if skill is None:
            return
        slots = self._slots(skill)
        slots.sort()
        slots[0] = t + self.recast_of(skill)
        if skill.gcd:
            self.gcd_span = self.gcd_time_of(skill)
            self.gcd_ready = t + self.gcd_span

    def remaining(self, skill_name: str, t: float) -> float:
        """技能距下一次可用还剩多少秒（充能技能返回最早可用的一层）。"""
        skill = self._skills.get(skill_name)
        if skill is None:
            return 0.0
        slots = self._slots(skill)
        return max(0.0, min(slots) - t)

    def ready_charges(self, skill_name: str, t: float) -> int:
        """当前已恢复的充能层数（无充能技能为 0 或 1 ）。"""
        skill = self._skills.get(skill_name)
        if skill is None:
            return 0
        slots = self._slots(skill)
        return sum(1 for ready in slots if ready <= t + 1e-6)

    def max_charges(self, skill_name: str) -> int:
        skill = self._skills.get(skill_name)
        if skill is None:
            return 0
        return max(1, skill.charges)

    def recharge_remaining(self, skill_name: str, t: float) -> float:
        """正在恢复的一层还需多少秒；全部充能就绪时返回 0。"""
        skill = self._skills.get(skill_name)
        if skill is None:
            return 0.0
        for ready in sorted(self._slots(skill)):
            if ready > t:
                return max(0.0, ready - t)
        return 0.0

    def gcd_remaining(self, t: float) -> float:
        return max(0.0, self.gcd_ready - t)

    def blocked_by_gcd(self, skill: Skill, t: float, slack: float = 0.15) -> bool:
        if not skill.gcd:
            return False
        return self.gcd_remaining(t) > slack

    def on_cooldown(self, skill: Skill, t: float, slack: float = 0.15) -> bool:
        return self.remaining(skill.name, t) > slack
