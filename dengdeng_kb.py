"""洛克王国配队知识库。

精灵事实走 JSON 精确查找。规则、技能和特性按板块从 knowledge/rules.md 取出相关片段。
同一份原文不重复索引 knowledge/知识库.md 和精灵 record。
配队助手只许引用这里和检索片段里已经写明的内容。
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge"
dengdeng_DIR = KNOWLEDGE_DIR / "dengdeng"
USAGE_PATH = KNOWLEDGE_DIR / "usage.json"
RULES_PATH = KNOWLEDGE_DIR / "rules.md"
GOLD_PATH = KNOWLEDGE_DIR / "gold_teams.jsonl"
PREFERENCE_DIR = ROOT / "data" / "preferences"
INTERACTION_PATH = PREFERENCE_DIR / "interactions.jsonl"
DPO_PATH = PREFERENCE_DIR / "dpo.jsonl"


def catalog_ready() -> bool:
    return any(dengdeng_DIR.glob("*.json")) if dengdeng_DIR.exists() else False


def load_dengdeng() -> List[Dict]:
    if not dengdeng_DIR.exists():
        return []
    paths = sorted(dengdeng_DIR.glob("*.json"))
    if not paths:
        return []
    mtime = max(path.stat().st_mtime for path in paths)
    cached = _dengdeng_CACHE.get("data")
    if cached is not None and _dengdeng_CACHE.get("mtime") == mtime:
        return cached
    dengdeng = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    _dengdeng_CACHE["mtime"] = mtime
    _dengdeng_CACHE["data"] = dengdeng
    return dengdeng


def load_usage() -> Dict:
    if not USAGE_PATH.exists():
        return {}
    return json.loads(USAGE_PATH.read_text(encoding="utf-8"))


def load_rules() -> str:
    if not RULES_PATH.exists():
        return ""
    return RULES_PATH.read_text(encoding="utf-8").strip()


KNOWLEDGE_SOURCE = "knowledge/rules.md"
_HEADING = re.compile(r"(?m)^## (?P<title>.+)$")
_CHUNK_LIMIT = 2200
_ENTRY_GROUP = 8
_dengdeng_CACHE: Dict = {"mtime": None, "data": None}
_RULE_CACHE: Dict = {"mtime": None, "chunks": None}
_GENERIC_NAMES = {
    "次数", "效果", "来源", "冷却", "使用对象", "能耗", "威力", "分类", "属性", "定义",
}
_PLATE_HINTS = (
    ("板块 A", ("克制", "抵抗", "免疫", "双重克制", "双重抵抗")),
    ("板块 B", ("能量", "聚能", "入场能量")),
    ("板块 C", ("血脉", "技能石", "血脉药", "混血")),
    ("板块 D", ("愿力", "进化之力", "光合治愈", "战斗道具", "道具")),
    ("板块 E", ("配队", "队伍", "模板", "魔力", "倾斜", "对局")),
    ("板块 G", ("技能分类", "攻击技能", "防御技能", "状态技能", "技能总表")),
    ("板块 H", ("萌化", "阶数", "中毒", "灼烧", "冻结", "增益", "减益", "状态")),
    ("板块 N", ("特性",)),
    ("板块 I", ("印记",)),
    ("板块 J", ("天气", "沙暴", "暴风雪", "雨天", "雷鸣")),
    ("板块 K", ("离场", "脱离", "迅捷", "传动", "返场", "连击")),
    ("板块 M", ("伤害", "公式", "本系加成", "种族值换算")),
    ("板块 O", ("输出", "联防", "充能", "轮转", "终端", "消强", "标签", "强化")),
    ("仍缺", ("未提供", "仍缺", "尚未写入")),
)
_TEAM_PINS = ("板块 C", "板块 D", "板块 E", "板块 O")
_TEAM_WORDS = ("配队", "组队", "队伍", "模板", "对局")


def knowledge_content_hash() -> str:
    if not RULES_PATH.exists():
        return ""
    return hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()[:16]


def _entry_names(text: str) -> List[str]:
    names = []
    seen = set()
    for line in text.splitlines():
        stripped = line.strip()
        candidates = []
        if stripped.startswith("- "):
            body = stripped[2:]
            candidates.append(body.split("｜")[0].split("：")[0].strip())
        candidates.extend(re.findall(r"【([^】]{1,20})】", line))
        for name in candidates:
            if not (1 < len(name) <= 20) or name in _GENERIC_NAMES or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def _make_chunk(section: str, text: str) -> Dict:
    body = text.strip()
    return {
        "section": section,
        "text": body,
        "names": _entry_names(body),
        "source": f"{KNOWLEDGE_SOURCE} · {section}",
    }


def _split_entries(section: str, full: str) -> List[Dict]:
    lines = full.splitlines()
    header = []
    entries = []
    current = []
    for line in lines:
        if line.startswith("- ") and current:
            entries.append("\n".join(current))
            current = [line]
        elif line.startswith("- "):
            current = [line]
        elif current:
            current.append(line)
        else:
            header.append(line)
    if current:
        entries.append("\n".join(current))
    if len(entries) < 4:
        return []
    header_text = "\n".join(header).strip()
    chunks = []
    for start in range(0, len(entries), _ENTRY_GROUP):
        part = entries[start:start + _ENTRY_GROUP]
        body = header_text + "\n\n" + "\n".join(part)
        label = section if len(entries) <= _ENTRY_GROUP else f"{section} #{start // _ENTRY_GROUP + 1}"
        chunks.append(_make_chunk(label, body))
    return chunks


def rule_chunks() -> List[Dict]:
    """按板块切开 rules.md。技能总表和特性表再按条目分组。"""
    mtime = RULES_PATH.stat().st_mtime if RULES_PATH.exists() else None
    if _RULE_CACHE["mtime"] == mtime and _RULE_CACHE["chunks"] is not None:
        return _RULE_CACHE["chunks"]
    text = load_rules()
    matches = list(_HEADING.finditer(text))
    chunks = []
    if matches and matches[0].start() > 0:
        intro = text[:matches[0].start()].strip()
        if intro:
            chunks.append(_make_chunk("导读", intro))
    elif text and not matches:
        chunks.append(_make_chunk("导读", text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group("title").strip()
        full = f"## {title}\n\n{text[start:end].strip()}".strip()
        if len(full) <= _CHUNK_LIMIT:
            chunks.append(_make_chunk(title, full))
            continue
        split = _split_entries(title, full)
        chunks.extend(split or [_make_chunk(title, full[:_CHUNK_LIMIT])])
    _RULE_CACHE["mtime"] = mtime
    _RULE_CACHE["chunks"] = chunks
    return chunks


def _section_hit(section: str, question: str) -> int:
    score = 0
    for prefix, words in _PLATE_HINTS:
        if section.startswith(prefix) and any(word in question for word in words):
            score += 12
    for part in re.split(r"[\s　]+", section):
        plain = re.split(r"[（#(]", part)[0].strip()
        if len(plain) >= 2 and plain not in ("板块",) and plain in question:
            score += 10
    return score


def _chunk_score(question: str, chunk: Dict) -> int:
    score = _section_hit(chunk["section"], question)
    for name in chunk["names"]:
        if name in question:
            score += 30
            break
    return score


def retrieve_rule_chunks(question: str, limit: int = 8) -> List[Dict]:
    """取出和问题相关的规则片段。配队问题固定带上携带、道具、对局和标签。"""
    chunks = rule_chunks()
    if not chunks or not question.strip():
        return []
    team_question = any(word in question for word in _TEAM_WORDS)
    pinned = []
    if team_question:
        for chunk in chunks:
            if any(chunk["section"].startswith(prefix) for prefix in _TEAM_PINS):
                pinned.append(chunk)
    ranked = sorted(
        (( _chunk_score(question, chunk), chunk) for chunk in chunks if chunk not in pinned),
        key=lambda item: item[0],
        reverse=True,
    )
    chosen = list(pinned)
    extra_room = max(limit - len(chosen), 0)
    for score, chunk in ranked:
        if score <= 0 or extra_room <= 0:
            break
        chosen.append(chunk)
        extra_room -= 1
    if not chosen:
        for chunk in chunks:
            if chunk["section"].startswith("板块 E") or chunk["section"].startswith("板块 O"):
                chosen.append(chunk)
    return chosen[:limit]


def template_member_names(question: str) -> List[str]:
    golds = _read_jsonl(GOLD_PATH)
    if not golds:
        return []
    selected = []
    if any(token in question for token in ("模板1", "模板 1", "模板一")):
        selected.append(0)
    if any(token in question for token in ("模板2", "模板 2", "模板二")):
        selected.append(1)
    if not selected and ("完美配队" in question or "模板" in question):
        selected = list(range(len(golds)))
    names = []
    for index in selected:
        if index >= len(golds):
            continue
        for name in golds[index].get("members") or []:
            if name not in names:
                names.append(name)
    return names


def select_window(question: str, usage: Dict) -> Dict:
    if any(word in question for word in ("上个月", "上月")):
        key = "last_month"
    else:
        key = "yesterday"
    window = usage.get(key) or {}
    window = dict(window)
    window["key"] = key
    return window


def _by_name(dengdeng: List[Dict]) -> Dict[str, Dict]:
    return {item["name"]: item for item in dengdeng}


_FORM_SPLIT = re.compile(r"[（(]")


def _name_stem(name: str) -> str:
    return _FORM_SPLIT.split(name or "", 1)[0].strip()


def _mentioned_names(text: str, dengdeng: List[Dict]) -> List[str]:
    found = []
    body = text or ""
    for item in sorted(dengdeng, key=lambda mon: len(mon["name"]), reverse=True):
        if item["name"] in body and item["name"] not in found:
            found.append(item["name"])
    stems = []
    for item in dengdeng:
        stem = _name_stem(item["name"])
        if len(stem) >= 2 and stem != item["name"]:
            stems.append((stem, item["name"]))
    for stem, full in sorted(stems, key=lambda item: len(item[0]), reverse=True):
        if full in found:
            continue
        if stem in body:
            found.append(full)
    bosses = []
    for item in dengdeng:
        boss = str(item.get("boss") or "").strip()
        if not boss:
            continue
        bosses.append((boss, _name_stem(boss), item["name"]))
    for boss, stem, full in sorted(bosses, key=lambda item: len(item[1] or item[0]), reverse=True):
        if full in found:
            continue
        if boss in body or (len(stem) >= 2 and stem in body):
            found.append(full)
    return found


def _format_stats(stats: Dict) -> str:
    labels = [
        ("hp", "HP"),
        ("attack", "攻击"),
        ("defense", "防御"),
        ("special_attack", "特攻"),
        ("special_defense", "特防"),
        ("speed", "速度"),
    ]
    return " ".join(f"{label}{stats.get(key, 0)}" for key, label in labels)


_TYPE_ORDER = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
    "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)
_SKILL_CACHE: Dict = {"mtime": None, "by_name": None, "catalog": None}
SKILL_SLOT_COUNT = 4
# 物攻与魔攻相差不足 15 时，攻击技能允许物魔混合。
STAT_BIAS_GAP = 15
# 已携带攻击技能的系别至少克制 4 种单属性，即算打击面广。与「队内输出里较高水平」是或关系。
OUTPUT_SINGLE_TYPE_MIN = 4
_BOSS_ITEM_MARKERS = ("恶魔狼", "雪影娃娃")
_ITEM_EVOLVE = "进化之力"
_ITEM_WILL = "愿力强化"
_ITEM_HEAL = "光合治愈"
_CHART_CACHE: Dict = {"mtime": None, "super": None, "resist": None}
_BLOOD_RE = re.compile(
    "(" + "|".join(_TYPE_ORDER) + ")系?血脉"
)


def _style_tags(mon: Dict) -> List[str]:
    return [part.strip() for part in re.split(r"[、，,]", str(mon.get("style") or "")) if part.strip()]


def _split_type_cell(cell: str) -> List[str]:
    text = cell.strip()
    if text in {"无", "—", "-", ""}:
        return []
    allowed = set(_TYPE_ORDER)
    return [part.strip() for part in text.split("、") if part.strip() in allowed]


def _join_types(found: set) -> str:
    ordered = [name for name in _TYPE_ORDER if name in found]
    return "、".join(ordered) if ordered else "未提供"


# 两招都在池里时只带焚烧烙印，避免占掉两格。技能表里没有名为「倾斜」的条目。
_TILT_MOVE_NAMES = ("焚烧烙印", "倾斜")
# 两招都在池里时先带飞羽。
_DISPEL_MOVE_NAMES = ("飞羽", "晒太阳")
_CHARGE_MOVE_NAME = "加大功率"


def _cost_from_parts(parts: List[str]) -> int:
    """板块 G 的「能耗 N」。读不到时记 0。"""
    for part in parts:
        matched = re.match(r"能耗\s*(\d+)", part)
        if matched:
            return int(matched.group(1))
    return 0


def _power_from_parts(parts: List[str]) -> int:
    """「威力 无」记 0，「威力 150」记 150。"""
    for part in parts:
        matched = re.match(r"威力\s*(\d+|无)", part)
        if not matched:
            continue
        return 0 if matched.group(1) == "无" else int(matched.group(1))
    return 0


def _effect_from_parts(parts: List[str]) -> str:
    """威力栏后面的效果原文。关联和图标不算效果。"""
    for index, part in enumerate(parts):
        if not part.startswith("威力"):
            continue
        if index + 1 >= len(parts):
            return ""
        nxt = parts[index + 1]
        if nxt.startswith("关联") or nxt.startswith("图标"):
            return ""
        return nxt
    return ""


def _effect_has_rider(effect: str) -> bool:
    """有附加词条。光「减伤X%，应对攻击。」没有。"""
    text = effect or ""
    matched = re.search(r"应对攻击：(.+)", text)
    if matched and re.sub(r"[。．\s]", "", matched.group(1)):
        return True
    stripped = re.sub(r"减伤\s*\d+\s*%", "", text)
    stripped = re.sub(r"应对攻击[：:][^。；]*", "", stripped)
    stripped = stripped.replace("应对攻击", "")
    stripped = re.sub(r"[，,。．、\s]", "", stripped)
    return bool(stripped)


def skill_catalog() -> Dict[str, Dict]:
    """板块 G：技能名 → category、damage、types、power、effect。按 rules.md 的 mtime 缓存。"""
    mtime = RULES_PATH.stat().st_mtime if RULES_PATH.exists() else None
    if _SKILL_CACHE["mtime"] == mtime and _SKILL_CACHE["catalog"] is not None:
        return _SKILL_CACHE["catalog"]
    catalog: Dict[str, Dict] = {}
    current_type = ""
    current_category = ""
    in_catalog = False
    type_heading = re.compile(r"^## (" + "|".join(_TYPE_ORDER) + r")系")
    category_heading = re.compile(r"^### (攻击|防御|状态)")
    for line in load_rules().splitlines():
        if line.startswith("## 板块 G"):
            in_catalog = True
            current_type = ""
            current_category = ""
            continue
        if in_catalog and line.startswith("## 板块 "):
            break
        if not in_catalog:
            continue
        type_match = type_heading.match(line)
        if type_match:
            current_type = type_match.group(1)
            current_category = ""
            continue
        category_match = category_heading.match(line)
        if category_match:
            current_category = category_match.group(1)
            continue
        if not (current_type and current_category and line.startswith("- ")):
            continue
        parts = [part.strip() for part in line[2:].split("｜")]
        name = parts[0] if parts else ""
        if not name:
            continue
        damage = parts[1] if len(parts) > 1 and parts[1] in {"物攻", "魔攻"} else ""
        power = _power_from_parts(parts)
        effect = _effect_from_parts(parts)
        cost = _cost_from_parts(parts)
        entry = catalog.setdefault(name, {
            "category": current_category,
            "damage": damage,
            "types": set(),
            "power": power,
            "effect": effect,
            "cost": cost,
        })
        if not entry["category"]:
            entry["category"] = current_category
        if damage and not entry["damage"]:
            entry["damage"] = damage
        if power and not entry.get("power"):
            entry["power"] = power
        if effect and not entry.get("effect"):
            entry["effect"] = effect
        if cost and not entry.get("cost"):
            entry["cost"] = cost
        entry["types"].add(current_type)
    catalog["聚能"] = {"category": "状态", "damage": "", "types": set(), "power": 0, "effect": "", "cost": 0}
    by_name = {name: set(entry["types"]) for name, entry in catalog.items()}
    _SKILL_CACHE["mtime"] = mtime
    _SKILL_CACHE["catalog"] = catalog
    _SKILL_CACHE["by_name"] = by_name
    return catalog


def skill_types_by_name() -> Dict[str, set]:
    """技能名称对应板块 G 里的系别。同名只应出现一次。"""
    skill_catalog()
    return _SKILL_CACHE["by_name"] or {}


def type_chart() -> Dict[str, Dict[str, set]]:
    """板块 A。super 是攻击属性克制的防守属性；resist 是该防守属性抵抗的攻击属性。"""
    mtime = RULES_PATH.stat().st_mtime if RULES_PATH.exists() else None
    if _CHART_CACHE["mtime"] == mtime and _CHART_CACHE["super"] is not None:
        return {"super": _CHART_CACHE["super"], "resist": _CHART_CACHE["resist"]}
    super_map = {name: set() for name in _TYPE_ORDER}
    resist_map = {name: set() for name in _TYPE_ORDER}
    for line in load_rules().splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in super_map:
            continue
        super_map[cells[0]] = set(_split_type_cell(cells[1]))
        resist_map[cells[0]] = set(_split_type_cell(cells[2]))
    _CHART_CACHE["mtime"] = mtime
    _CHART_CACHE["super"] = super_map
    _CHART_CACHE["resist"] = resist_map
    return {"super": super_map, "resist": resist_map}


def elf_move_types(mon: Dict, by_name: Dict[str, set] = None) -> Dict[str, set]:
    catalog = by_name if by_name is not None else skill_types_by_name()
    native = set()
    stone = set()
    for item in mon.get("native_skills") or []:
        native |= catalog.get(str(item).split("｜")[0].strip(), set())
    for item in mon.get("stone_skills") or []:
        stone |= catalog.get(str(item).split("｜")[0].strip(), set())
    blood = set()
    for item in mon.get("blood_skills") or []:
        matched = _BLOOD_RE.search(str(item))
        if matched:
            blood.add(matched.group(1))
    return {"native": native, "stone": stone, "blood": blood}


def _skill_entry(name: str) -> Dict:
    found = skill_catalog().get(name) or {}
    return {
        "category": found.get("category") or "",
        "damage": found.get("damage") or "",
        "types": set(found.get("types") or []),
        "power": int(found.get("power") or 0),
        "effect": found.get("effect") or "",
        "cost": int(found.get("cost") or 0),
    }


def _bare_skill_name(item: str) -> str:
    return str(item).split("｜")[0].strip()


def elf_skill_options(mon: Dict) -> List[Dict]:
    """该精灵三池里的可携带技能。同名优先自带，其次技能石，再次血脉。"""
    options = []
    seen = set()

    def add(name: str, source: str, blood_type: str = "") -> None:
        if not name or name in seen or name == "聚能":
            return
        meta = _skill_entry(name)
        types = set(meta["types"])
        if blood_type:
            types.add(blood_type)
        options.append({
            "name": name,
            "source": source,
            "blood_type": blood_type,
            "category": meta["category"],
            "damage": meta["damage"],
            "types": types,
            "power": meta["power"],
            "effect": meta["effect"],
            "cost": meta["cost"],
        })
        seen.add(name)

    for item in mon.get("native_skills") or []:
        add(_bare_skill_name(item), "自带")
    for item in mon.get("stone_skills") or []:
        add(_bare_skill_name(item), "技能石")
    for item in mon.get("blood_skills") or []:
        text = str(item)
        matched = _BLOOD_RE.search(text)
        add(_bare_skill_name(text), "血脉", matched.group(1) if matched else "")
    return options


def _damage_bias(mon: Dict) -> str:
    stats = mon.get("base_stats") or {}
    attack = int(stats.get("attack") or 0)
    special = int(stats.get("special_attack") or 0)
    if special >= attack + STAT_BIAS_GAP:
        return "魔攻"
    if attack >= special + STAT_BIAS_GAP:
        return "物攻"
    return ""


def _matches_boss_family(name: str) -> bool:
    return any(marker in (name or "") for marker in _BOSS_ITEM_MARKERS)


def _can_boss(mon: Dict) -> bool:
    return str((mon or {}).get("can_boss") or "").strip() == "是"


def _wants_boss_item(question: str) -> bool:
    text = question or ""
    return any(word in text for word in ("进化之力", "首领化", "首领血脉"))


def _can_boss_names(members: List[Dict], catalog: Dict[str, Dict] = None) -> List[str]:
    catalog = catalog or _by_name(load_dengdeng())
    names = []
    for member in members:
        name = member["name"]
        if name not in names and _can_boss(catalog.get(name) or {}):
            names.append(name)
    return names


def _must_evolve_names(members: List[Dict]) -> List[str]:
    return [member["name"] for member in members if _matches_boss_family(member["name"])]


def _wants_heal_item(question: str) -> bool:
    return "光合治愈" in (question or "")


def _wants_will_item(question: str) -> bool:
    return "愿力强化" in (question or "")


def _evolve_use_target(boss_names: List[str], forced: List[str], question: str) -> str:
    named = [name for name in _mentioned_names(question, load_dengdeng()) if name in boss_names]
    if named:
        return named[0]
    if forced:
        return forced[0]
    return boss_names[0] if boss_names else ""


def _count_roles(members: List[Dict]) -> Dict[str, int]:
    return {
        "输出": sum(1 for member in members if "输出" in member.get("tags") or []),
        "联防": sum(1 for member in members if "联防" in member.get("tags") or []),
    }


def _skill_phrase(skill: Dict) -> str:
    if skill.get("source") == "技能石":
        return f"{skill['name']}（技能石，消耗【技能石】）"
    if skill.get("source") == "血脉":
        blood = skill.get("blood_type") or "未提供"
        return f"{skill['name']}（{blood}血脉，消耗【血脉药】）"
    return f"{skill['name']}（自带）"


def _format_option(skill: Dict) -> str:
    damage = f"｜{skill['damage']}" if skill.get("damage") else ""
    origin = skill["source"] if skill.get("source") != "血脉" else f"{skill.get('blood_type') or '未提供'}血脉"
    return f"{skill['name']}｜{origin}｜{skill.get('category') or '未提供'}{damage}｜系别：{_join_types(skill.get('types') or set())}"


def recommend_skills(mon: Dict, low: int = 6, high: int = 6) -> List[Dict]:
    """压缩名录用，顺序与 4 栏补全相同，只是最多列 6 个。"""
    return _priority_picks(mon, high, True, type_chart())


def meta_snippet(question: str = "") -> str:
    """使用率窗口没有精灵或队伍时不提供任何使用率文本。"""
    usage = load_usage()
    windows = [usage.get("yesterday") or {}, usage.get("last_month") or {}]
    if not any((window.get("dengdeng") or window.get("teams")) for window in windows):
        return ""
    window = select_window(question, usage)
    lines = [f"时间窗口：{window.get('label') or '未提供'}"]
    for item in window.get("dengdeng") or []:
        lines.append(f"- {item.get('name')} {float(item.get('usage') or 0) * 100:.1f}%")
    for team in window.get("teams") or []:
        members = " / ".join(team.get("members") or [])
        lines.append(f"- {members} {float(team.get('usage') or 0) * 100:.1f}%")
    return "\n".join(lines)


def _plate_excerpt(prefix: str) -> str:
    for chunk in rule_chunks():
        if chunk["section"].startswith(prefix):
            return chunk["text"]
    return ""


def short_chart_text() -> str:
    """板块 A 的短克制表。每系一行，只写克制谁。"""
    chart = type_chart()
    lines = ["板块 A 短表。下面每一行是该攻击属性克制的防守属性。倍率 2 或 3 才算克制。"]
    for name in _TYPE_ORDER:
        targets = [item for item in _TYPE_ORDER if item in chart["super"].get(name, ())]
        lines.append(f"- {name} 克制 {'、'.join(targets) if targets else '无'}")
    return "\n".join(lines)


def _item_excerpt() -> str:
    return "\n".join([
        "板块 D　战斗道具",
        "道具只有三种：【愿力强化】、【进化之力】、【光合治愈】。一局对决只能携带并使用其中 1 种。",
        "【愿力强化】：使用对象是系别血脉的精灵。首领血脉不能使用。",
        "【进化之力】：队内有可以首领化的精灵就可以选用。恶魔狼、雪影娃娃在队时必须携带。使用对象是首领血脉。一局只能对一只使用，但多只都可以写成首领血脉，方便临场选择。",
        "【光合治愈】：使用对象是任意血脉的精灵。回复生命。一局只能使用 1 次。",
        "技能、血脉和道具由程序补全。模型只写 6 个完整名字。",
    ])


def _pool_move_names(mon: Dict) -> set:
    return {skill["name"] for skill in elf_skill_options(mon)}


def can_learn_tilt(mon: Dict) -> bool:
    """JSON 有倾斜标签，且技能池里有「焚烧烙印」或「倾斜」。"""
    return "倾斜" in _style_tags(mon) and bool(_pool_move_names(mon) & set(_TILT_MOVE_NAMES))


def roster_text(dengdeng: List[Dict] = None) -> str:
    """给模型看的短名录：每只一行，不含推荐技能和技能池。"""
    dengdeng = dengdeng if dengdeng is not None else load_dengdeng()
    lines = [
        "已记录精灵。只从下面的完整名字里选 6 只。不要写技能。",
        "能当有效倾斜的精灵，标记为「可倾斜」。消强能学晒太阳或飞羽的标「可消强」。充能能学加大功率的标「可充能」。",
    ]
    for mon in dengdeng:
        tags = _style_tags(mon)
        types = "、".join(mon.get("types") or []) or "未提供"
        marks = []
        if can_learn_tilt(mon):
            marks.append("可倾斜")
        names = _pool_move_names(mon)
        if "消强" in tags and names & set(_DISPEL_MOVE_NAMES):
            marks.append("可消强")
        if "充能" in tags and _CHARGE_MOVE_NAME in names:
            marks.append("可充能")
        extra = f"｜{'、'.join(marks)}" if marks else ""
        lines.append(
            f"- {mon['name']}｜属性：{types}｜标签：{'、'.join(tags) or '未提供'}{extra}"
        )
    return "\n".join(lines)


def _full_pool_text(mon: Dict) -> str:
    lines = [f"### {mon['name']} 的完整三池"]
    for skill in elf_skill_options(mon):
        lines.append(f"- {_format_option(skill)}")
    return "\n".join(lines)


def composer_snippets(question: str) -> List[Dict]:
    """配队检索：只给模型短名录。技能、克制表和三池由程序补全，不进提示词。"""
    dengdeng = load_dengdeng()
    if not dengdeng:
        return []
    named = _mentioned_names(question, dengdeng)[:6]
    note = "用户点名的精灵必须入队：" + "、".join(named) if named else "没有点名精灵。"
    return [{
        "id": 1,
        "source": "knowledge/dengdeng/*.json · 短名录",
        "page": "",
        "text": roster_text(dengdeng) + "\n" + note,
    }]


def propose_team_line(question: str) -> str:
    """模型超时或凑不齐 6 只时，按标签选出 6 个完整名字。"""
    dengdeng = load_dengdeng()
    if len(dengdeng) < 6:
        return ""
    catalog = _by_name(dengdeng)
    named = [name for name in _mentioned_names(question, dengdeng) if name in catalog]
    eligible = [
        mon for mon in dengdeng
        if "输出" in _style_tags(mon) or "联防" in _style_tags(mon)
    ]
    picked: List[str] = []
    for name in named:
        if name not in picked:
            picked.append(name)

    def output_count(names: List[str]) -> int:
        return sum(1 for name in names if "输出" in _style_tags(catalog[name]))

    def has_tilt(names: List[str]) -> bool:
        return any(can_learn_tilt(catalog[name]) for name in names)

    if not has_tilt(picked):
        tilt = next((mon for mon in eligible if can_learn_tilt(mon) and mon["name"] not in picked), None)
        if tilt:
            if len(picked) >= 6:
                for index in range(len(picked) - 1, -1, -1):
                    if picked[index] not in named:
                        picked[index] = tilt["name"]
                        break
            else:
                picked.append(tilt["name"])

    defense_bias = any(word in (question or "") for word in ("防守", "联防", "防御", "偏守", "肉"))
    output_bias = any(word in (question or "") for word in ("输出", "进攻", "打手", "偏攻"))

    def score(mon: Dict) -> int:
        tags = _style_tags(mon)
        names = _pool_move_names(mon)
        value = 0
        if defense_bias and "联防" in tags:
            value += 4
        if output_bias and "输出" in tags:
            value += 4
        if "消强" in tags and names & set(_DISPEL_MOVE_NAMES):
            value += 1
        if "充能" in tags and _CHARGE_MOVE_NAME in names:
            value += 1
        if can_learn_tilt(mon):
            value += 2
        return value

    rest = [mon for mon in eligible if mon["name"] not in picked]
    rest.sort(key=score, reverse=True)
    for mon in rest:
        if len(picked) >= 6:
            break
        tags = _style_tags(mon)
        trial = picked + [mon["name"]]
        if output_count(trial) > 3:
            continue
        if "输出" not in tags and "联防" not in tags:
            continue
        picked.append(mon["name"])
    if output_count(picked) < 1:
        attacker = next(
            (mon for mon in eligible if "输出" in _style_tags(mon) and mon["name"] not in picked),
            None,
        )
        if attacker:
            if len(picked) >= 6:
                for index in range(len(picked) - 1, -1, -1):
                    if picked[index] not in named and not can_learn_tilt(catalog[picked[index]]):
                        picked[index] = attacker["name"]
                        break
            else:
                picked.append(attacker["name"])
    if len(picked) < 6:
        for mon in dengdeng:
            if mon["name"] in picked:
                continue
            picked.append(mon["name"])
            if len(picked) >= 6:
                break
    names = picked[:6]
    if len(names) != 6:
        return ""
    reason = "程序按点名、有效倾斜和攻守标签选出六人。"
    return f"队伍配置为{'、'.join(names)}\n选取的理由是{reason}"


def _multiplier(attack: str, defender_types: List[str], chart: Dict) -> float:
    supers = 0
    resists = 0
    for defender in defender_types:
        if defender in chart["super"].get(attack, ()):
            supers += 1
        if attack in chart["resist"].get(defender, ()):
            resists += 1
    if len(defender_types) >= 2:
        if supers >= 2:
            return 3
        if resists >= 2 and supers == 0:
            return 0.25
        if supers == 1 and resists >= 1:
            return 1
        if supers == 1:
            return 2
        if resists >= 1:
            return 0.5
        return 1
    if supers and not resists:
        return 2
    if resists and not supers:
        return 0.5
    return 1


def _beats(attack: str, defender_types: List[str], chart: Dict) -> bool:
    return bool(defender_types) and _multiplier(attack, defender_types, chart) >= 2


def type_combinations() -> List[tuple]:
    combos = [(name,) for name in _TYPE_ORDER]
    for index, left in enumerate(_TYPE_ORDER):
        for right in _TYPE_ORDER[index + 1:]:
            combos.append((left, right))
    return combos


def coverage_count(attack_types: set, chart: Dict = None) -> int:
    chart = chart or type_chart()
    attacks = [name for name in _TYPE_ORDER if name in attack_types]
    covered = 0
    for combo in type_combinations():
        if any(_beats(attack, list(combo), chart) for attack in attacks):
            covered += 1
    return covered


def _profile_text(mon: Dict) -> str:
    record = str(mon.get("record") or "").strip()
    if record:
        return record
    return (
        f"名字：{mon['name']}\n"
        f"属性：{'、'.join(mon.get('types') or [])}\n"
        f"特性：{'、'.join(mon.get('abilities') or [])}\n"
        f"种族值：{_format_stats(mon.get('base_stats') or {})}\n"
        f"个体值：{_format_stats(mon.get('ivs') or {})}\n"
        f"技能池：{'、'.join(mon.get('moves') or [])}\n"
        f"战斗风格：{mon.get('style') or ''}"
    )


def build_team_snippets(question: str) -> List[Dict]:
    """检索员的结构化结果：点名的精灵、相关规则板块、使用率。"""
    dengdeng = load_dengdeng()
    if not dengdeng:
        return []
    usage = load_usage()
    window = select_window(question, usage)
    named = _mentioned_names(question, dengdeng)
    ranked = [item["name"] for item in window.get("dengdeng") or []]
    team_members = []
    for team in (window.get("teams") or [])[:2]:
        team_members.extend(team.get("members") or [])

    ordered = []
    for name in named + template_member_names(question) + team_members + ranked:
        if name not in ordered and name in _by_name(dengdeng):
            ordered.append(name)
    ordered = ordered[:12]

    usage_lines = [
        f"时间窗口：{window.get('label') or '未提供'}（{window.get('date') or '未标注日期'}）",
    ]
    usage_dengdeng = window.get("dengdeng") or []
    usage_teams = window.get("teams") or []
    if not usage_dengdeng and not usage_teams:
        usage_lines.append("使用率：未提供。")
    else:
        usage_lines.append("精灵使用率：")
        for item in usage_dengdeng:
            usage_lines.append(f"- {item['name']} {float(item['usage']) * 100:.1f}%")
        usage_lines.append("队伍使用率：")
        for team in usage_teams:
            members = " / ".join(team.get("members") or [])
            usage_lines.append(f"- {members} {float(team.get('usage') or 0) * 100:.1f}%")

    snippets = []
    for chunk in retrieve_rule_chunks(question):
        snippets.append({
            "id": len(snippets) + 1,
            "source": chunk["source"],
            "page": "",
            "text": chunk["text"],
        })
    catalog = _by_name(dengdeng)
    for name in ordered:
        snippets.append({
            "id": len(snippets) + 1,
            "source": f"knowledge/dengdeng/{name}.json",
            "page": "",
            "text": _profile_text(catalog[name]),
        })
    snippets.append({
        "id": len(snippets) + 1,
        "source": "knowledge/usage.json",
        "page": window.get("key") or "",
        "text": "\n".join(usage_lines),
    })
    return snippets


def _team_section(draft: str) -> str:
    start = draft.find("【队伍】")
    if start < 0:
        return draft
    end = draft.find("【理由】", start)
    return draft[start:end if end > start else None]


def validate_team_draft(draft: str, question: str) -> List[str]:
    """核对员里不靠模型也能判定的部分。"""
    dengdeng = load_dengdeng()
    if not dengdeng:
        return []
    catalog = _by_name(dengdeng)
    section = _team_section(draft)
    members = _mentioned_names(section, dengdeng)
    issues = []
    if "【队伍】" not in draft:
        issues.append("缺少【队伍】段落")
    expected = 6 if len(dengdeng) >= 6 else len(dengdeng)
    if len(members) != expected:
        issues.append(f"队伍应有 {expected} 只知识库中的精灵，当前识别到 {len(members)} 只：{'、'.join(members) or '无'}")
    for name in _mentioned_names(question, dengdeng):
        if name not in members:
            issues.append(f"用户点名的主力 {name} 不在队伍里")

    global_moves = {move for mon in dengdeng for move in mon.get("moves") or []}
    for line in section.splitlines():
        names = _mentioned_names(line, dengdeng)
        if len(names) != 1:
            continue
        mon = catalog[names[0]]
        own_moves = set(mon.get("moves") or [])
        for move in sorted(global_moves, key=len, reverse=True):
            if move in line and move not in own_moves:
                issues.append(f"{names[0]} 的技能池里没有「{move}」")
    return issues


def config_members(answer: str, dengdeng: List[Dict] = None) -> List[str]:
    """只从「选取的理由」之前识别精灵。优先读六行配置。"""
    parsed = parse_team_config(answer, dengdeng)
    names = [member["name"] for member in parsed.get("members") or [] if member.get("name")]
    if names:
        return names
    dengdeng = dengdeng if dengdeng is not None else load_dengdeng()
    text = answer or ""
    if "选取的理由" in text:
        text = text.split("选取的理由", 1)[0]
    return _mentioned_names(text, dengdeng)


_SKILL_TOKEN = re.compile(r"([^、]+?)（([^）]*)）")


def _parse_skill_token(token: str, options: List[Dict]) -> Dict:
    text = token.strip()
    matched = re.match(r"^(?P<name>.+?)（(?P<meta>[^）]*)）$", text)
    name = matched.group("name").strip() if matched else text
    meta = matched.group("meta") if matched else ""
    source = ""
    blood_type = ""
    if "技能石" in meta:
        source = "技能石"
    elif "血脉" in meta:
        source = "血脉"
        found = _BLOOD_RE.search(meta)
        blood_type = found.group(1) if found else ""
    elif "自带" in meta:
        source = "自带"
    pool = [item for item in options if item["name"] == name]
    chosen = None
    if source:
        chosen = next((item for item in pool if item["source"] == source), None)
    if chosen is None and pool and not source:
        chosen = pool[0]
    if chosen is None:
        meta_entry = _skill_entry(name)
        return {
            "name": name,
            "source": source,
            "blood_type": blood_type,
            "category": meta_entry["category"],
            "damage": meta_entry["damage"],
            "types": set(meta_entry["types"]) | ({blood_type} if blood_type else set()),
            "in_pool": False,
            "raw": text,
        }
    copied = dict(chosen)
    copied["types"] = set(chosen["types"])
    copied["in_pool"] = True
    copied["raw"] = text
    if source == "血脉" and blood_type and copied.get("blood_type") not in {blood_type, ""}:
        copied["blood_type"] = blood_type
        copied["in_pool"] = False
    return copied


def _member_from_line(line: str, catalog: Dict[str, Dict]) -> Dict:
    body = line.strip()
    if body.startswith("- "):
        body = body[2:].strip()
    name = body.split("｜", 1)[0].strip()
    mon = catalog.get(name)
    tags = _style_tags(mon) if mon else []
    blood = ""
    skills = []
    blood_match = re.search(r"血脉：([^｜]+)", body)
    if blood_match:
        blood = blood_match.group(1).strip()
    skill_match = re.search(r"技能：(.*)$", body)
    options = elf_skill_options(mon) if mon else []
    if skill_match and skill_match.group(1).strip():
        for token in skill_match.group(1).split("、"):
            token = token.strip()
            if token:
                skills.append(_parse_skill_token(token, options))
    return {"name": name if mon else "", "raw_name": name, "tags": tags, "blood": blood, "skills": skills}


def parse_team_config(answer: str, dengdeng: List[Dict] = None) -> Dict:
    """解析「队伍配置为」六行、战斗道具和理由。解析不到六行时按名字回退。"""
    dengdeng = dengdeng if dengdeng is not None else load_dengdeng()
    catalog = _by_name(dengdeng)
    text = answer or ""
    reason = ""
    if "选取的理由" in text:
        head, tail = text.split("选取的理由", 1)
        reason = tail.lstrip("是").strip()
    else:
        head = text
    item = ""
    item_match = re.search(r"战斗道具：【([^】]+)】", head)
    if item_match:
        item = item_match.group(1).strip()
        head = head[:item_match.start()]
    members = []
    for line in head.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        member = _member_from_line(stripped, catalog)
        if member["name"]:
            members.append(member)
    if len(members) < 6:
        line_names = _names_from_config_line(head, dengdeng)
        seen = {member["name"] for member in members}
        extra = line_names or _mentioned_names(head, dengdeng)
        for name in extra:
            if name in seen:
                continue
            mon = catalog[name]
            members.append({"name": name, "raw_name": name, "tags": _style_tags(mon), "blood": "", "skills": []})
            seen.add(name)
            if line_names and len(members) >= 6:
                break
    return {"members": members, "item": item, "reason": reason}


def _names_from_config_line(head: str, dengdeng: List[Dict]) -> List[str]:
    """「队伍配置为名字、名字…」这一行。带技能栏的旧格式返回空，改走六行解析。"""
    match = re.search(r"队伍配置为\s*([^\n]+)", head or "")
    if not match:
        return []
    chunk = match.group(1)
    if "｜" in chunk:
        return []
    chunk = re.split(r"六只精灵", chunk)[0]
    names = []
    for part in re.split(r"[、，,]", chunk):
        part = part.strip().strip("。．. ")
        if not part:
            continue
        catalog = _by_name(dengdeng)
        if part in catalog:
            if part not in names:
                names.append(part)
            continue
        for name in _mentioned_names(part, dengdeng):
            if name not in names:
                names.append(name)
    return names


def roster_incomplete(answer: str, question: str = "") -> bool:
    """补全技能之前：不是正好 6 只，或用户点名的精灵不在队里。"""
    parsed = parse_team_config(answer)
    names = []
    for member in parsed.get("members") or []:
        name = member.get("name") or ""
        if name and name not in names:
            names.append(name)
    if len(names) != 6:
        return True
    for ace in _mentioned_names(question, load_dengdeng()):
        if ace not in names:
            return True
    return False


def carried_skill_types(members: List[Dict]) -> set:
    """只统计已携带技能的系别，不并入未携带的自带或技能石。"""
    found = set()
    for member in members:
        for skill in (member.get("skills") or [])[:SKILL_SLOT_COUNT]:
            found |= set(skill.get("types") or [])
    return found


def _attack_types_for_team(members, catalog: Dict[str, Dict] = None, reason: str = "") -> set:
    """兼容旧调用。字符串按配置解析；列表只读已携带技能。"""
    if isinstance(members, str):
        parsed = parse_team_config(members)
        return carried_skill_types(parsed.get("members") or [])
    if members and isinstance(members[0], str):
        return set()
    return carried_skill_types(members)


def _attack_skills(skills: List[Dict]) -> List[Dict]:
    return [skill for skill in skills if skill.get("category") == "攻击"]


def _single_type_coverage(skills: List[Dict], chart: Dict) -> int:
    types = set()
    for skill in _attack_skills(skills):
        types |= set(skill.get("types") or [])
    return sum(1 for name in _TYPE_ORDER if any(_beats(attack, [name], chart) for attack in types))


def _threat_types(mon: Dict, chart: Dict) -> List[str]:
    defender = mon.get("types") or []
    return [name for name in _TYPE_ORDER if _beats(name, defender, chart)]


def _counters_threat(skills: List[Dict], threats: List[str], chart: Dict) -> bool:
    if not threats:
        return True
    for skill in _attack_skills(skills):
        for attack in skill.get("types") or []:
            if any(_beats(attack, [threat], chart) for threat in threats):
                return True
    return False


def _output_spread_ok(skills: List[Dict], mon: Dict, chart: Dict, peer_coverages: List[int] = None) -> bool:
    covered = _single_type_coverage(skills, chart)
    peers = peer_coverages or []
    median = sorted(peers)[len(peers) // 2] if peers else 0
    broad = covered >= OUTPUT_SINGLE_TYPE_MIN or (peers and covered >= median and covered > 0)
    return broad or _counters_threat(skills, _threat_types(mon, chart), chart)


def _damage_direction_ok(skills: List[Dict], mon: Dict) -> bool:
    bias = _damage_bias(mon)
    attacks = [skill for skill in _attack_skills(skills) if skill.get("damage") in {"物攻", "魔攻"}]
    if not bias or len(attacks) < 2:
        return True
    wrong = "物攻" if bias == "魔攻" else "魔攻"
    return any(skill["damage"] != wrong for skill in attacks)


def _learnable_skills(mon: Dict, allow_blood: bool) -> List[Dict]:
    pool = elf_skill_options(mon)
    if allow_blood:
        return pool
    return [skill for skill in pool if skill.get("source") != "血脉"]


def _open_pool(mon: Dict, picked: List[Dict], allow_blood: bool) -> List[Dict]:
    picked_names = {skill["name"] for skill in picked}
    blood_used = any(skill.get("source") == "血脉" for skill in picked)
    opened = []
    for skill in _learnable_skills(mon, allow_blood):
        if skill["name"] in picked_names or skill["name"] == "聚能":
            continue
        if skill["source"] == "血脉" and blood_used:
            continue
        opened.append(skill)
    return opened


def _attack_need(mon: Dict, allow_blood: bool) -> int:
    """池里没有攻击则不要求。输出要 2 个，其余有攻击可学时要 1 个。"""
    pool = _learnable_skills(mon, allow_blood)
    if not any(skill["category"] == "攻击" for skill in pool):
        return 0
    if "输出" in _style_tags(mon):
        return 2
    return 1


def _attack_sort_key(skill: Dict, mon: Dict, held: set) -> tuple:
    """威力优先，其次本系，再是物攻/魔攻倾向，最后是新覆盖的系别。"""
    types = set(skill.get("types") or [])
    stab = 1 if types & set(mon.get("types") or []) else 0
    bias = _damage_bias(mon)
    direction = 1 if not bias or skill.get("damage") in {bias, ""} else 0
    return (int(skill.get("power") or 0), stab, direction, len(types - held))


def _best_attack(pool: List[Dict], mon: Dict, picked: List[Dict]) -> Dict:
    attacks = [skill for skill in pool if skill["category"] == "攻击"]
    if not attacks:
        return {}
    held = set()
    for skill in _attack_skills(picked):
        held |= set(skill.get("types") or [])
    return max(attacks, key=lambda skill: _attack_sort_key(skill, mon, held))


def _best_defense(pool: List[Dict]) -> Dict:
    defenses = [skill for skill in pool if skill["category"] == "防御"]
    if not defenses:
        return {}
    return max(
        defenses,
        key=lambda skill: (
            1 if _effect_has_rider(skill.get("effect") or "") else 0,
            0 if skill["name"] == "防御" else 1,
        ),
    )


def _named_first(pool: List[Dict], names: tuple) -> Dict:
    found = [skill for skill in pool if skill["name"] in names]
    if not found:
        return {}
    found.sort(key=lambda skill: names.index(skill["name"]))
    return found[0]


def _copy_skill(skill: Dict) -> Dict:
    copied = dict(skill)
    copied["types"] = set(skill.get("types") or [])
    copied["in_pool"] = True
    copied["power"] = int(skill.get("power") or 0)
    copied["effect"] = skill.get("effect") or ""
    copied["raw"] = _skill_phrase(copied)
    return copied


def _skill_is_protected(mon: Dict, picked: List[Dict], index: int, allow_blood: bool) -> bool:
    """唯一攻击、唯一防御、唯一倾斜技、唯一消强/充能特征技不能被挤掉。"""
    skill = picked[index]
    name = skill.get("name") or ""
    tags = _style_tags(mon)
    trial = picked[:index] + picked[index + 1:]
    if name in _TILT_MOVE_NAMES and sum(1 for item in picked if item.get("name") in _TILT_MOVE_NAMES) <= 1:
        return True
    if name in _DISPEL_MOVE_NAMES and "消强" in tags and sum(1 for item in picked if item.get("name") in _DISPEL_MOVE_NAMES) <= 1:
        return True
    if name == _CHARGE_MOVE_NAME and "充能" in tags and sum(1 for item in picked if item.get("name") == _CHARGE_MOVE_NAME) <= 1:
        return True
    if skill.get("category") == "防御" and "联防" in tags and not any(item.get("category") == "防御" for item in trial):
        return True
    need = _attack_need(mon, allow_blood)
    if skill.get("category") == "攻击" and len(_attack_skills(trial)) < need:
        return True
    return False


def _replace_index(mon: Dict, picked: List[Dict], allow_blood: bool):
    """优先丢掉无关状态，其次丢掉威力最低的多余攻击。"""
    candidates = [
        index for index in range(len(picked))
        if not _skill_is_protected(mon, picked, index, allow_blood)
    ]
    if not candidates:
        return None

    def rank(index: int) -> tuple:
        skill = picked[index]
        name = skill.get("name") or ""
        if skill.get("category") == "状态" and name not in _TILT_MOVE_NAMES + _DISPEL_MOVE_NAMES and name != _CHARGE_MOVE_NAME:
            return (0, 0)
        if skill.get("category") == "攻击":
            return (1, int(skill.get("power") or 0))
        if name == "防御":
            return (2, 0)
        return (3, 0)

    return min(candidates, key=rank)


def _is_unmet_hard(mon: Dict, picked: List[Dict], skill: Dict, allow_blood: bool) -> bool:
    tags = _style_tags(mon)
    if skill.get("name") in _TILT_MOVE_NAMES and "倾斜" in tags:
        return not any(item.get("name") in _TILT_MOVE_NAMES for item in picked)
    if skill.get("category") == "防御" and "联防" in tags:
        return not any(item.get("category") == "防御" for item in picked)
    if skill.get("category") == "攻击" and len(_attack_skills(picked)) < _attack_need(mon, allow_blood):
        return True
    if skill.get("name") in _DISPEL_MOVE_NAMES and "消强" in tags:
        return not any(item.get("name") in _DISPEL_MOVE_NAMES for item in picked)
    if skill.get("name") == _CHARGE_MOVE_NAME and "充能" in tags:
        return not any(item.get("name") == _CHARGE_MOVE_NAME for item in picked)
    return False


def _next_skill(mon: Dict, picked: List[Dict], allow_blood: bool, chart: Dict) -> Dict:
    """A 倾斜技、B 联防防御、C 攻击配额、D 消强、E 充能、F 高威力本系攻击。"""
    tags = _style_tags(mon)
    pool = _open_pool(mon, picked, allow_blood)
    if not pool:
        return {}
    if "倾斜" in tags and not any(skill.get("name") in _TILT_MOVE_NAMES for skill in picked):
        tilt = _named_first(pool, _TILT_MOVE_NAMES)
        if tilt:
            return tilt
    if "联防" in tags and not any(skill.get("category") == "防御" for skill in picked):
        defense = _best_defense(pool)
        if not defense:
            return {}
        return defense
    if len(_attack_skills(picked)) < _attack_need(mon, allow_blood):
        attack = _best_attack(pool, mon, picked)
        if attack:
            return attack
    if "消强" in tags and not any(skill.get("name") in _DISPEL_MOVE_NAMES for skill in picked):
        dispel = _named_first(pool, _DISPEL_MOVE_NAMES)
        if dispel:
            return dispel
    if "充能" in tags and not any(skill.get("name") == _CHARGE_MOVE_NAME for skill in picked):
        charge = _named_first(pool, (_CHARGE_MOVE_NAME,))
        if charge:
            return charge
    attack = _best_attack(pool, mon, picked)
    if attack:
        return attack
    return max(
        pool,
        key=lambda skill: (
            1 if skill.get("category") == "防御" and _effect_has_rider(skill.get("effect") or "") else 0,
            1 if skill.get("source") == "自带" else 0,
        ),
    )


def _priority_picks(mon: Dict, limit: int, allow_blood: bool, chart: Dict) -> List[Dict]:
    picked = []
    while len(picked) < limit:
        nxt = _next_skill(mon, picked, allow_blood, chart)
        if not nxt:
            break
        picked.append(_copy_skill(nxt))
    return picked


def _enforce_hard_skills(mon: Dict, picked: List[Dict], allow_blood: bool, chart: Dict) -> None:
    """4 栏已满时，用可丢技能换上还没满足的硬需求。"""
    for _ in range(SKILL_SLOT_COUNT):
        nxt = _next_skill(mon, picked, allow_blood, chart)
        if not nxt or not _is_unmet_hard(mon, picked, nxt, allow_blood):
            return
        if any(skill.get("name") == nxt.get("name") for skill in picked):
            return
        if len(picked) < SKILL_SLOT_COUNT:
            picked.append(_copy_skill(nxt))
            continue
        index = _replace_index(mon, picked, allow_blood)
        if index is None:
            return
        picked[index] = _copy_skill(nxt)


def _nudge_attack_direction(mon: Dict, picked: List[Dict], allow_blood: bool) -> None:
    """攻击不能整栏都逆着物攻/魔攻倾向。只替换一条逆倾向攻击。"""
    if _damage_direction_ok(picked, mon):
        return
    bias = _damage_bias(mon)
    good = [
        skill for skill in _open_pool(mon, picked, allow_blood)
        if skill["category"] == "攻击" and (not bias or skill.get("damage") in {bias, ""})
    ]
    if not good:
        return
    best = max(good, key=lambda skill: _attack_sort_key(skill, mon, set()))
    wrong = [
        index for index, skill in enumerate(picked)
        if skill.get("category") == "攻击" and bias and skill.get("damage") not in {bias, ""}
    ]
    if not wrong:
        return
    index = min(wrong, key=lambda item: int(picked[item].get("power") or 0))
    if picked[index].get("name") in _TILT_MOVE_NAMES:
        return
    picked[index] = _copy_skill(best)


def fill_member_skills(mon: Dict, requested: List[Dict], allow_blood: bool = True, chart: Dict = None) -> List[Dict]:
    """丢掉非法技能后贪心补到 4 个。没有防御技能可学时不硬塞。"""
    chart = chart or type_chart()
    options = elf_skill_options(mon)
    by_name = {}
    for skill in options:
        by_name.setdefault(skill["name"], []).append(skill)
    picked = []
    for skill in requested or []:
        if skill.get("name") == "聚能" or not skill.get("in_pool", True):
            continue
        matches = by_name.get(skill["name"]) or []
        chosen = next((item for item in matches if item["source"] == skill.get("source")), None)
        if chosen is None:
            continue
        if chosen["source"] == "血脉" and (not allow_blood or any(item["source"] == "血脉" for item in picked)):
            continue
        if any(item["name"] == chosen["name"] for item in picked):
            continue
        copied = dict(chosen)
        copied["types"] = set(chosen["types"])
        copied["in_pool"] = True
        copied["raw"] = _skill_phrase(copied)
        picked.append(copied)
        if len(picked) == SKILL_SLOT_COUNT:
            break
    while len(picked) < SKILL_SLOT_COUNT:
        nxt = _next_skill(mon, picked, allow_blood, chart)
        if not nxt:
            break
        picked.append(_copy_skill(nxt))
    _enforce_hard_skills(mon, picked, allow_blood, chart)
    _nudge_attack_direction(mon, picked, allow_blood)
    return picked


def _blood_label(skills: List[Dict], forced: str = "") -> str:
    if forced:
        return forced
    bloods = [skill for skill in skills if skill.get("source") == "血脉"]
    if len(bloods) == 1 and bloods[0].get("blood_type"):
        return f"{bloods[0]['blood_type']}血脉"
    return "初始血脉"


def _item_sentence(
    item: str,
    priority: str,
    target: str = "",
    targets: List[str] = None,
    forced: bool = False,
) -> str:
    if item == _ITEM_EVOLVE or priority == "P0":
        bosses = "、".join(targets or ([target] if target else [])) or "可首领化精灵"
        who = target or (targets[0] if targets else "其中一只")
        if forced:
            head = "队内有恶魔狼或雪影娃娃，必须携带【进化之力】。"
        else:
            head = f"队内有可首领化精灵（{bosses}），所以携带【进化之力】。"
        use = f"一局只能对一只使用，对局时优先用在{who}。"
        if len(targets or []) > 1:
            use += f"{bosses}都写成首领血脉，方便临场选择。"
        else:
            use += f"{who}写成首领血脉。"
        return head + use
    if priority == "P1":
        who = target or "一只输出精灵"
        return f"输出只数多于联防只数，所以全队携带【愿力强化】，使用对象是{who}。"
    return "联防只数不少于输出只数，所以全队携带【光合治愈】。"


def choose_battle_item(members: List[Dict], question: str = "") -> Dict:
    """恶魔狼/雪影娃娃必须进化之力；其余只要有可首领化精灵就可以选。"""
    catalog = _by_name(load_dengdeng())
    boss_names = _can_boss_names(members, catalog)
    forced = _must_evolve_names(members)
    take_evolve = False
    if forced:
        take_evolve = True
    elif _wants_boss_item(question) and boss_names:
        take_evolve = True
    elif boss_names and not _wants_heal_item(question) and not _wants_will_item(question):
        take_evolve = True
    if take_evolve and boss_names:
        target = _evolve_use_target(boss_names, forced, question)
        return {
            "item": _ITEM_EVOLVE,
            "priority": "P0",
            "target": target,
            "targets": boss_names,
            "forced": bool(forced),
        }
    roles = _count_roles(members)
    if _wants_will_item(question) or (roles["输出"] > roles["联防"] and not _wants_heal_item(question)):
        target = next((member["name"] for member in members if "输出" in member.get("tags") or []), "")
        return {"item": _ITEM_WILL, "priority": "P1", "target": target, "targets": [], "forced": False}
    return {"item": _ITEM_HEAL, "priority": "P2", "target": "", "targets": [], "forced": False}


def _best_blood_skill(mon: Dict, picked: List[Dict], chart: Dict) -> Dict:
    held = carried_skill_types([{"skills": picked}])
    best = {}
    best_gain = -1
    for skill in elf_skill_options(mon):
        if skill["source"] != "血脉" or skill["name"] in {item["name"] for item in picked}:
            continue
        if skill["category"] != "攻击":
            continue
        gain = len(set(skill["types"]) - held)
        bias = _damage_bias(mon)
        if bias and skill["damage"] not in {bias, ""}:
            gain -= 1
        if gain > best_gain:
            best = skill
            best_gain = gain
    return best


def _replace_for_blood(mon: Dict, picked: List[Dict], blood: Dict) -> List[Dict]:
    """换上血脉攻击时，不挤掉倾斜技、唯一防御和攻击配额。"""
    if len(picked) < SKILL_SLOT_COUNT:
        return picked + [blood]
    index = _replace_index(mon, picked, True)
    if index is None:
        return picked
    if picked[index].get("name") in _TILT_MOVE_NAMES:
        return picked
    return picked[:index] + [blood] + picked[index + 1:]


def _is_effective_tilt(member: Dict) -> bool:
    """标签含倾斜，且 4 栏里有「倾斜」或「焚烧烙印」。特性不算。"""
    if "倾斜" not in (member.get("tags") or []):
        return False
    return any(skill.get("name") in _TILT_MOVE_NAMES for skill in member.get("skills") or [])


def _effective_tilt_sentence(members: List[Dict]) -> str:
    parts = []
    for member in members:
        moves = [skill.get("name") for skill in member.get("skills") or [] if skill.get("name") in _TILT_MOVE_NAMES]
        if "倾斜" in (member.get("tags") or []) and moves:
            parts.append(f"{member['name']}携带{moves[0]}")
    if not parts:
        return "队内还没有有效倾斜。"
    return "有效倾斜是" + "、".join(parts) + "。"


def complete_team_answer(answer: str, question: str = "") -> str:
    """按已点技能补满 4 栏，并裁定血脉和全队道具。凑不齐 6 只时原样返回。"""
    dengdeng = load_dengdeng()
    catalog = _by_name(dengdeng)
    parsed = parse_team_config(answer, dengdeng)
    members = [member for member in parsed["members"] if member["name"] in catalog]
    if len(members) != 6:
        return answer or ""
    chart = type_chart()
    filled = []
    for member in members[:6]:
        mon = catalog[member["name"]]
        skills = fill_member_skills(mon, member.get("skills") or [], True, chart)
        filled.append({
            "name": member["name"],
            "tags": _style_tags(mon),
            "skills": skills,
            "blood": "",
        })
    decision = choose_battle_item(filled, question)
    targets = set(decision.get("targets") or [])
    if decision["item"] == _ITEM_EVOLVE:
        for member in filled:
            if member["name"] not in targets:
                continue
            mon = catalog[member["name"]]
            kept = [skill for skill in member["skills"] if skill.get("source") != "血脉"]
            member["skills"] = fill_member_skills(mon, kept, False, chart)
            member["blood"] = "首领血脉"
    elif decision["priority"] == "P1" and decision["target"]:
        target = next(member for member in filled if member["name"] == decision["target"])
        mon = catalog[target["name"]]
        if not any(skill.get("source") == "血脉" for skill in target["skills"]):
            blood = _best_blood_skill(mon, target["skills"], chart)
            if blood:
                copied = dict(blood)
                copied["types"] = set(blood["types"])
                copied["in_pool"] = True
                copied["raw"] = _skill_phrase(copied)
                target["skills"] = _replace_for_blood(mon, target["skills"], copied)[:SKILL_SLOT_COUNT]
    for member in filled:
        if member["blood"]:
            continue
        member["blood"] = _blood_label(member["skills"])
    sentence = _item_sentence(
        decision["item"],
        decision["priority"],
        decision.get("target") or "",
        decision.get("targets") or [],
        bool(decision.get("forced")),
    )
    tilt_sentence = _effective_tilt_sentence(filled)
    reason = parsed.get("reason") or ""
    if sentence not in reason:
        reason = (reason + sentence).strip() if reason else sentence
    if tilt_sentence not in reason:
        reason = (reason + tilt_sentence).strip()
    return format_team_answer(filled, decision["item"], reason)


def format_team_answer(members: List[Dict], item: str, reason: str) -> str:
    lines = ["队伍配置为"]
    for member in members:
        skills = "、".join(_skill_phrase(skill) for skill in member.get("skills") or [])
        tags = "、".join(member.get("tags") or []) or "未提供"
        lines.append(f"- {member['name']}｜标签：{tags}｜血脉：{member.get('blood') or '初始血脉'}｜技能：{skills}")
    lines.append(f"战斗道具：【{item}】")
    lines.append(f"选取的理由是{reason.strip()}")
    return "\n".join(lines)


def _member_skill_issues(
    member: Dict,
    mon: Dict,
    chart: Dict,
    peer_coverages: List[int],
    evolve_targets: List[str] = None,
) -> List[str]:
    issues = []
    skills = member.get("skills") or []
    if len(skills) != SKILL_SLOT_COUNT:
        issues.append(f"{member['name']} 应正好携带 {SKILL_SLOT_COUNT} 个技能，当前 {len(skills)} 个")
    if any(skill.get("name") == "聚能" for skill in skills):
        issues.append(f"{member['name']} 不能用【聚能】凑技能栏")
    pool = elf_skill_options(mon)
    pool_names = {skill["name"] for skill in pool}
    bloods = [skill for skill in skills if skill.get("source") == "血脉"]
    if len(bloods) > 1:
        issues.append(f"{member['name']} 的血脉技能超过 1 个")
    for skill in skills:
        if skill.get("name") == "聚能":
            continue
        if skill.get("name") not in pool_names or not skill.get("in_pool", True):
            issues.append(f"{member['name']} 的技能「{skill.get('name')}」不在自己的技能池")
            continue
        raw = skill.get("raw") or ""
        if skill.get("source") == "技能石" and "消耗【技能石】" not in raw:
            issues.append(f"{member['name']} 的技能石技能必须写消耗【技能石】")
        if skill.get("source") == "血脉" and "消耗【血脉药】" not in raw:
            issues.append(f"{member['name']} 的血脉技能必须写消耗【血脉药】")
    tags = member.get("tags") or []
    pool_names = {skill["name"] for skill in pool}
    pool_has_attack = any(skill["category"] == "攻击" for skill in pool)
    carried_attacks = _attack_skills(skills)
    if "联防" in tags and not any(skill.get("category") == "防御" for skill in skills):
        issues.append(f"{member['name']} 是联防，但 4 个技能里没有防御技能")
    if pool_has_attack and len(carried_attacks) < 1:
        issues.append(f"{member['name']} 的技能池里有攻击技能，但 4 栏里没有攻击")
    if "输出" in tags and pool_has_attack:
        if len(carried_attacks) < 2:
            issues.append(f"{member['name']} 是输出，攻击技能少于 2 个")
        elif not _output_spread_ok(skills, mon, chart, peer_coverages):
            issues.append(f"{member['name']} 的攻击技能既没有盖住 {OUTPUT_SINGLE_TYPE_MIN} 种单属性，也不能反克克制自己的属性")
        if not _damage_direction_ok(skills, mon):
            issues.append(f"{member['name']} 的攻击技能整体与物攻/魔攻倾向相反")
    dispel_options = [name for name in _DISPEL_MOVE_NAMES if name in pool_names]
    if "消强" in tags and dispel_options and not any(skill.get("name") in _DISPEL_MOVE_NAMES for skill in skills):
        issues.append(f"{member['name']} 是消强，要携带{'或'.join(dispel_options)}")
    if "充能" in tags and _CHARGE_MOVE_NAME in pool_names and not any(skill.get("name") == _CHARGE_MOVE_NAME for skill in skills):
        issues.append(f"{member['name']} 是充能，要携带{_CHARGE_MOVE_NAME}")
    blood = member.get("blood") or ""
    is_evolve_target = member["name"] in set(evolve_targets or [])
    if blood == "首领血脉":
        if bloods:
            issues.append(f"{member['name']} 是首领血脉，不能再带血脉技能")
    elif blood == "初始血脉":
        if bloods:
            issues.append(f"{member['name']} 写了初始血脉，却携带了血脉技能")
    elif blood.endswith("血脉"):
        expected = blood[:-2]
        if len(bloods) != 1 or bloods[0].get("blood_type") != expected:
            issues.append(f"{member['name']} 的血脉「{blood}」和已携带血脉技能不一致")
    else:
        issues.append(f"{member['name']} 缺少血脉")
    if is_evolve_target and blood != "首领血脉":
        issues.append(f"{member['name']} 可以首领化，携带【进化之力】时应写成首领血脉")
    return issues


def validate_team_answer(answer: str, question: str) -> List[str]:
    """校验六人、标签、4 技能、血脉、唯一道具、已携带技能的克制覆盖。"""
    dengdeng = load_dengdeng()
    if not dengdeng:
        return ["知识库里没有精灵"]
    catalog = _by_name(dengdeng)
    text = answer or ""
    issues = []
    if "队伍配置为" not in text:
        issues.append("开头必须是「队伍配置为」")
    if "选取的理由" not in text:
        issues.append("必须包含「选取的理由是」")
    if not re.search(r"战斗道具：【[^】]+】", text):
        issues.append("必须写明全队唯一战斗道具")
    parsed = parse_team_config(text, dengdeng)
    members = parsed["members"]
    names = [member["name"] for member in members]
    if len(names) != 6 or len(set(names)) != 6:
        shown = "、".join(names) or "无"
        issues.append(f"配置里应正好有 6 只不同的已记录精灵，当前是：{shown}")
        return issues
    for name in _mentioned_names(question, dengdeng):
        if name not in names:
            issues.append(f"用户点名的 {name} 不在队伍里")
    if not any(_is_effective_tilt(member) for member in members):
        issues.append("队伍里没有有效倾斜：标签含倾斜的精灵必须携带「倾斜」或「焚烧烙印」")
    output_names = [member["name"] for member in members if "输出" in member["tags"]]
    if not 1 <= len(output_names) <= 3:
        issues.append(f"【输出】标签应有 1 到 3 只，当前是 {len(output_names)} 只：{'、'.join(output_names) or '无'}")
    for member in members:
        if "输出" not in member["tags"] and "联防" not in member["tags"]:
            issues.append(f"{member['name']} 没有【输出】或【联防】标签，不能放在其余位置")

    chart = type_chart()
    if not any(chart["super"].values()):
        issues.append("板块 A 的克制表没有读到")
        return issues
    peer = [
        _single_type_coverage(member["skills"], chart)
        for member in members if "输出" in member["tags"]
    ]
    decision = choose_battle_item(members, question)
    using_evolve = parsed["item"] == _ITEM_EVOLVE
    targets = _can_boss_names(members, catalog) if using_evolve else []
    if _must_evolve_names(members) and not using_evolve:
        issues.append("队内有恶魔狼或雪影娃娃，必须携带【进化之力】")
    if using_evolve and not targets:
        issues.append("【进化之力】需要队内至少一只可以首领化的精灵")
    for member in members:
        mon = catalog[member["name"]]
        extra = _member_skill_issues(member, mon, chart, peer, targets)
        if not using_evolve:
            extra = [item for item in extra if "进化之力" not in item]
            if member.get("blood") == "首领血脉":
                extra.append(f"{member['name']} 没有【进化之力】，不能写首领血脉")
        elif member.get("blood") == "首领血脉" and member["name"] not in targets:
            extra.append(f"{member['name']} 不能首领化，不能写首领血脉")
        issues.extend(extra)
    if decision["item"] == _ITEM_WILL:
        typed_outputs = [
            member["name"] for member in members
            if "输出" in member["tags"]
            and str(member.get("blood") or "").endswith("血脉")
            and member.get("blood") not in {"初始血脉", "首领血脉"}
        ]
        if not typed_outputs:
            issues.append("【愿力强化】的使用对象必须是带着系别血脉的输出精灵")
    if parsed["item"] != decision["item"]:
        issues.append(f"战斗道具应为【{decision['item']}】，当前是【{parsed['item'] or '未写'}】")
    elif decision["priority"] == "P0" and "进化之力" not in (parsed.get("reason") or ""):
        issues.append("理由里要写明携带【进化之力】")
    attack_types = carried_skill_types(members)
    total = len(type_combinations())
    covered = coverage_count(attack_types, chart)
    if covered * 2 <= total:
        owned = "、".join(name for name in _TYPE_ORDER if name in attack_types) or "无"
        issues.append(
            f"已携带技能的系别只克制 {covered}/{total} 种单属性与双属性组合，需要超过一半。当前计入：{owned}"
        )
    for attack in _TYPE_ORDER:
        defender_types = [catalog[name].get("types") or [] for name in names]
        if all(_beats(attack, types, chart) for types in defender_types):
            issues.append(f"{attack}属性技能能克制队伍中的全部精灵")
            break
    return issues


def parse_schemes(text: str) -> List[Dict]:
    """从助手回复里拆出多套【方案】。没有方案标题时，整段视为一套。"""
    import re
    dengdeng = load_dengdeng()
    marks = list(re.finditer(r"【方案\s*(\d+)】", text or ""))
    if not marks:
        chunks = [("方案1", text or "")]
    else:
        chunks = []
        for index, mark in enumerate(marks):
            end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
            chunks.append((f"方案{mark.group(1)}", text[mark.start():end]))
    schemes = []
    for title, raw in chunks:
        body = raw.strip()
        section = _team_section(body) if "【队伍】" in body else body
        members = _mentioned_names(section, dengdeng)
        if members:
            schemes.append({"title": title, "raw": body, "members": members})
    return schemes


def choose_overlapping_scheme(schemes: List[Dict], question: str) -> Dict:
    """保留重合成员最多的一套。有合法队伍时，不采用技能池或人数不合规的方案。"""
    dengdeng = load_dengdeng()
    aces = _mentioned_names(question, dengdeng)
    frequency: Dict[str, int] = {}
    for scheme in schemes:
        for name in dict.fromkeys(scheme.get("members") or []):
            frequency[name] = frequency.get(name, 0) + 1

    def overlap_score(members: List[str]) -> int:
        return sum(frequency.get(name, 0) - 1 for name in dict.fromkeys(members))

    ranked = []
    for index, scheme in enumerate(schemes):
        issues = validate_team_draft(scheme.get("raw") or "", question)
        has_ace = all(ace in (scheme.get("members") or []) for ace in aces) if aces else True
        ranked.append({
            "scheme": scheme,
            "overlap": overlap_score(scheme.get("members") or []),
            "issues": issues,
            "has_ace": has_ace,
            "index": index,
        })
    legal = [item for item in ranked if not item["issues"]]
    pool = legal or ranked
    pool.sort(key=lambda item: (item["overlap"], item["has_ace"], -len(item["issues"]), -item["index"]), reverse=True)
    chosen = pool[0]
    shared = [name for name, count in frequency.items() if count >= 2]
    shared.sort(key=lambda name: (-frequency[name], name))
    return {
        "chosen": chosen["scheme"],
        "overlap": chosen["overlap"],
        "issues": chosen["issues"],
        "frequency": frequency,
        "shared": shared,
        "scheme_count": len(schemes),
    }


def format_consensus(selection: Dict) -> str:
    chosen = selection["chosen"]
    assistant = chosen.get("assistant") or "助手"
    lines = ["【采用方案】", chosen.get("raw") or "", "", "【重合】"]
    frequency = selection.get("frequency") or {}
    total = selection.get("scheme_count") or 0
    shared = selection.get("shared") or []
    if shared:
        for name in shared:
            lines.append(f"- {name} 出现在 {frequency.get(name, 0)}/{total} 套方案中")
    else:
        lines.append("- 各方案没有共同成员，采用了和其他方案重合分数最高的一套")
    lines.append(f"采用的是{assistant}的{chosen.get('title') or '方案'}，它与其他方案的重合分数为 {selection.get('overlap', 0)}。")
    issues = selection.get("issues") or []
    if issues:
        lines.append("这套方案仍有规则问题：")
        lines.extend(f"- {item}" for item in issues)
    return "\n".join(lines).strip()


def team_reward(draft: str, question: str) -> float:
    """PPO 用的奖励。只根据知识库规则打分，范围 0 到 1。"""
    dengdeng = load_dengdeng()
    if not dengdeng or not draft.strip():
        return 0.0
    issues = validate_team_answer(draft, question)
    score = 1.0 if not issues else max(0.0, 1.0 - 0.25 * len(issues))
    window = select_window(question, load_usage())
    members = config_members(draft, dengdeng)
    best_overlap = 0.0
    for team in window.get("teams") or []:
        group = set(team.get("members") or [])
        if not group:
            continue
        overlap = len(group.intersection(members)) / len(group)
        best_overlap = max(best_overlap, overlap)
    return round(min(1.0, score * 0.8 + best_overlap * 0.2), 4)


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _format_gold(gold: Dict) -> str:
    lines = ["【队伍】"]
    for index, name in enumerate(gold.get("members") or [], 1):
        lines.append(f"{index}. {name}")
    if gold.get("note"):
        lines.append("【理由】")
        lines.append(str(gold["note"]))
    return "\n".join(lines)


def record_feedback(question: str, model_answer: str, accepted: bool, corrected_team: str = "") -> Dict:
    PREFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "question": question.strip(),
        "model_answer": model_answer.strip(),
        "accepted": bool(accepted),
        "corrected_team": corrected_team.strip(),
        "reward": team_reward(model_answer, question),
    }
    with INTERACTION_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    pairs = rebuild_preference_dataset()
    return {"saved": True, "reward": event["reward"], "pairs": pairs}


def rebuild_preference_dataset() -> int:
    """用户修正过的队伍，以及和完美配对不一致的模型队伍，写成 DPO 样本。"""
    interactions = _read_jsonl(INTERACTION_PATH)
    golds = _read_jsonl(GOLD_PATH)
    pairs = []
    seen = set()

    def add_pair(prompt: str, chosen: str, rejected: str, source: str) -> None:
        chosen = chosen.strip()
        rejected = rejected.strip()
        if not prompt.strip() or not chosen or not rejected or chosen == rejected:
            return
        key = (prompt.strip(), chosen, rejected)
        if key in seen:
            return
        seen.add(key)
        pairs.append({
            "prompt": prompt.strip(),
            "chosen": chosen,
            "rejected": rejected,
            "source": source,
        })

    for event in interactions:
        if event.get("corrected_team"):
            add_pair(event.get("question") or "", event["corrected_team"], event.get("model_answer") or "", "user_edit")
        for gold in golds:
            request = str(gold.get("request") or "")
            question = str(event.get("question") or "")
            if request and request in question:
                add_pair(question, _format_gold(gold), event.get("model_answer") or "", "gold")

    PREFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    with DPO_PATH.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")
    return len(pairs)
