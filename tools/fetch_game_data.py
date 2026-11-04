"""从 XIVAPI v2 与中文数据挖掘仓库抓取全部职业技能、图标、冷却与变换数据。

用法：
  .venv\\Scripts\\python.exe tools\\fetch_game_data.py            # 抓数据 + 下载图标
  .venv\\Scripts\\python.exe tools\\fetch_game_data.py --icons-only  # 仅补下载图标
  .venv\\Scripts\\python.exe tools\\fetch_game_data.py --refresh    # 忽略本地缓存重新抓表
输出：data/game_data.json、assets/icons/*.png
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://v2.xivapi.com/api"
CN_BASE = "https://raw.githubusercontent.com/thewakingsands/ffxiv-datamining-cn/master"
HEADERS = {"User-Agent": "ff14-rotation-trainer/1.0"}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ICON_DIR = BASE_DIR / "assets" / "icons"
OUT_FILE = DATA_DIR / "game_data.json"
CACHE_DIR = Path(tempfile.gettempdir()) / "ff14_fetch_cache" / "v2"

# 战斗职业（不含基础职业、生产采集、青魔/兽王等限定职业）
JOB_IDS = [
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    27,
    28,
    30,
    31,
    32,
    33,
    34,
    35,
    37,
    38,
    39,
    40,
    41,
    42,
    36,
]

# 基础职业 → 可使用的职业（职业技能中的基础连击、投盾等来自这些职业）
CLASS_TO_JOBS = {
    1: (19,),  # 剑术师 → 骑士
    2: (20,),  # 格斗家 → 武僧
    3: (21,),  # 斧术师 → 战士
    4: (22,),  # 枪术师 → 龙骑士
    5: (23,),  # 弓术师 → 吟游诗人
    6: (24,),  # 幻术师 → 白魔法师
    7: (25,),  # 咒术师 → 黑魔法师
    26: (27, 28),  # 秘术师 → 召唤师 / 学者
    29: (30,),  # 双剑师 → 忍者
}

JOB_ABBREVS = (
    "GLA,PGL,MRD,LNC,ARC,CNJ,THM,ACN,ROG,"
    "PLD,MNK,WAR,DRG,BRD,WHM,BLM,SMN,SCH,NIN,MCH,DRK,AST,SAM,RDM,BLU,GNB,DNC,RPR,SGE,VPR,PCT"
)

# v2 的 Role 表只有枚举 Type，不再提供名称；按 ClassJob.Role 行号映射常用职能名。
ROLE_NAMES = {1: "坦克", 2: "近战", 3: "远程", 4: "治疗"}

ACTION_FIELDS = (
    "Name,Icon,ActionCategory.value,ClassJob.value,Recast100ms,ActionCombo.value,"
    "ActionProcStatus.value,CooldownGroup,AdditionalCooldownGroup,ClassJobLevel,"
    "IsPlayerAction,IsPvP,IsRoleAction,MaxCharges,PreservesCombo,ClassJobCategory.value,"
    "Range,EffectRange"
)
SKILL_CATEGORIES = {2, 3, 4}  # Spell / Weaponskill / Ability

# 官方 Action 表未记录、但游戏内由前置技能变化而来的技能
CURATED_TRANSFORMS = [
    ("标准舞步", "标准舞步结束"),
    ("标准舞步", "单色标准舞步结束"),
    ("标准舞步", "双色标准舞步结束"),
    ("标准舞步", "结束动作"),
    ("技巧舞步", "技巧舞步结束"),
    ("技巧舞步", "单色技巧舞步结束"),
    ("技巧舞步", "双色技巧舞步结束"),
    ("技巧舞步", "三色技巧舞步结束"),
    ("技巧舞步", "四色技巧舞步结束"),
    ("技巧舞步结束", "提拉纳"),
    ("单色技巧舞步结束", "提拉纳"),
    ("双色技巧舞步结束", "提拉纳"),
    ("三色技巧舞步结束", "提拉纳"),
    ("四色技巧舞步结束", "提拉纳"),
    ("忍术", "风遁之术"),
    ("忍术", "火遁之术"),
    ("忍术", "雷遁之术"),
    ("忍术", "冰遁之术"),
    ("忍术", "土遁之术"),
    ("忍术", "水遁之术"),
    ("忍术", "通灵之术"),
]


def _request(url: str, as_json: bool = True, retries: int = 5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=40) as resp:
                payload = resp.read()
            return json.loads(payload) if as_json else payload
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(1.0 + attempt * 1.5)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(1.0 + attempt)
                continue
            raise
    raise RuntimeError(f"请求失败：{url}")


def sheet(path: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}/sheet/{path}" + (f"?{query}" if query else "")
    return _request(url)


def fetch_pages(
    sheet_name: str,
    fields: str,
    limit: int = 500,
    refresh: bool = False,
    start_after: int = 0,
) -> list[dict]:
    cache = CACHE_DIR / f"{sheet_name}_{limit}.json"
    if cache.exists() and not refresh:
        print(f"  复用缓存 {cache.name}")
        return json.loads(cache.read_text(encoding="utf-8"))
    rows: list[dict] = []
    after = start_after
    page = 0
    while True:
        data = sheet(sheet_name, fields=fields, limit=limit, after=after)
        batch = data.get("rows", [])
        if not batch:
            break
        rows.extend(batch)
        after = batch[-1]["row_id"]
        page += 1
        print(f"  {sheet_name} 第 {page} 页，累计 {len(rows)} 行", end="\r", flush=True)
    print()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def fetch_cn_names(csv_name: str) -> dict[int, str]:
    url = f"{CN_BASE}/{csv_name}"
    raw = _request(url, as_json=False).decode("utf-8-sig")
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    names: dict[int, str] = {}
    for row in rows[3:]:
        if not row:
            continue
        try:
            key = int(row[0])
        except ValueError:
            continue
        name = row[1].strip() if len(row) > 1 else ""
        if name:
            names[key] = name
    return names


def fetch_cn_descriptions() -> dict[int, str]:
    """读取中文技能说明，用于解析威力数值。"""
    raw = _request(f"{CN_BASE}/ActionTransient.csv", as_json=False).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    descriptions: dict[int, str] = {}
    for row in rows[3:]:
        if not row:
            continue
        try:
            key = int(row[0])
        except ValueError:
            continue
        if len(row) > 1 and row[1].strip():
            descriptions[key] = row[1]
    return descriptions


def fetch_cn_status_table() -> dict[int, dict]:
    """读取状态（buff）中文名、说明与图标 ID。"""
    raw = _request(f"{CN_BASE}/Status.csv", as_json=False).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    out: dict[int, dict] = {}
    for row in rows[3:]:
        if not row:
            continue
        try:
            key = int(row[0])
        except ValueError:
            continue
        name = row[1].strip() if len(row) > 1 else ""
        if not name:
            continue
        out[key] = {
            "name": name,
            "description": row[2].strip() if len(row) > 2 else "",
            "icon": int(row[3]) if len(row) > 3 and row[3].isdigit() else 0,
        }
    return out


def buff_labels() -> set[str]:
    """读取量谱规则里引用的状态名，只保留这些状态，避免数据膨胀。"""
    import sys

    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    try:
        from app.jobs import all_specs
    except Exception:  # pragma: no cover - 数据脚本不依赖应用运行
        return set()
    labels: set[str] = set()
    for spec in all_specs().values():
        labels.update(buff.label for buff in spec.buffs.values())
    return labels


def collect_statuses(refresh: bool = False) -> dict[str, dict]:
    """从游戏源抓取状态信息，供训练页量谱下方显示。"""
    print("读取状态表…")
    rows = fetch_pages("Status", "Name,Icon", limit=500, refresh=refresh, start_after=1)
    cn_status = fetch_cn_status_table()
    wanted = buff_labels()
    statuses: dict[str, dict] = {}
    for row in rows:
        row_id = row["row_id"]
        cn = cn_status.get(row_id)
        if not cn:
            continue
        name = cn["name"]
        if wanted and name not in wanted:
            continue
        icon_id, icon_path = icon_ref(row["fields"].get("Icon"))
        statuses[name] = {
            "id": row_id,
            "icon": icon_id or cn["icon"],
            "icon_path": icon_path,
            "description": _TAG_RE.sub("", cn["description"]).strip(),
        }
    print(f"命中状态 {len(statuses)} / 需求 {len(wanted)}")
    return statuses


_TAG_RE = re.compile(r"<[^>]+>")
_NUMBER_RE = re.compile(r"\d+")


def _potency_candidates(line: str, keyword: str) -> list[float]:
    """从说明行中取出威力候选（过滤两位数的颜色代码）。"""
    index = line.find(keyword)
    if index < 0:
        return []
    segment = line[index + len(keyword) :]
    return [float(token) for token in _NUMBER_RE.findall(segment) if len(token) >= 3]


def parse_potency(description: str) -> tuple[float, float]:
    """从技能说明解析单体威力与连击威力（持续伤害不计入）。"""
    text = _TAG_RE.sub(" ", description or "")
    base: list[float] = []
    combo: list[float] = []
    for line in re.split(r"\r?\n", text):
        # 游戏内文案为“连击中威力”，旧版数据挖取为“连击威力”。
        keyword = next(
            (word for word in ("连击中威力", "连击威力") if word in line), ""
        )
        if keyword:
            combo.extend(_potency_candidates(line, keyword))
            continue
        if "威力" not in line:
            continue
        if "持续" in line or "连击" in line:
            continue
        base.extend(_potency_candidates(line, "威力"))
    return (max(base) if base else 0.0, max(combo) if combo else 0.0)


_HEX_COLOR_RE = re.compile(r"[0-9A-F]{6,}")
_NAME_RE = re.compile(r"[\u4e00-\u9fff·]+")


def parse_transform_refs(description: str, source_name: str) -> list[tuple[str, str]]:
    """解析「跳舞模式中该技能变为 X」「满足发动条件后，A 和 B 变为 C」等说明。"""
    text = _HEX_COLOR_RE.sub("", _TAG_RE.sub("", description or ""))
    pairs: list[tuple[str, str]] = []
    for line in re.split(r"\r?\n", text):
        index = line.find("变为")
        if index < 0:
            continue
        before, after = line[:index], line[index + 2 :]
        targets = _NAME_RE.findall(after)
        if not targets:
            continue
        target = targets[0]
        if "该技能" in before:
            sources = [source_name]
        elif "满足发动条件后" in before:
            tail = before.split("满足发动条件后", 1)[1].replace("该技能", source_name)
            sources = _NAME_RE.findall(tail) or [source_name]
        else:
            continue
        for src in sources:
            pairs.append((src, target))
    return pairs


def fetch_replace_pairs() -> dict[int, list[int]]:
    """读取技能替换表：使用/满足条件后 A 变成 B。"""
    raw = _request(f"{CN_BASE}/ReplaceAction.csv", as_json=False).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    pairs: dict[int, list[int]] = {}
    for row in rows[3:]:
        if len(row) < 11:
            continue
        try:
            src = int(row[1])
        except ValueError:
            continue
        if not src:
            continue
        for index in (4, 7, 10):
            try:
                dst = int(row[index])
            except (ValueError, IndexError):
                continue
            if dst and dst != src:
                pairs.setdefault(src, [])
                if dst not in pairs[src]:
                    pairs[src].append(dst)
    return pairs


def ref_value(value) -> int:
    if isinstance(value, dict):
        return int(value.get("value", 0))
    return int(value or 0)


def icon_ref(value) -> tuple[int, str]:
    if isinstance(value, dict):
        return int(value.get("id") or 0), str(
            value.get("path_hr1") or value.get("path") or ""
        )
    return 0, ""


def build_skill(
    row_id: int,
    fields: dict,
    owners: list[int],
    cn_action: dict[int, str],
    descriptions: dict[int, str],
) -> dict:
    icon_id, icon_path = icon_ref(fields.get("Icon"))
    category = ref_value(fields.get("ActionCategory"))
    name_en = (fields.get("Name") or "").strip()
    potency, combo_potency = parse_potency(descriptions.get(row_id, ""))
    return {
        "id": row_id,
        "jobs": owners,
        "name": cn_action.get(row_id) or name_en,
        "name_en": name_en,
        "icon": icon_id,
        "icon_path": icon_path,
        "category": category,
        "recast": round(float(fields.get("Recast100ms", 0)) / 10.0, 3),
        "gcd": category in (2, 3),
        "charges": int(fields.get("MaxCharges") or 0),
        "level": int(fields.get("ClassJobLevel") or 0),
        "combo_id": ref_value(fields.get("ActionCombo")),
        "proc_id": ref_value(fields.get("ActionProcStatus")),
        "role_action": bool(fields.get("IsRoleAction")),
        "range": float(fields.get("Range") or 0),
        "effect_range": float(fields.get("EffectRange") or 0),
        "potency": potency,
        "combo_potency": combo_potency,
    }


def owners_for(
    fields: dict, job_meta: dict, category_jobs: dict[int, set[str]]
) -> list[int]:
    job_id = ref_value(fields.get("ClassJob"))
    if job_id in job_meta:
        return [job_id]
    if job_id in CLASS_TO_JOBS:
        return list(CLASS_TO_JOBS[job_id])
    # 职能技能与"变化结果"技能没有直属职业，用职业分类表反查
    mapped = category_jobs.get(ref_value(fields.get("ClassJobCategory")), set())
    return [jid for jid, meta in job_meta.items() if meta["abbrev"] in mapped]


def is_transform(src: dict, dst: dict) -> bool:
    """区分「技能变换」与「特性升级 / 连击后续」：升级与连击不作为变换展示。"""
    if dst["name"] == src["name"]:
        return False
    if int(dst.get("proc_id") or 0):  # 触发类变化（如精准刺 → 龙眼雷电）
        return True
    return int(dst.get("level") or 0) <= int(src.get("level") or 0)


def collect(refresh: bool = False) -> dict:
    print("读取职业表…")
    job_rows = sheet(
        "ClassJob",
        fields="Name,Abbreviation,Role,ClassJobCategory.value,IsLimitedJob",
        limit=60,
    )["rows"]
    job_meta = {}
    for row in job_rows:
        jid = row["row_id"]
        if jid not in JOB_IDS:
            continue
        fields = row["fields"]
        job_meta[jid] = {
            "id": jid,
            "abbrev": fields.get("Abbreviation", ""),
            # v2 的 ClassJob.Name 为全小写，恢复为首字母大写以保持旧数据格式。
            "name_en": str(fields.get("Name", "")).title(),
            "role": ROLE_NAMES.get(ref_value(fields.get("Role")), ""),
            "limited": bool(fields.get("IsLimitedJob", False)),
        }

    print("读取职业分类表…")
    categories = fetch_pages(
        "ClassJobCategory", f"Name,{JOB_ABBREVS}", limit=500, refresh=refresh
    )
    category_jobs: dict[int, set[str]] = {}
    abbrevs = {meta["abbrev"] for meta in job_meta.values()}
    for row in categories:
        fields = row["fields"]
        category_jobs[row["row_id"]] = {
            key for key, value in fields.items() if key in abbrevs and value is True
        }

    print("读取技能表…")
    actions = fetch_pages("Action", ACTION_FIELDS, refresh=refresh)
    action_by_id = {row["row_id"]: row["fields"] for row in actions}

    print("读取中文名称与技能替换表…")
    cn_action = fetch_cn_names("Action.csv")
    cn_job = fetch_cn_names("ClassJob.csv")
    descriptions = fetch_cn_descriptions()
    replace_pairs = fetch_replace_pairs()

    skills: list[dict] = []
    skipped: dict[str, int] = {}
    for row in actions:
        f = row["fields"]
        if f.get("IsPvP"):
            continue
        category = ref_value(f.get("ActionCategory"))
        if category not in SKILL_CATEGORIES:
            skipped[str(category)] = skipped.get(str(category), 0) + 1
            continue
        name_en = (f.get("Name") or "").strip()
        if not name_en:
            continue
        owners = owners_for(f, job_meta, category_jobs)
        if not owners:
            continue
        # 非"可主动施放"的动作只保留有职业归属且具备等级的变化结果（忍术、舞步结束、三连剑等）
        if not f.get("IsPlayerAction") and int(f.get("ClassJobLevel") or 0) <= 1:
            continue
        skills.append(build_skill(row["row_id"], f, owners, cn_action, descriptions))

    skill_by_id = {s["id"]: s for s in skills}

    # 技能变换：把替换目标补进技能表，并记录 A → B 的变化关系
    added = 0
    for src_id, targets in replace_pairs.items():
        src = skill_by_id.get(src_id)
        if src is None:
            continue
        for dst_id in targets:
            dst = skill_by_id.get(dst_id)
            if dst is None:
                f = action_by_id.get(dst_id)
                if not f or f.get("IsPvP"):
                    continue
                if ref_value(f.get("ActionCategory")) not in SKILL_CATEGORIES:
                    continue
                if not (f.get("Name") or "").strip():
                    continue
                dst = build_skill(dst_id, f, list(src["jobs"]), cn_action, descriptions)
                skills.append(dst)
                skill_by_id[dst_id] = dst
                added += 1
            if dst_id == src_id or not set(src["jobs"]) & set(dst["jobs"]):
                continue
            if not is_transform(src, dst):
                continue
            forms = src.setdefault("transform", [])
            if dst["name"] not in forms:
                forms.append(dst["name"])

    # 官方表未记录的变化关系（舞步结束、忍术等）
    name_index: dict[str, list[dict]] = {}
    for skill in skills:
        name_index.setdefault(skill["name"], []).append(skill)

    # 从中文说明「满足发动条件后，A 变为 B」补充变化关系
    description_pairs = 0
    for skill in skills:
        for src_name, dst_name in parse_transform_refs(
            descriptions.get(skill["id"], ""), skill["name"]
        ):
            for src in name_index.get(src_name, []):
                for dst in name_index.get(dst_name, []):
                    if not set(src["jobs"]) & set(dst["jobs"]):
                        continue
                    forms = src.setdefault("transform", [])
                    if dst["name"] not in forms:
                        forms.append(dst["name"])
                        description_pairs += 1

    for src_name, dst_name in CURATED_TRANSFORMS:
        for src in name_index.get(src_name, []):
            for dst in name_index.get(dst_name, []):
                if set(src["jobs"]) & set(dst["jobs"]):
                    forms = src.setdefault("transform", [])
                    if dst["name"] not in forms:
                        forms.append(dst["name"])

    name_by_id = {s["id"]: s["name"] for s in skills}
    for skill in skills:
        combo_id = skill["combo_id"]
        skill["combo"] = name_by_id.get(combo_id, "") if combo_id else ""

    for job_id, meta in job_meta.items():
        meta["name"] = cn_job.get(job_id) or meta["name_en"]

    by_job: dict[int, int] = {}
    for skill in skills:
        for job_id in skill["jobs"]:
            by_job[job_id] = by_job.get(job_id, 0) + 1
    print(
        "各职业技能数：",
        ", ".join(f"{job_meta[j]['abbrev']}={by_job.get(j, 0)}" for j in job_meta),
    )
    print(
        "变换新增技能：",
        added,
        "条；说明补充变换：",
        description_pairs,
        "条；跳过的动作分类计数：",
        skipped,
    )

    return {
        "version": 8,
        "source": "XIVAPI v2 (v2.xivapi.com) + ffxiv-datamining-cn",
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": sorted(job_meta.values(), key=lambda m: m["id"]),
        "skills": skills,
        "statuses": collect_statuses(refresh=refresh),
    }


def write_payload(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), indent=1),
        encoding="utf-8",
    )
    tmp.replace(OUT_FILE)
    print(f"已写入 {OUT_FILE}（{OUT_FILE.stat().st_size / 1024:.0f} KB）")


def _download_one(item: tuple[int, str]) -> tuple[int, str]:
    icon_id, path = item
    target = ICON_DIR / f"{icon_id}.png"
    if target.exists():
        return icon_id, "skip"
    raw = _request(
        f"{BASE}/asset?path={urllib.parse.quote(path, safe='/')}&format=png",
        as_json=False,
    )
    tmp = target.with_suffix(".part")
    tmp.write_bytes(raw)
    tmp.replace(target)
    return icon_id, "ok"


def download_icons(
    skills: list[dict], statuses: dict[str, dict] | None = None, workers: int = 8
) -> None:
    icons: dict[int, str] = {}
    for skill in skills:
        if skill["icon"] and skill["icon_path"]:
            icons.setdefault(skill["icon"], skill["icon_path"])
    for status in (statuses or {}).values():
        icon_id = int(status.get("icon") or 0)
        path = status.get("icon_path") or ""
        if icon_id and path:
            icons.setdefault(icon_id, path)
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    pending = [
        (i, p) for i, p in sorted(icons.items()) if not (ICON_DIR / f"{i}.png").exists()
    ]
    total = len(pending)
    print(f"共 {len(skills)} 条技能，{len(icons)} 个图标，待下载 {total} 个")
    if not total:
        return

    done = 0
    failed = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, item): item for item in pending}
        for future in as_completed(futures):
            icon_id, _path = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"\n  图标 {icon_id} 下载失败：{exc}")
            with lock:
                done += 1
                if done % 40 == 0 or done == total:
                    print(
                        f"  图标进度 {done}/{total}（失败 {failed}）",
                        end="\r",
                        flush=True,
                    )
    print(f"\n图标下载完成，共 {len(icons)} 个，本次失败 {failed} 个")


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 FF14 职业技能与图标")
    parser.add_argument(
        "--icons-only",
        action="store_true",
        help="复用已有 game_data.json ，仅下载缺失图标",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="复用已有技能数据 ，仅抓取状态（ buff ）信息与图标",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="忽略本地缓存重新抓取表格"
    )
    parser.add_argument("--workers", type=int, default=8, help="图标并发下载线程数")
    args = parser.parse_args()

    if args.icons_only:
        if not OUT_FILE.exists():
            raise SystemExit(f"未找到 {OUT_FILE}，请先完整运行一次抓取。")
        payload = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        print(f"复用 {OUT_FILE}，技能 {len(payload['skills'])} 条")
    elif args.status_only:
        if not OUT_FILE.exists():
            raise SystemExit(f"未找到 {OUT_FILE}，请先完整运行一次抓取。")
        payload = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        payload["statuses"] = collect_statuses(refresh=args.refresh)
        write_payload(payload)
    else:
        payload = collect(refresh=args.refresh)
        write_payload(payload)

    download_icons(
        payload["skills"],
        payload.get("statuses", {}),
        workers=max(1, args.workers),
    )


if __name__ == "__main__":
    main()
