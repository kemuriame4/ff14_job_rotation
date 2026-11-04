from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

# 能力技不占 GCD，按该间隔依次织入当前 GCD 窗口（秒）
WEAVE_GAP = 0.65


@dataclass
class Skill:
    name: str
    key: str = ""
    color: str = "#5c9fe0"
    icon: int = 0
    recast: float = 0.0
    gcd: bool = True
    # 该技能占用的公共冷却时长；0 表示使用职业默认 GCD（舞步等短 GCD 技能用）。
    gcd_time: float = 0.0
    charges: int = 0
    combo: str = ""
    level: int = 0
    transform: list[str] = field(default_factory=list)
    attack_range: float = 0.0
    effect_range: float = 0.0
    potency: float = 0.0
    combo_potency: float = 0.0

    @property
    def is_aoe(self) -> bool:
        """作用半径为 0 视为单体技能，否则为范围伤害。"""
        return self.effect_range > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "key": self.key,
            "color": self.color,
            "icon": self.icon,
            "recast": self.recast,
            "gcd": self.gcd,
            "gcd_time": self.gcd_time,
            "charges": self.charges,
            "combo": self.combo,
            "level": self.level,
            "transform": list(self.transform),
            "attack_range": self.attack_range,
            "effect_range": self.effect_range,
            "potency": self.potency,
            "combo_potency": self.combo_potency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        return cls(
            name=str(data.get("name", "")).strip(),
            key=str(data.get("key", "")).strip(),
            color=str(data.get("color", "#5c9fe0")),
            icon=int(data.get("icon", 0) or 0),
            recast=float(data.get("recast", 0.0) or 0.0),
            gcd=bool(data.get("gcd", True)),
            gcd_time=float(data.get("gcd_time", 0.0) or 0.0),
            charges=int(data.get("charges", 0) or 0),
            combo=str(data.get("combo", "")),
            level=int(data.get("level", 0) or 0),
            transform=[str(x) for x in data.get("transform", []) if str(x).strip()],
            attack_range=float(data.get("attack_range", 0.0) or 0.0),
            effect_range=float(data.get("effect_range", 0.0) or 0.0),
            potency=float(data.get("potency", 0.0) or 0.0),
            combo_potency=float(data.get("combo_potency", 0.0) or 0.0),
        )


@dataclass
class Step:
    skill: str
    offset: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"skill": self.skill, "offset": round(self.offset, 3)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        return cls(
            skill=str(data.get("skill", "")).strip(),
            offset=float(data.get("offset", 0.0)),
        )


@dataclass
class Job:
    id: str
    name: str
    gcd: float = 2.5
    loop: bool = True
    cycle_length: float = 30.0
    notes: str = ""
    skills: list[Skill] = field(default_factory=list)
    rotation: list[Step] = field(default_factory=list)
    abbrev: str = ""
    role: str = ""
    hotbar: list[str] = field(default_factory=list)
    hotbar_keys: list[str] = field(default_factory=list)

    def skill(self, name: str) -> Skill | None:
        return next((s for s in self.skills if s.name == name), None)

    def normalize_hotbar(self) -> None:
        """热键栏按栏位顺序保存技能名（"" 表示空栏位），热键与栏位一一对应。"""
        names = {s.name for s in self.skills}
        keys = list(self.hotbar_keys)
        while len(keys) < len(self.hotbar):
            keys.append("")
        cleaned: list[str] = []
        cleaned_keys: list[str] = []
        seen: set[str] = set()
        for index, name in enumerate(self.hotbar):
            key = normalize_key_text(keys[index]) if index < len(keys) else ""
            if not name:
                cleaned.append("")
                cleaned_keys.append(key)
            elif name in names and name not in seen:
                cleaned.append(name)
                cleaned_keys.append(key)
                seen.add(name)
        while cleaned and not cleaned[-1] and not cleaned_keys[-1]:
            cleaned.pop()
            cleaned_keys.pop()
        self.hotbar = cleaned
        self.hotbar_keys = cleaned_keys

    def apply_hotbar_keys(self) -> None:
        """把栏位热键同步到当前技能上，供训练与判定使用。"""
        for skill in self.skills:
            skill.key = ""
        for name, key in zip(self.hotbar, self.hotbar_keys):
            skill = self.skill(name)
            if skill is not None:
                skill.key = normalize_key_text(key)

    def layout_rotation(self) -> float:
        """按技能类型与复唱时间推算每个步骤的期望时间，返回一轮总时长。

        GCD 技能按当前 GCD 间隔推进；能力技不占 GCD ，按 WEAVE_GAP 依次织入当前 GCD 窗口；
        同一技能重复出现时，受自身复唱时间限制。步骤顺序始终保留（时间不倒退）。
        """
        interval = max(0.1, float(self.gcd or 0.1))
        cursor = 0.0  # 下一个 GCD 的最早可用时间
        gcd_start: float | None = None  # 当前 GCD 窗口的起点
        weave = 0  # 当前 GCD 窗口内已织入的能力技数量
        last_t = 0.0
        last_use: dict[str, float] = {}
        end = 0.0
        for step in self.rotation:
            skill = self.skill(step.skill)
            recast = max(0.0, float(skill.recast)) if skill else 0.0
            ready = last_use[step.skill] + recast if step.skill in last_use else 0.0
            if skill is None or skill.gcd:
                t = max(cursor, ready, last_t)
                # 显式 GCD 时长优先；舞步等短复唱 GCD 按自身复唱推进，其余使用当前 GCD。
                gcd_interval = interval
                if skill is not None:
                    if skill.gcd_time > 0:
                        gcd_interval = skill.gcd_time
                    elif 0 < recast < interval:
                        gcd_interval = recast
                cursor = t + gcd_interval
                gcd_start = t
                weave = 0
                end = max(end, cursor)
            else:
                if gcd_start is None:
                    t = max(last_t, ready)
                else:
                    t = max(gcd_start + WEAVE_GAP * (weave + 1), ready, last_t)
                weave += 1
                end = max(end, t)
            t = round(t, 3)
            step.offset = t
            last_t = t
            last_use[step.skill] = t
        return round(end, 3)

    def key_lookup(self) -> dict[str, Skill]:
        lookup: dict[str, Skill] = {}
        for skill in self.skills:
            key = normalize_key_text(skill.key)
            if key:
                lookup[key] = skill
        return lookup

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "gcd": self.gcd,
            "loop": self.loop,
            "cycle_length": self.cycle_length,
            "notes": self.notes,
            "skills": [s.to_dict() for s in self.skills],
            "rotation": [s.to_dict() for s in self.rotation],
            "abbrev": self.abbrev,
            "role": self.role,
            "hotbar": list(self.hotbar),
            "hotbar_keys": list(self.hotbar_keys),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        skills = [
            Skill.from_dict(x)
            for x in data.get("skills", [])
            if str(x.get("name", "")).strip()
        ]
        rotation = [
            Step.from_dict(x)
            for x in data.get("rotation", [])
            if str(x.get("skill", "")).strip()
        ]
        job = cls(
            id=str(data.get("id", "")).strip() or "job",
            name=str(data.get("name", "")).strip() or "未命名职业",
            gcd=float(data.get("gcd", 2.5) or 2.5),
            loop=bool(data.get("loop", True)),
            cycle_length=float(data.get("cycle_length", 30.0) or 0.0),
            notes=str(data.get("notes", "")),
            skills=skills,
            rotation=rotation,
            abbrev=str(data.get("abbrev", "")),
            role=str(data.get("role", "")),
            hotbar=[str(x) for x in data.get("hotbar", [])],
            hotbar_keys=[str(x) for x in data.get("hotbar_keys", [])],
        )
        if "hotbar_keys" not in data:  # 旧数据：热键仍绑定在技能上
            job.hotbar_keys = []
            for name in job.hotbar:
                skill = job.skill(name)
                job.hotbar_keys.append(skill.key if skill else "")
        job.normalize_hotbar()
        job.apply_hotbar_keys()
        job.layout_rotation()
        return job


@dataclass
class Settings:
    job_id: str = ""
    duration: int = 60
    tolerance_ms: int = 350
    global_hook: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "duration": self.duration,
            "tolerance_ms": self.tolerance_ms,
            "global_hook": self.global_hook,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        return cls(
            job_id=str(data.get("job_id", "")),
            duration=int(data.get("duration", 60) or 60),
            tolerance_ms=int(data.get("tolerance_ms", 350) or 350),
            global_hook=bool(data.get("global_hook", True)),
        )


def normalize_key_text(key: str) -> str:
    return "+".join(part.strip().lower() for part in key.split("+") if part.strip())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def save_jobs(jobs: list[Job]) -> None:
    _write_json(JOBS_FILE, {"version": 1, "jobs": [j.to_dict() for j in jobs]})


def load_jobs() -> list[Job]:
    if JOBS_FILE.exists():
        try:
            data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
            jobs = [
                Job.from_dict(item)
                for item in data.get("jobs", [])
                if str(item.get("id", "")).strip()
            ]
            if jobs:
                return jobs
        except (OSError, ValueError, TypeError):
            pass
    return []


def load_settings() -> Settings:
    if SETTINGS_FILE.exists():
        try:
            return Settings.from_dict(
                json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError):
            pass
    return Settings()


def save_settings(settings: Settings) -> None:
    _write_json(SETTINGS_FILE, settings.to_dict())
