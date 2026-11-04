"""舞者（ DNC ）专属逻辑：量谱规则、舞步状态机与训练页显示。"""

from __future__ import annotations

import random

from ..gauge import Buff, BuffRule, GaugeSpec, GaugeTracker, Rule, _r, _req
from .base import JobLogic

DANCE_DURATION = 15.0

DANCE_STEPS = ("蔷薇曲脚步", "小鸟交叠跳", "绿叶小踢腿", "金冠趾尖转")
DANCE_STEP_BASES = {
    "瀑泻": "蔷薇曲脚步",
    "风车": "蔷薇曲脚步",
    "喷泉": "小鸟交叠跳",
    "落刃雨": "小鸟交叠跳",
    "逆瀑泻": "绿叶小踢腿",
    "升风车": "绿叶小踢腿",
    "坠喷泉": "金冠趾尖转",
    "落血雨": "金冠趾尖转",
}
STANDARD_ENDINGS = ("标准舞步结束", "单色标准舞步结束", "双色标准舞步结束")
TECHNICAL_ENDINGS = (
    "技巧舞步结束",
    "单色技巧舞步结束",
    "双色技巧舞步结束",
    "三色技巧舞步结束",
    "四色技巧舞步结束",
)
DANCE_ENDINGS = set(STANDARD_ENDINGS + TECHNICAL_ENDINGS)
DANCE_TRIGGERS = {"标准舞步": "standard", "技巧舞步": "technical"}

# 跳舞模式中仍可施放的技能（舞步、结束技能与下列技能之外全部不可用）。
DANCE_ALLOWED_EXTRA = {
    "前冲步",
    "治疗之华尔兹",
    "防守之桑巴",
    "闭式舞姿",
    "速行",
    "内丹",
    "亲疏自行",
}


def ending_for(kind: str, success: int) -> str:
    """按成功舞步数量返回对应颜色的结束技能名。"""
    table = STANDARD_ENDINGS if kind == "standard" else TECHNICAL_ENDINGS
    return table[min(max(0, int(success)), len(table) - 1)]


def canonical_dance_name(name: str) -> str:
    """分析时把任意舞步 / 任意颜色结束技能视为同一技能。"""
    if name in DANCE_STEPS:
        return "舞步技能"
    if name in STANDARD_ENDINGS:
        return STANDARD_ENDINGS[0]
    if name in TECHNICAL_ENDINGS:
        return TECHNICAL_ENDINGS[0]
    return name


DNC = GaugeSpec(
    name="伶俐 / 幻扇",
    resources=(
        _r("esprit", "伶俐", 100),
        _r("feather", "幻扇", 4),
    ),
    buffs={
        "symmetry": Buff("symmetry", "对称投掷", 30.0),
        "flow": Buff("flow", "非对称投掷", 30.0),
        "symmetry_flourish": Buff("symmetry_flourish", "对称投掷·百花争艳", 30.0),
        "flow_flourish": Buff("flow_flourish", "非对称投掷·百花争艳", 30.0),
        "std_finish": Buff("std_finish", "标准舞步结束", 60.0),
        "tec_finish": Buff("tec_finish", "技巧舞步结束", 20.0),
        "fan3_ready": Buff("fan3_ready", "扇舞·急预备", 30.0),
        "fan4_ready": Buff("fan4_ready", "扇舞·终", 30.0),
        "finish_ready": Buff("finish_ready", "结束动作预备", 30.0),
        "last_ready": Buff("last_ready", "落幕舞预备", 30.0),
        "star_ready": Buff("star_ready", "流星舞预备", 20.0),
        "tillana_ready": Buff("tillana_ready", "提拉纳预备", 30.0),
        "dawn_ready": Buff("dawn_ready", "拂晓舞预备", 30.0),
        "improv": Buff("improv", "即兴表演", 15.0),
    },
    rules={
        "瀑泻": Rule(note="50% 获得对称投掷"),
        "风车": Rule(note="50% 获得对称投掷"),
        "喷泉": Rule(note="连击成功 50% 获得非对称投掷"),
        "落刃雨": Rule(note="连击成功 50% 获得非对称投掷"),
        "逆瀑泻": Rule(
            buff_any=(("symmetry", "symmetry_flourish"),),
            chance_gains=(("feather", 1, 0.5),),
            note="需要对称投掷， 使用后消耗； 50% 获得幻扇",
        ),
        "升风车": Rule(
            buff_any=(("symmetry", "symmetry_flourish"),),
            chance_gains=(("feather", 1, 0.5),),
            note="需要对称投掷， 使用后消耗； 50% 获得幻扇",
        ),
        "坠喷泉": Rule(
            buff_any=(("flow", "flow_flourish"),),
            chance_gains=(("feather", 1, 0.5),),
            note="需要非对称投掷， 使用后消耗； 50% 获得幻扇",
        ),
        "落血雨": Rule(
            buff_any=(("flow", "flow_flourish"),),
            chance_gains=(("feather", 1, 0.5),),
            note="需要非对称投掷， 使用后消耗； 50% 获得幻扇",
        ),
        # 伶俐达到 50 时剑舞可发动，并在热键栏中高亮提示。
        "剑舞": Rule(
            requires=_req("esprit", 50), costs=_req("esprit", 50), highlight=True
        ),
        "拂晓舞": Rule(
            requires=_req("esprit", 50),
            costs=_req("esprit", 50),
            buff_requires=("dawn_ready",),
            note="需要伶俐 50 与拂晓舞预备，使用后消耗",
        ),
        "提拉纳": Rule(
            buff_requires=("tillana_ready",),
            gains={"esprit": 50},
            note="需要提拉纳预备，使用后消耗；获得 50 伶俐",
        ),
        "扇舞·序": Rule(
            requires=_req("feather", 1),
            costs=_req("feather", 1),
            highlight=True,
            note="消耗 1 幻扇",
        ),
        "扇舞·破": Rule(
            requires=_req("feather", 1),
            costs=_req("feather", 1),
            highlight=True,
            note="消耗 1 幻扇",
        ),
        "扇舞·急": Rule(
            buff_requires=("fan3_ready",), highlight=True, note="需要扇舞·急预备"
        ),
        "扇舞·终": Rule(
            buff_requires=("fan4_ready",), highlight=True, note="需要扇舞·终状态"
        ),
        "流星舞": Rule(buff_requires=("star_ready",), note="需要流星舞预备"),
        "落幕舞": Rule(buff_requires=("last_ready",), note="需要落幕舞预备"),
        "结束动作": Rule(buff_requires=("finish_ready",), note="需要结束动作预备"),
        "即兴表演结束": Rule(buff_requires=("improv",), note="需要即兴表演状态"),
    },
    buff_rules={
        "瀑泻": BuffRule(chance_grants=(("symmetry", 30.0, 0.5),)),
        "风车": BuffRule(chance_grants=(("symmetry", 30.0, 0.5),)),
        "喷泉": BuffRule(chance_grants=(("flow", 30.0, 0.5),), combo="瀑泻"),
        "落刃雨": BuffRule(chance_grants=(("flow", 30.0, 0.5),), combo="风车"),
        "逆瀑泻": BuffRule(consumes=("symmetry", "symmetry_flourish")),
        "升风车": BuffRule(consumes=("symmetry", "symmetry_flourish")),
        "坠喷泉": BuffRule(consumes=("flow", "flow_flourish")),
        "落血雨": BuffRule(consumes=("flow", "flow_flourish")),
        "提拉纳": BuffRule(consumes=("tillana_ready",)),
        "拂晓舞": BuffRule(consumes=("dawn_ready",)),
        "扇舞·序": BuffRule(chance_grants=(("fan3_ready", 30.0, 0.5),)),
        "扇舞·破": BuffRule(chance_grants=(("fan3_ready", 30.0, 0.5),)),
        "扇舞·急": BuffRule(consumes=("fan3_ready",)),
        "扇舞·终": BuffRule(consumes=("fan4_ready",)),
        "进攻之探戈": BuffRule(grants=(("star_ready", 20.0),)),
        "流星舞": BuffRule(consumes=("star_ready",)),
        "百花争艳": BuffRule(
            grants=(
                ("symmetry_flourish", 30.0),
                ("flow_flourish", 30.0),
                ("fan3_ready", 30.0),
                ("fan4_ready", 30.0),
                ("finish_ready", 30.0),
            )
        ),
        "即兴表演": BuffRule(grants=(("improv", 15.0),)),
        "即兴表演结束": BuffRule(consumes=("improv",)),
        "标准舞步结束": BuffRule(grants=(("std_finish", 60.0), ("last_ready", 30.0))),
        "单色标准舞步结束": BuffRule(
            grants=(("std_finish", 60.0), ("last_ready", 30.0))
        ),
        "双色标准舞步结束": BuffRule(
            grants=(("std_finish", 60.0), ("last_ready", 30.0))
        ),
        "结束动作": BuffRule(
            consumes=("finish_ready",),
            grants=(("std_finish", 60.0), ("last_ready", 30.0)),
        ),
        "落幕舞": BuffRule(consumes=("last_ready",)),
        "技巧舞步结束": BuffRule(
            grants=(("tec_finish", 20.0), ("tillana_ready", 30.0), ("dawn_ready", 30.0))
        ),
        "单色技巧舞步结束": BuffRule(
            grants=(("tec_finish", 20.0), ("tillana_ready", 30.0), ("dawn_ready", 30.0))
        ),
        "双色技巧舞步结束": BuffRule(
            grants=(("tec_finish", 20.0), ("tillana_ready", 30.0), ("dawn_ready", 30.0))
        ),
        "三色技巧舞步结束": BuffRule(
            grants=(("tec_finish", 20.0), ("tillana_ready", 30.0), ("dawn_ready", 30.0))
        ),
        "四色技巧舞步结束": BuffRule(
            grants=(("tec_finish", 20.0), ("tillana_ready", 30.0), ("dawn_ready", 30.0))
        ),
    },
    gcd_gain={"esprit": 5},
    hint="伶俐 0-100 ；幻扇 0-4。瀑泻/喷泉 50% 获得投掷状态，"
    "逆瀑泻/坠喷泉 50% 获得幻扇；扇舞·序/破 消耗幻扇并 50% 获得扇舞·急预备。",
)


class DncLogic(JobLogic):
    """舞者训练逻辑：随机舞步序列、跳舞模式限制与状态驱动的栏位显示。"""

    abbrev = "DNC"
    gauge = DNC
    state_driven_display = True

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.kind = ""
        self.sequence: list[str] = []
        self.progress = 0
        self.end = 0.0

    # 舞步状态
    def reset(self) -> None:
        self.kind = ""
        self.sequence = []
        self.progress = 0
        self.end = 0.0

    def active(self, t: float) -> bool:
        return bool(self.kind) and t < self.end

    def next_step(self) -> str:
        if self.progress < len(self.sequence):
            return self.sequence[self.progress]
        return ""

    def _start(self, trigger: str, t: float, hotbar_bases: set[str]) -> None:
        kind = DANCE_TRIGGERS[trigger]
        length = 2 if kind == "standard" else 4
        available = {
            DANCE_STEP_BASES[base] for base in hotbar_bases if base in DANCE_STEP_BASES
        }
        pool = [step for step in DANCE_STEPS if step in available] or list(DANCE_STEPS)
        self.kind = kind
        self.sequence = self.rng.sample(pool, min(length, len(pool)))
        self.progress = 0
        self.end = t + DANCE_DURATION

    # JobLogic 接口
    def tick(self, t: float) -> str:
        if self.kind and t >= self.end:
            self.reset()
            return "舞步超时：未使用结束技能"
        return ""

    def on_cast(self, name: str, t: float, hotbar_bases: set[str]) -> str:
        if name in DANCE_TRIGGERS:
            self._start(name, t, hotbar_bases)
            return (
                "舞步顺序："
                + " → ".join(self.sequence)
                + "（按顺序输入舞步，可随时使用结束技能）"
            )
        if name in DANCE_STEPS and self.kind:
            expected = self.next_step()
            if expected and name == expected:
                self.progress += 1
            elif expected:
                return f"舞步顺序错误：下一步应为 {expected}"
            return ""
        if name in DANCE_ENDINGS:
            self.reset()
        return ""

    def block_reason(self, name: str, t: float) -> str:
        if self.active(t):
            if name in DANCE_ENDINGS:
                family = (
                    STANDARD_ENDINGS if self.kind == "standard" else TECHNICAL_ENDINGS
                )
                return "" if name in family else "当前舞步类型不匹配"
            if name in DANCE_STEPS or name in DANCE_ALLOWED_EXTRA:
                return ""
            return "跳舞模式中只能使用舞步 / 结束技能"
        if name in DANCE_STEPS:
            return "需要先使用标准舞步或技巧舞步"
        if name in DANCE_ENDINGS:
            return "需要先进入跳舞模式"
        return ""

    def allows(self, name: str, t: float) -> bool:
        if not self.active(t):
            return True
        return (
            name in DANCE_STEPS or name in DANCE_ENDINGS or name in DANCE_ALLOWED_EXTRA
        )

    def suppress_proc(self, name: str) -> bool:
        return name in DANCE_STEPS or name in DANCE_ENDINGS

    def queued_skill(self, t: float) -> str:
        if not self.active(t):
            return ""
        return self.next_step()

    def progress_hint(self, t: float) -> str:
        if not self.active(t):
            return ""
        step = self.next_step() or "结束技能"
        return (
            f"舞步 {self.progress}/{len(self.sequence)}:"
            f"下一步 {step} (剩余 {max(0.0, self.end - t):.1f}s)"
        )

    def display(self, base: str, t: float, gauge: GaugeTracker | None) -> str:
        """按当前跳舞 / buff 状态决定栏位应显示的动作。"""
        if self.active(t):
            step = DANCE_STEP_BASES.get(base)
            if step:
                return step
            if base == "标准舞步" and self.kind == "standard":
                return ending_for("standard", self.progress)
            if base == "技巧舞步" and self.kind == "technical":
                return ending_for("technical", self.progress)
        if gauge is None:
            return base
        if base == "标准舞步":
            return "结束动作" if gauge.has_buff("finish_ready", t) else base
        if base == "技巧舞步":
            return "提拉纳" if gauge.has_buff("tillana_ready", t) else base
        if base == "剑舞":
            if gauge.has_buff("dawn_ready", t) and gauge.value("esprit") >= 50:
                return "拂晓舞"
            return base
        if base == "进攻之探戈":
            return "流星舞" if gauge.has_buff("star_ready", t) else base
        if base == "即兴表演":
            return "即兴表演结束" if gauge.has_buff("improv", t) else base
        return base

    def status_text(self, t: float, icon_uri) -> str:
        if not self.active(t):
            return ""
        total = len(self.sequence)
        next_step = self.next_step()
        tail = f"下一步 {next_step}" if next_step else "可使用结束技能"
        icons = []
        for step in self.sequence:
            uri = icon_uri(step)
            icons.append(f'<img src="{uri}" width="22" height="22">' if uri else step)
        return (
            f'<span style="color:#9fb1c9">舞步 {self.progress}/{total}</span>'
            "&nbsp;&nbsp;"
            + "&nbsp;→&nbsp;".join(icons)
            + "&nbsp;&nbsp;"
            + tail
            + f" · 剩余 {max(0.0, self.end - t):.1f}s"
        )
