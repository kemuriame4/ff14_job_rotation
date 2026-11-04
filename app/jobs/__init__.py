"""职业专属逻辑注册表。

新增职业时，在本目录下创建 ``<职业缩写>.py`` 并实现 ``JobLogic``,
然后加入 ``_JOB_LOGICS`` 即可。
"""

from __future__ import annotations

from ..gauge import SPECS, GaugeSpec
from .base import JobLogic
from .dnc import DncLogic

_JOB_LOGICS: dict[str, type[JobLogic]] = {
    DncLogic.abbrev: DncLogic,
}


def new_job_logic(job) -> JobLogic | None:
    """为当前职业创建一份新的职业逻辑实例（无专属逻辑则返回 None ）。"""
    logic = _JOB_LOGICS.get(job.abbrev)
    return logic() if logic is not None else None


def gauge_spec_for(job) -> GaugeSpec:
    """取职业量谱规格：优先使用职业逻辑自带的规格。"""
    logic = _JOB_LOGICS.get(job.abbrev)
    if logic is not None and logic.gauge is not None:
        return logic.gauge
    return SPECS.get(job.abbrev, GaugeSpec(name="无职业量谱"))


def all_specs() -> dict[str, GaugeSpec]:
    """所有职业的量谱规格（含工具脚本需要读取的 buff 标签）。"""
    specs = dict(SPECS)
    specs.update(
        {
            abbrev: logic.gauge
            for abbrev, logic in _JOB_LOGICS.items()
            if logic.gauge is not None
        }
    )
    return specs
