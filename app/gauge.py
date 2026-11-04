"""职业量谱的简化模拟。

真实游戏中的量谱由客户端脚本维护，无法从技能表直接读取，这里用可维护的规则表做近似：
- ``rules`` 描述每个技能的消耗/获得/要求；
- ``gcd_gain`` / ``periodic`` 描述随 GCD 自然增长的部分（如誓约、忍气、蛇胆）；
- 只对显式配置了条件的技能做“状态不足”校验，未配置的技能不受影响。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# 连击后续技能的隐式可用窗口（秒）。窗口内使用其他技能不会打断连击。
COMBO_WINDOW = 30.0


@dataclass(frozen=True)
class Resource:
    key: str
    label: str
    maximum: float
    initial: float = 0.0


@dataclass(frozen=True)
class Buff:
    key: str
    label: str
    duration: float


@dataclass(frozen=True)
class BuffRule:
    grants: tuple[tuple[str, float], ...] = ()
    consumes: tuple[str, ...] = ()
    # (状态 key, 持续时间, 触发概率)
    chance_grants: tuple[tuple[str, float, float], ...] = ()
    # 仅当上一技能为该连击前置时，才结算概率效果。
    combo: str = ""


@dataclass(frozen=True)
class Rule:
    requires: dict[str, float] = field(default_factory=dict)
    any_requires: tuple[dict[str, float], ...] = ()
    buff_requires: tuple[str, ...] = ()
    buff_any: tuple[tuple[str, ...], ...] = ()
    costs: dict[str, float] = field(default_factory=dict)
    gains: dict[str, float] = field(default_factory=dict)
    # (资源 key, 数量, 触发概率)
    chance_gains: tuple[tuple[str, float, float], ...] = ()
    sets: dict[str, float] = field(default_factory=dict)
    swaps: dict[str, str] = field(default_factory=dict)
    # 资源条件满足时是否在热键栏高亮（如 DNC 剑舞在伶俐 ≥ 50 时）。
    highlight: bool = False
    note: str = ""


@dataclass(frozen=True)
class GaugeSpec:
    name: str
    resources: tuple[Resource, ...] = ()
    rules: dict[str, Rule] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    gcd_gain: dict[str, float] = field(default_factory=dict)
    periodic: dict[str, tuple[int, float]] = field(default_factory=dict)
    buffs: dict[str, Buff] = field(default_factory=dict)
    buff_rules: dict[str, BuffRule] = field(default_factory=dict)
    hint: str = ""


def _r(key: str, label: str, maximum: float, initial: float = 0.0) -> Resource:
    return Resource(key, label, maximum, initial)


def _req(key: str, value: float) -> dict[str, float]:
    return {key: value}


BLM = GaugeSpec(
    name="星极火 / 灵极冰 / 通晓",
    resources=(
        _r("fire", "星极火", 3),
        _r("ice", "灵极冰", 3),
        _r("poly", "通晓", 2),
    ),
    rules={
        "火炎": Rule(sets={"ice": 0}, gains={"fire": 1}),
        "烈炎": Rule(sets={"ice": 0}, gains={"fire": 1}),
        "炽炎": Rule(sets={"ice": 0}),
        "高烈炎": Rule(sets={"ice": 0}, gains={"fire": 1}),
        "爆炎": Rule(sets={"fire": 3, "ice": 0}),
        "核爆": Rule(sets={"fire": 3, "ice": 0}),
        "冰结": Rule(sets={"fire": 0}, gains={"ice": 1}),
        "冰冻": Rule(sets={"fire": 0}, gains={"ice": 1}),
        "冰澈": Rule(sets={"fire": 0, "ice": 3}),
        "冰封": Rule(sets={"fire": 0, "ice": 3}),
        "玄冰": Rule(sets={"fire": 0, "ice": 3}),
        "高冰冻": Rule(sets={"fire": 0, "ice": 3}),
        "星灵移位": Rule(swaps={"fire": "ice", "ice": "fire"}, gains={"poly": 1}),
        "绝望": Rule(requires=_req("fire", 1), note="需要星极火"),
        "悖论": Rule(
            any_requires=({"fire": 3.0}, {"ice": 3.0}),
            note="需要星极火或灵极冰 3 档",
        ),
        "异言": Rule(requires=_req("poly", 1), costs=_req("poly", 1)),
        "秽浊": Rule(requires=_req("poly", 1), costs=_req("poly", 1)),
    },
    aliases={
        "火3": "爆炎",
        "火4": "炽炎",
        "冰3": "冰封",
        "冰4": "冰澈",
        "雷3": "高闪雷",
    },
    periodic={"poly": (6, 1.0)},
    hint="通晓按每 6 个 GCD 回复 1 点（近似）",
)

SAM = GaugeSpec(
    name="闪 / 剑气 / 默想",
    resources=(
        _r("sen", "闪", 3),
        _r("kenki", "剑气", 100),
        _r("meditation", "默想", 3),
    ),
    rules={
        "雪风": Rule(gains={"sen": 1}),
        "月光": Rule(gains={"sen": 1}),
        "花车": Rule(gains={"sen": 1}),
        "阵风": Rule(gains={"sen": 1}),
        "居合术": Rule(requires=_req("sen", 3), costs=_req("sen", 3)),
        "天道五剑": Rule(requires=_req("sen", 3), costs=_req("sen", 3)),
        "天道雪月花": Rule(requires=_req("sen", 3), costs=_req("sen", 3)),
        "必杀剑·红莲": Rule(requires=_req("kenki", 10), costs=_req("kenki", 10)),
        "必杀剑·九天": Rule(requires=_req("kenki", 25), costs=_req("kenki", 25)),
        "奥义斩浪": Rule(requires=_req("kenki", 50), costs=_req("kenki", 50)),
    },
    gcd_gain={"kenki": 5},
)

PLD = GaugeSpec(
    name="誓约",
    resources=(_r("oath", "誓约", 100),),
    rules={
        "盾阵": Rule(requires=_req("oath", 50), costs=_req("oath", 50)),
        "圣盾阵": Rule(requires=_req("oath", 50), costs=_req("oath", 50)),
        "干预": Rule(requires=_req("oath", 50), costs=_req("oath", 50)),
    },
    gcd_gain={"oath": 5},
)

WAR = GaugeSpec(
    name="兽魂",
    resources=(_r("beast", "兽魂", 100),),
    rules={
        "猛攻": Rule(requires=_req("beast", 50), costs=_req("beast", 50)),
        "狂魂": Rule(requires=_req("beast", 50), costs=_req("beast", 50)),
        "尽毁": Rule(requires=_req("beast", 50), costs=_req("beast", 50)),
    },
    gcd_gain={"beast": 5},
)

DRK = GaugeSpec(
    name="暗血",
    resources=(_r("blood", "暗血", 100),),
    rules={
        "血溅": Rule(requires=_req("blood", 50), costs=_req("blood", 50)),
        "掠影的蔑视": Rule(requires=_req("blood", 50), costs=_req("blood", 50)),
    },
    gcd_gain={"blood": 5},
)

GNB = GaugeSpec(
    name="晶壤",
    resources=(_r("cartridge", "晶壤", 3),),
    rules={
        "烈牙": Rule(gains={"cartridge": 1}),
        "命运之环": Rule(requires=_req("cartridge", 1), costs=_req("cartridge", 1)),
        "倍攻": Rule(requires=_req("cartridge", 2), costs=_req("cartridge", 2)),
        "终结之心": Rule(requires=_req("cartridge", 3), costs=_req("cartridge", 3)),
    },
)

WHM = GaugeSpec(
    name="百合",
    resources=(_r("lily", "百合", 3),),
    rules={
        "医济": Rule(gains={"lily": 1}),
        "医养": Rule(gains={"lily": 1}),
        "狂喜之心": Rule(requires=_req("lily", 1), costs=_req("lily", 1)),
        "苦难之心": Rule(requires=_req("lily", 3), costs=_req("lily", 3)),
    },
)

SCH = GaugeSpec(
    name="以太超流 / 异想",
    resources=(
        _r("aether", "以太超流", 3),
        _r("faerie", "异想", 100),
    ),
    rules={
        "醒神": Rule(gains={"aether": 3}),
        "生命活性法": Rule(requires=_req("aether", 1), costs=_req("aether", 1)),
        "深谋远虑之策": Rule(requires=_req("aether", 1), costs=_req("aether", 1)),
        "异想的融光": Rule(requires=_req("faerie", 10), costs={"faerie": 10}),
    },
)

AST = GaugeSpec(
    name="星印",
    resources=(_r("seal", "星印", 3),),
    rules={
        "王冠之领主": Rule(gains={"seal": 1}),
        "王冠之贵妇": Rule(gains={"seal": 1}),
        "占卜": Rule(requires=_req("seal", 3), costs=_req("seal", 3)),
    },
)

SGE = GaugeSpec(
    name="蛇胆 / 蛇刺",
    resources=(
        _r("addergall", "蛇胆", 3, 3),
        _r("addersting", "蛇刺", 3),
    ),
    rules={
        "白牛清汁": Rule(requires=_req("addergall", 1), costs=_req("addergall", 1)),
        "输血": Rule(requires=_req("addergall", 1), costs=_req("addergall", 1)),
        "根素": Rule(requires=_req("addergall", 1), costs=_req("addergall", 1)),
        "整体论": Rule(requires=_req("addergall", 2), costs=_req("addergall", 2)),
    },
    periodic={"addergall": (3, 1.0)},
)

MNK = GaugeSpec(
    name="斗气",
    resources=(_r("chakra", "斗气", 5),),
    rules={
        "阴阳斗气斩": Rule(requires=_req("chakra", 5), costs=_req("chakra", 5)),
        "万象斗气圈": Rule(requires=_req("chakra", 5), costs=_req("chakra", 5)),
        "乾坤斗气弹": Rule(requires=_req("chakra", 5), costs=_req("chakra", 5)),
    },
    periodic={"chakra": (2, 1.0)},
)

DRG = GaugeSpec(
    name="龙血",
    resources=(_r("dragon", "龙血", 100),),
    rules={
        "龙炎升": Rule(requires=_req("dragon", 30), costs=_req("dragon", 30)),
    },
    gcd_gain={"dragon": 5},
)

NIN = GaugeSpec(
    name="忍气",
    resources=(_r("ninki", "忍气", 100),),
    rules={
        "六道轮回": Rule(requires=_req("ninki", 50), costs=_req("ninki", 50)),
        "命水": Rule(requires=_req("ninki", 50), costs=_req("ninki", 50)),
        "是生灭法": Rule(requires=_req("ninki", 50), costs=_req("ninki", 50)),
        "百雷铳": Rule(requires=_req("ninki", 50), costs=_req("ninki", 50)),
    },
    gcd_gain={"ninki": 5},
)

RPR = GaugeSpec(
    name="魂 / 夜",
    resources=(
        _r("soul", "魂", 100),
        _r("shroud", "夜", 100),
    ),
    rules={
        "绞决": Rule(gains={"shroud": 10}),
        "缢杀": Rule(gains={"shroud": 10}),
        "断首": Rule(gains={"shroud": 10}),
        "夜游魂衣": Rule(requires=_req("shroud", 50), costs=_req("shroud", 50)),
        "虚无收割": Rule(requires=_req("shroud", 50), costs=_req("shroud", 50)),
        "交错收割": Rule(requires=_req("shroud", 50), costs=_req("shroud", 50)),
        "团契": Rule(requires=_req("shroud", 50), costs=_req("shroud", 50)),
    },
    gcd_gain={"soul": 5},
)

VPR = GaugeSpec(
    name="响尾蛇鳞",
    resources=(_r("coil", "响尾蛇鳞", 3),),
    rules={
        "飞蛇之尾": Rule(requires=_req("coil", 1), costs=_req("coil", 1)),
        "飞蛇连尾击": Rule(requires=_req("coil", 1), costs=_req("coil", 1)),
        "飞蛇乱尾击": Rule(requires=_req("coil", 1), costs=_req("coil", 1)),
    },
    periodic={"coil": (4, 1.0)},
)

BRD = GaugeSpec(
    name="灵魂之声 / 音律",
    resources=(
        _r("soul_voice", "灵魂之声", 100),
        _r("coda", "音律", 3),
    ),
    rules={
        "绝峰箭": Rule(requires=_req("soul_voice", 80), costs=_req("soul_voice", 80)),
        "共鸣箭": Rule(requires=_req("coda", 3), costs=_req("coda", 3)),
        "行吟": Rule(gains={"coda": 1}),
        "大地神的抒情恋歌": Rule(gains={"coda": 1}),
        "光明神的最终乐章": Rule(gains={"coda": 1}),
    },
    gcd_gain={"soul_voice": 5},
)

MCH = GaugeSpec(
    name="热量 / 电能",
    resources=(
        _r("heat", "热量", 100),
        _r("battery", "电能", 100),
    ),
    rules={
        "枪管加热": Rule(gains={"heat": 50}),
        "全金属爆发": Rule(requires=_req("heat", 50), costs=_req("heat", 50)),
        "后式自走人偶": Rule(requires=_req("battery", 50), costs=_req("battery", 50)),
        "超档后式人偶": Rule(requires=_req("battery", 50), costs=_req("battery", 50)),
    },
    gcd_gain={"heat": 5, "battery": 5},
)

SMN = GaugeSpec(
    name="亚灵",
    resources=(_r("aether", "亚灵", 2),),
    rules={
        "以太充能": Rule(gains={"aether": 2}),
        "坏死爆发": Rule(requires=_req("aether", 1), costs=_req("aether", 1)),
        "能量流失": Rule(requires=_req("aether", 1), costs=_req("aether", 1)),
        "死星核爆": Rule(requires=_req("aether", 1), costs=_req("aether", 1)),
    },
)

RDM = GaugeSpec(
    name="白魔力 / 黑魔力",
    resources=(
        _r("white", "白魔力", 100),
        _r("black", "黑魔力", 100),
    ),
    rules={
        "震荡": Rule(gains={"white": 5}),
        "冲击": Rule(gains={"black": 5}),
        "魔元化": Rule(gains={"white": 50, "black": 50}),
        "决断": Rule(
            requires={"white": 50, "black": 50}, costs={"white": 50, "black": 50}
        ),
    },
)

PCT = GaugeSpec(
    name="绘具",
    resources=(_r("motif", "绘具", 3),),
    rules={
        "兽爪构想": Rule(gains={"motif": 1}),
        "尖牙构想": Rule(gains={"motif": 1}),
        "风景构想": Rule(gains={"motif": 1}),
        "马蒂恩惩罚": Rule(requires=_req("motif", 3), costs=_req("motif", 3)),
    },
)

BLU = GaugeSpec(name="无职业量谱", hint="青魔导士使用 MP 与技能组合，没有职业量谱")

SPECS: dict[str, GaugeSpec] = {
    "PLD": PLD,
    "MNK": MNK,
    "WAR": WAR,
    "DRG": DRG,
    "BRD": BRD,
    "WHM": WHM,
    "BLM": BLM,
    "SMN": SMN,
    "SCH": SCH,
    "NIN": NIN,
    "MCH": MCH,
    "DRK": DRK,
    "AST": AST,
    "SAM": SAM,
    "RDM": RDM,
    "BLU": BLU,
    "GNB": GNB,
    "RPR": RPR,
    "SGE": SGE,
    "VPR": VPR,
    "PCT": PCT,
}


class GaugeTracker:
    """按施放顺序推进量谱与状态（ buff ），并校验技能要求。"""

    def __init__(self, spec: GaugeSpec, rng: random.Random | None = None) -> None:
        self.spec = spec
        self.values: dict[str, float] = {}
        self.buff_expiry: dict[str, float] = {}
        self.now = 0.0
        self.last_skill = ""
        self.rng = rng or random.Random()
        self.reset()

    def reset(self) -> None:
        self.values = {r.key: r.initial for r in self.spec.resources}
        self.buff_expiry = {}
        self._gcd_count = 0
        self.last_skill = ""

    def _label(self, key: str) -> str:
        for resource in self.spec.resources:
            if resource.key == key:
                return resource.label
        return key

    def _buff_label(self, key: str) -> str:
        buff = self.spec.buffs.get(key)
        return buff.label if buff else key

    def _canonical(self, name: str) -> str:
        return self.spec.aliases.get(name, name)

    def _expire(self, now: float) -> None:
        self.now = max(self.now, now)
        for key, expiry in list(self.buff_expiry.items()):
            if expiry <= self.now:
                self.buff_expiry.pop(key, None)

    def _active(self, key: str) -> bool:
        return self.buff_expiry.get(key, 0.0) > self.now

    def value(self, key: str) -> float:
        return self.values.get(key, 0.0)

    def has_buff(self, key: str, now: float | None = None) -> bool:
        self._expire(self.now if now is None else now)
        return self._active(key)

    def available(self, name: str, now: float | None = None) -> bool:
        return not self.check(name, now)

    def empowered(self, name: str, now: float | None = None) -> bool:
        """技能是否因 buff 或资源条件而处于强化 / 可发动状态。"""
        self._expire(self.now if now is None else now)
        rule = self.spec.rules.get(self._canonical(name))
        if rule is None or not (rule.buff_requires or rule.buff_any or rule.highlight):
            return False
        return not self.check(name, now)

    def check(self, name: str, now: float | None = None) -> str:
        self._expire(self.now if now is None else now)
        rule = self.spec.rules.get(self._canonical(name))
        if rule is None:
            return ""
        for key, need in rule.requires.items():
            if self.values.get(key, 0.0) < need:
                return (
                    f"{self._label(key)}不足（{self.values.get(key, 0.0):g}/{need:g}）"
                )
        if rule.any_requires:
            groups = [
                " 或 ".join(f"{self._label(k)}{v:g}" for k, v in group.items())
                for group in rule.any_requires
            ]
            if not any(
                all(self.values.get(k, 0.0) >= v for k, v in group.items())
                for group in rule.any_requires
            ):
                return "需要 " + " / ".join(groups)
        for key in rule.buff_requires:
            if not self._active(key):
                return f"缺少状态：{self._buff_label(key)}"
        for group in rule.buff_any:
            if not any(self._active(key) for key in group):
                return "需要状态：" + " 或 ".join(
                    self._buff_label(key) for key in group
                )
        return ""

    def _apply(self, key: str, delta: float) -> None:
        resource = next((r for r in self.spec.resources if r.key == key), None)
        if resource is None:
            return
        self.values[key] = min(
            max(self.values.get(key, 0.0) + delta, 0.0), resource.maximum
        )

    def _grant(self, key: str, duration: float) -> None:
        buff = self.spec.buffs.get(key)
        if buff is None:
            return
        self.buff_expiry[key] = self.now + max(0.0, duration)

    def cast(
        self, name: str, is_gcd: bool = False, t: float = 0.0
    ) -> tuple[bool, str]:
        """返回 (是否可施放, 原因)；不可施放时不改变量谱与状态。"""
        self._expire(t)
        canonical = self._canonical(name)
        reason = self.check(canonical)
        if reason:
            return False, reason
        rule = self.spec.rules.get(canonical)
        if rule is not None:
            if rule.swaps:
                old = dict(self.values)
                for source, target in rule.swaps.items():
                    if source in self.values and target in self.values:
                        self.values[source] = old.get(target, 0.0)
            for key, amount in rule.sets.items():
                self._apply(key, amount - self.values.get(key, 0.0))
            for key, amount in rule.costs.items():
                self._apply(key, -amount)
            for key, amount in rule.gains.items():
                self._apply(key, amount)
            for key, amount, chance in rule.chance_gains:
                if self.rng.random() < chance:
                    self._apply(key, amount)
        buff_rule = self.spec.buff_rules.get(canonical)
        if buff_rule is not None:
            for key in buff_rule.consumes:
                self.buff_expiry.pop(key, None)
            for key, duration in buff_rule.grants:
                self._grant(key, duration)
            if buff_rule.combo and self.last_skill != buff_rule.combo:
                continue_chance = False
            else:
                continue_chance = True
            for key, duration, chance in buff_rule.chance_grants:
                if continue_chance and self.rng.random() < chance:
                    self._grant(key, duration)
        self.last_skill = canonical
        if is_gcd:
            self._gcd_count += 1
            for key, amount in self.spec.gcd_gain.items():
                self._apply(key, amount)
            for key, (period, amount) in self.spec.periodic.items():
                if self._gcd_count % max(1, period) == 0:
                    self._apply(key, amount)
        return True, ""

    def snapshot(self) -> list[tuple[Resource, float]]:
        return [
            (resource, self.values.get(resource.key, 0.0))
            for resource in self.spec.resources
        ]

    def active_buffs(self, now: float | None = None) -> list[tuple[Buff, float]]:
        self._expire(self.now if now is None else now)
        out: list[tuple[Buff, float]] = []
        for key, buff in self.spec.buffs.items():
            expiry = self.buff_expiry.get(key, 0.0)
            if expiry > self.now:
                out.append((buff, expiry - self.now))
        return out

    def is_proc(self, name: str, now: float | None = None) -> bool:
        """技能是否因 buff 触发而可施放（用于热键栏原生高亮）。"""
        return self.empowered(name, now)
