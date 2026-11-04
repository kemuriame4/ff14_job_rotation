from __future__ import annotations

import json
from pathlib import Path

from .models import Job, Skill

BASE_DIR = Path(__file__).resolve().parent.parent
GAME_DATA_FILE = BASE_DIR / "data" / "game_data.json"
ICON_DIR = BASE_DIR / "assets" / "icons"

CATEGORY_COLORS = {2: "#4fa3d1", 3: "#e0794a", 4: "#d9b55a"}

_data: dict | None = None


def game_data() -> dict | None:
    global _data
    if _data is None:
        if not GAME_DATA_FILE.exists():
            return None
        try:
            _data = json.loads(GAME_DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return _data


def icon_file(icon_id: int) -> Path | None:
    if not icon_id:
        return None
    path = ICON_DIR / f"{icon_id}.png"
    return path if path.exists() else None


def status_info(name: str) -> dict:
    """游戏数据中抓取到的状态（buff）信息：图标、说明。"""
    if not name:
        return {}
    data = game_data()
    if not data:
        return {}
    return data.get("statuses", {}).get(name, {})


def game_jobs() -> list[Job]:
    data = game_data()
    if not data:
        return []
    skills_by_job: dict[int, list[dict]] = {}
    for skill in data.get("skills", []):
        for job_id in skill.get("jobs", []):
            skills_by_job.setdefault(int(job_id), []).append(skill)

    jobs: list[Job] = []
    for meta in data.get("jobs", []):
        job_id = int(meta["id"])
        rows = sorted(
            skills_by_job.get(job_id, []),
            key=lambda s: (int(s.get("level") or 0), int(s["id"])),
        )
        skills: list[Skill] = []
        seen: set[str] = set()
        for row in rows:
            name = str(row.get("name") or row.get("name_en") or "").strip()
            if not name or name in seen:  # 同名技能（如青魔的赞歌）只保留首个
                continue
            seen.add(name)
            skills.append(
                Skill(
                    name=name,
                    color=CATEGORY_COLORS.get(int(row.get("category") or 4), "#8d97a8"),
                    icon=int(row.get("icon") or 0),
                    recast=float(row.get("recast") or 0.0),
                    gcd=bool(row.get("gcd", True)),
                    charges=int(row.get("charges") or 0),
                    combo=str(row.get("combo") or ""),
                    level=int(row.get("level") or 0),
                    transform=[
                        str(x) for x in row.get("transform", []) if str(x).strip()
                    ],
                    attack_range=float(row.get("range") or 0.0),
                    effect_range=float(row.get("effect_range") or 0.0),
                    potency=float(row.get("potency") or 0.0),
                    combo_potency=float(row.get("combo_potency") or 0.0),
                )
            )
        gcd_count = sum(1 for s in skills if s.gcd)
        job = Job(
            id=f"j{job_id}",
            name=f"{meta.get('name') or meta.get('name_en')}（{meta.get('abbrev')}）",
            gcd=2.5,
            loop=True,
            cycle_length=30.0,
            notes=(
                f"游戏数据导入：{len(skills)} 个技能（GCD {gcd_count} / oGCD {len(skills) - gcd_count}）。"
                "尚未配置标准循环，请到「标准循环」页添加步骤，并在「键位映射」页绑定按键。"
            ),
            skills=skills,
            rotation=[],
            abbrev=str(meta.get("abbrev") or ""),
            role=str(meta.get("role") or ""),
            hotbar=[],
            hotbar_keys=[],
        )
        jobs.append(job)
    return jobs


_GAME_SKILL_FIELDS = (
    "icon",
    "recast",
    "gcd",
    "charges",
    "combo",
    "level",
    "transform",
    "attack_range",
    "effect_range",
    "potency",
    "combo_potency",
)


def _sync_job_skills(target: Job, source: Job) -> None:
    """用游戏数据刷新已有职业的技能表，保留用户的键位、颜色与标准循环。"""
    existing = {skill.name: skill for skill in target.skills}
    source_names = set()
    refreshed: list[Skill] = []
    for new_skill in source.skills:
        source_names.add(new_skill.name)
        old = existing.get(new_skill.name)
        if old is None:
            refreshed.append(new_skill)
            continue
        for attr in _GAME_SKILL_FIELDS:
            setattr(old, attr, getattr(new_skill, attr))
        if not old.color or old.color == "#5c9fe0":
            old.color = new_skill.color
        refreshed.append(old)
    # 保留用户手动添加（不在游戏数据中的）技能
    for skill in target.skills:
        if skill.name not in source_names:
            refreshed.append(skill)
    target.skills = refreshed
    target.normalize_hotbar()
    target.apply_hotbar_keys()
    target.layout_rotation()


def _skill_signature(job: Job) -> list[tuple]:
    return [
        (
            s.name,
            s.key,
            s.icon,
            s.recast,
            s.gcd,
            s.charges,
            s.combo,
            s.level,
            tuple(s.transform),
            s.color,
            s.attack_range,
            s.effect_range,
            s.potency,
            s.combo_potency,
        )
        for s in job.skills
    ]


def merge_jobs(existing: list[Job]) -> tuple[list[Job], bool]:
    """把游戏数据里的职业并入现有列表；已存在的游戏职业同步最新技能数据。"""
    merged = list(existing)
    by_id = {job.id: job for job in merged}
    changed = False
    for job in game_jobs():
        current = by_id.get(job.id)
        if current is None:
            merged.append(job)
            by_id[job.id] = job
            changed = True
            continue
        before = (
            _skill_signature(current),
            tuple(current.hotbar),
            tuple(current.hotbar_keys),
        )
        _sync_job_skills(current, job)
        after = (
            _skill_signature(current),
            tuple(current.hotbar),
            tuple(current.hotbar_keys),
        )
        if before != after:
            changed = True
    return merged, changed
