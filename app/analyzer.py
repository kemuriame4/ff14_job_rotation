from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .cooldowns import CooldownTracker
from .gauge import COMBO_WINDOW
from .jobs.dnc import canonical_dance_name
from .models import Job
from .session import InputEvent

OK = "准确"
EARLY = "偏早"
LATE = "偏晚"
MISSING = "缺失"
EXTRA = "多余"
ORDER = "顺序错误"


@dataclass
class ExpectedEvent:
    t: float
    skill: str


@dataclass
class DiffRow:
    expected_index: int | None
    expected_t: float | None
    expected_skill: str | None
    actual_index: int | None
    actual_t: float | None
    actual_skill: str | None
    status: str
    delta: float | None


@dataclass
class AnalysisResult:
    job_name: str
    duration: float
    tolerance: float
    gcd: float
    score: int
    grade: str
    sequence_accuracy: float
    timing_accuracy: float
    matched_count: int
    expected_count: int
    press_count: int
    missing_count: int
    extra_count: int
    order_issue_count: int
    avg_abs_delta: float
    mean_delta: float
    std_delta: float
    max_abs_delta: float
    expected: list[tuple[float, str]] = field(default_factory=list)
    expected_statuses: list[str | None] = field(default_factory=list)
    actual: list[tuple[float, str]] = field(default_factory=list)
    actual_statuses: list[str | None] = field(default_factory=list)
    rows: list[DiffRow] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    cooldown_clashes: int = 0
    gcd_clashes: int = 0
    combo_breaks: int = 0
    expected_potency: float = 0.0
    actual_potency: float = 0.0
    expected_pps: float = 0.0
    actual_pps: float = 0.0
    potency_ratio: float = 0.0
    potency_grade: str = "—"
    state_issues: list[tuple[float, str, str]] = field(default_factory=list)


def total_potency(
    job: Job,
    timeline: list[tuple[float, str]],
    skip: set[tuple[float, str]] | None = None,
) -> float:
    """按施放顺序累计单体威力，连击命中时取连击威力。"""
    skipped = skip or set()
    total = 0.0
    last_used: dict[str, float] = {}
    for moment, name in timeline:
        if (round(moment, 2), name) in skipped:
            continue
        skill = job.skill(name)
        if skill is None:
            continue
        value = skill.potency
        if skill.combo and skill.combo_potency > 0:
            # 连击窗口内使用其他技能不会打断连击。
            started = last_used.get(skill.combo)
            if started is not None and moment - started <= COMBO_WINDOW:
                value = skill.combo_potency
        total += max(0.0, value)
        last_used[name] = moment
    return total


def _potency_grade(ratio: float) -> str:
    if ratio <= 0:
        return "—"
    if ratio >= 0.98:
        return "优秀"
    if ratio >= 0.9:
        return "良好"
    if ratio >= 0.75:
        return "一般"
    return "偏低"


def potency_ceiling(job: Job, duration: float) -> float:
    """无标准循环时的威力基准：始终施放最高威力 GCD 的理论上限。"""
    gcd = max(0.1, float(job.gcd or 0.1))
    top = max((s.potency for s in job.skills if s.gcd and s.potency > 0), default=0.0)
    return top / gcd * max(0.0, duration)


def update_actual_potency(
    job: Job, result: AnalysisResult, skip: set[tuple[float, str]] | None = None
) -> None:
    """排除状态不足的无效施放后，刷新实际威力与实用性评级。"""
    result.actual_potency = total_potency(job, result.actual, skip)
    result.actual_pps = (
        result.actual_potency / result.duration if result.duration > 0 else 0.0
    )
    basis = result.expected_potency or potency_ceiling(job, result.duration)
    result.potency_ratio = result.actual_potency / basis if basis > 0 else 0.0
    result.potency_grade = _potency_grade(result.potency_ratio)


def build_expected(job: Job, duration: float) -> list[ExpectedEvent]:
    steps = sorted((s for s in job.rotation if s.skill), key=lambda s: s.offset)
    if not steps or duration <= 0:
        return []
    if not job.loop:
        return [
            ExpectedEvent(s.offset, s.skill)
            for s in steps
            if s.offset < duration - 1e-6
        ]

    cycle = job.cycle_length if job.cycle_length > 0 else (steps[-1].offset + job.gcd)
    cycle = max(cycle, 0.1)
    out: list[ExpectedEvent] = []
    cycle_index = 0
    while cycle_index * cycle < duration - 1e-6:
        base = cycle_index * cycle
        for step in steps:
            t = base + step.offset
            if t < duration - 1e-6:
                out.append(ExpectedEvent(t, step.skill))
        cycle_index += 1
        if cycle_index > 10000:
            break
    return sorted(out, key=lambda e: e.t)


def _pair_by_timing(
    gcd: float, expected: list[ExpectedEvent], actual: list[InputEvent]
) -> list[tuple[int, int]]:
    """Pair same-skill presses with the closest expected event inside one GCD window.

    This keeps an early stray press from shifting every later same-skill comparison.
    """
    window = max(1.0, gcd * 0.9)
    by_skill: dict[str, list[int]] = {}
    for index, event in enumerate(expected):
        by_skill.setdefault(canonical_dance_name(event.skill), []).append(index)

    used: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for actual_index, event in enumerate(actual):
        candidates = [
            index
            for index in by_skill.get(canonical_dance_name(event.skill), [])
            if index not in used and abs(expected[index].t - event.t) <= window
        ]
        if not candidates:
            continue
        best = min(
            candidates, key=lambda index: (abs(expected[index].t - event.t), index)
        )
        used.add(best)
        pairs.append((best, actual_index))
    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _scan_availability(job: Job, actual: list[InputEvent]) -> tuple[int, int, int]:
    """按实际按键顺序推演冷却，统计冷却冲突、GCD 冲突与连击中断。"""
    tracker = CooldownTracker(job)
    cooldown_clashes = 0
    gcd_clashes = 0
    combo_breaks = 0
    last_used: dict[str, float] = {}
    for event in actual:
        skill = job.skill(event.skill)
        if skill is None:
            continue
        if skill.gcd and tracker.gcd_remaining(event.t) > 0.2:
            gcd_clashes += 1
        elif tracker.on_cooldown(skill, event.t, slack=0.2):
            cooldown_clashes += 1
        if skill.combo and last_used:
            started = last_used.get(skill.combo)
            if started is None or event.t - started > COMBO_WINDOW:
                combo_breaks += 1
        tracker.on_cast(skill.name, event.t)
        last_used[skill.name] = event.t
    return cooldown_clashes, gcd_clashes, combo_breaks


def _grade(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def analyze(
    job: Job, events: list[InputEvent], duration: float, tolerance: float
) -> AnalysisResult:
    duration = max(0.0, float(duration))
    tolerance = max(0.01, float(tolerance))
    expected = build_expected(job, duration)
    actual = [e for e in events if e.t <= duration + 1e-6]

    pairs = _pair_by_timing(job.gcd, expected, actual)
    paired_expected = {i for i, _ in pairs}
    paired_actual = {j for _, j in pairs}

    # Pair leftover same-skill presses as ordering mistakes (e.g. A B vs B A).
    leftover_expected = [i for i in range(len(expected)) if i not in paired_expected]
    leftover_actual = [j for j in range(len(actual)) if j not in paired_actual]
    used_actual: set[int] = set()
    order_pairs: list[tuple[int, int]] = []
    for ei in leftover_expected:
        for aj in leftover_actual:
            if aj not in used_actual and canonical_dance_name(
                actual[aj].skill
            ) == canonical_dance_name(expected[ei].skill):
                order_pairs.append((ei, aj))
                used_actual.add(aj)
                break
    order_expected = {i for i, _ in order_pairs}
    order_actual = {j for _, j in order_pairs}
    missing_expected = [i for i in leftover_expected if i not in order_expected]
    extra_actual = [j for j in leftover_actual if j not in used_actual]

    expected_statuses: list[str | None] = [None] * len(expected)
    actual_statuses: list[str | None] = [None] * len(actual)
    rows: list[DiffRow] = []

    for ei, aj in pairs:
        delta = actual[aj].t - expected[ei].t
        if abs(delta) <= tolerance:
            status = OK
        elif delta < 0:
            status = EARLY
        else:
            status = LATE
        expected_statuses[ei] = status
        actual_statuses[aj] = status
        rows.append(
            DiffRow(
                ei + 1,
                expected[ei].t,
                expected[ei].skill,
                aj + 1,
                actual[aj].t,
                actual[aj].skill,
                status,
                delta,
            )
        )

    for ei, aj in order_pairs:
        delta = actual[aj].t - expected[ei].t
        expected_statuses[ei] = ORDER
        actual_statuses[aj] = ORDER
        rows.append(
            DiffRow(
                ei + 1,
                expected[ei].t,
                expected[ei].skill,
                aj + 1,
                actual[aj].t,
                actual[aj].skill,
                ORDER,
                delta,
            )
        )

    for ei in missing_expected:
        expected_statuses[ei] = MISSING
        rows.append(
            DiffRow(
                ei + 1,
                expected[ei].t,
                expected[ei].skill,
                None,
                None,
                None,
                MISSING,
                None,
            )
        )

    for aj in extra_actual:
        actual_statuses[aj] = EXTRA
        rows.append(
            DiffRow(
                None, None, None, aj + 1, actual[aj].t, actual[aj].skill, EXTRA, None
            )
        )

    rows.sort(
        key=lambda r: r.expected_t if r.expected_t is not None else (r.actual_t or 0.0)
    )

    deltas = [actual[aj].t - expected[ei].t for ei, aj in pairs]
    within = sum(1 for d in deltas if abs(d) <= tolerance)
    expected_count = len(expected)
    press_count = len(actual)
    matched_count = len(pairs)
    cooldown_clashes, gcd_clashes, combo_breaks = _scan_availability(job, actual)
    sequence_accuracy = matched_count / expected_count if expected_count else 0.0
    timing_accuracy = within / matched_count if matched_count else 0.0
    avg_abs_delta = sum(abs(d) for d in deltas) / len(deltas) if deltas else 0.0
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    std_delta = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
    max_abs_delta = max((abs(d) for d in deltas), default=0.0)

    penalty = min(
        20.0,
        (len(extra_actual) + len(order_pairs)) * 1.5
        + (cooldown_clashes + gcd_clashes + combo_breaks) * 1.0,
    )
    score = int(
        round(
            max(
                0.0,
                min(100.0, 60.0 * sequence_accuracy + 40.0 * timing_accuracy - penalty),
            )
        )
    )

    suggestions = _suggestions(
        job,
        expected_count,
        matched_count,
        missing_expected,
        extra_actual,
        order_pairs,
        expected,
        actual,
        mean_delta,
        std_delta,
        avg_abs_delta,
        tolerance,
        score,
        cooldown_clashes,
        gcd_clashes,
        combo_breaks,
    )

    expected_potency = total_potency(job, [(e.t, e.skill) for e in expected])
    actual_potency = total_potency(job, [(e.t, e.skill) for e in actual])
    expected_pps = expected_potency / duration if duration > 0 else 0.0
    actual_pps = actual_potency / duration if duration > 0 else 0.0
    basis = expected_potency or potency_ceiling(job, duration)
    potency_ratio = actual_potency / basis if basis > 0 else 0.0

    return AnalysisResult(
        job_name=job.name,
        duration=duration,
        tolerance=tolerance,
        gcd=job.gcd,
        score=score,
        grade=_grade(score),
        sequence_accuracy=sequence_accuracy,
        timing_accuracy=timing_accuracy,
        matched_count=matched_count,
        expected_count=expected_count,
        press_count=press_count,
        missing_count=len(missing_expected),
        extra_count=len(extra_actual),
        order_issue_count=len(order_pairs),
        avg_abs_delta=avg_abs_delta,
        mean_delta=mean_delta,
        std_delta=std_delta,
        max_abs_delta=max_abs_delta,
        expected=[(e.t, e.skill) for e in expected],
        expected_statuses=expected_statuses,
        actual=[(e.t, e.skill) for e in actual],
        actual_statuses=actual_statuses,
        rows=rows,
        suggestions=suggestions,
        cooldown_clashes=cooldown_clashes,
        gcd_clashes=gcd_clashes,
        combo_breaks=combo_breaks,
        expected_potency=expected_potency,
        actual_potency=actual_potency,
        expected_pps=expected_pps,
        actual_pps=actual_pps,
        potency_ratio=potency_ratio,
        potency_grade=_potency_grade(potency_ratio),
    )


def _suggestions(
    job: Job,
    expected_count: int,
    matched_count: int,
    missing: list[int],
    extra: list[int],
    order_pairs: list[tuple[int, int]],
    expected: list[ExpectedEvent],
    actual: list[InputEvent],
    mean_delta: float,
    std_delta: float,
    avg_abs_delta: float,
    tolerance: float,
    score: int,
    cooldown_clashes: int,
    gcd_clashes: int,
    combo_breaks: int,
) -> list[str]:
    if expected_count == 0:
        return ["当前职业还没有标准循环，请先在「标准循环」页添加步骤。"]
    if matched_count == 0:
        return [
            "没有按键与标准循环中的技能匹配，检查键位映射是否正确，或放慢速度重新开始。"
        ]

    out: list[str] = []
    if missing:
        names = sorted({expected[i].skill for i in missing})
        preview = "、".join(names[:4]) + ("…" if len(names) > 4 else "")
        out.append(f"漏按 {len(missing)} 个标准技能（{preview}），请对照时间轴补齐。")
    if extra:
        names = sorted({actual[j].skill for j in extra})
        out.append(
            f"出现 {len(extra)} 次标准循环之外的多余按键（{('、'.join(names[:4]))}）。"
        )
    if order_pairs:
        out.append(f"有 {len(order_pairs)} 处技能顺序与标准不同，注意连击顺序。")
    if gcd_clashes:
        out.append(
            f"有 {gcd_clashes} 次公共冷却（GCD）未就绪就按键，保持 {job.gcd:g}s 的施放间隔。"
        )
    if cooldown_clashes:
        out.append(
            f"有 {cooldown_clashes} 次技能仍在冷却中就被按下，注意 oGCD 的复唱时间。"
        )
    if combo_breaks:
        out.append(f"有 {combo_breaks} 次连击被打断，检查前置技能是否按顺序施放。")
    if abs(mean_delta) >= tolerance * 0.5:
        direction = "偏晚" if mean_delta > 0 else "偏早"
        out.append(
            f"整体节奏{direction}约 {abs(mean_delta) * 1000:.0f} ms，尝试对齐标准时间点。"
        )
    if std_delta >= 0.12:
        out.append(
            f"按键节奏波动较大(σ {std_delta * 1000:.0f} ms)，建议按固定 GCD 间隔练习。"
        )
    if avg_abs_delta > tolerance and len(out) == 0:
        out.append(
            f"平均时间偏差 {avg_abs_delta * 1000:.0f} ms，超出容差 {tolerance * 1000:.0f} ms。"
        )
    if not out:
        out.append("循环顺序与时间点都很稳，保持当前节奏。")
    if score >= 90 and len(out) <= 1:
        out.append(f"综合评分 {score} 分，已接近标准循环。")
    return out
