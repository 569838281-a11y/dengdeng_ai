"""按板块标题、精灵名和首领形态检索规则与 JSON。找不到就不编。

检索任务在结构化命中之外，再尝试专用向量索引。索引只含 rules.md 切块和精灵 JSON，
不含政策 PDF，也不把 knowledge/知识库.md 和 record 各收一遍。
"""
import logging
import re
import threading
from pathlib import Path

from pokemon_kb import (
    _TYPE_ORDER,
    _mentioned_names,
    _name_stem,
    _plate_excerpt,
    load_pokemon,
    load_rules,
    rule_chunks,
    skill_catalog,
)

logger = logging.getLogger(__name__)

KNOWLEDGE_STEPS = (
    ("parse", "理解意图"),
    ("lookup", "结构化检索"),
    ("web", "联网搜寻"),
    ("index", "知识索引"),
    ("retrieve", "召回片段"),
    ("generate", "生成回答"),
    ("done", "合并结果"),
)

_INDEX_LOCK = threading.Lock()
_knowledge_retriever = None
_knowledge_docs = None
_index_unavailable = ""

_PLATES = (
    (("板块A", "板块 A", "克制", "属性相克", "克制表"), "板块 A"),
    (("板块B", "板块 B", "能量", "聚能", "入场能量"), "板块 B"),
    (("板块C", "板块 C", "携带", "血脉药", "技能石", "首领血脉"), "板块 C"),
    (("板块D", "板块 D", "战斗道具", "愿力强化", "进化之力", "光合治愈", "愿力冲击"), "板块 D"),
    (("板块M", "板块 M", "伤害公式", "伤害", "种族值换算", "本系加成"), "板块 M"),
)

_SPOKEN_MAP = (
    (("减伤", "挡伤害", "防住了"), ("应对攻击", "减伤", "防御技能")),
    (("打断", "放不出状态", "无法使用状态技能"), ("应对状态", "打断")),
)
_DEFENSE_SKILL = re.compile(r"(?:使用防御|用防御|防御后|防御技能)")

_QUERY_NOISE = (
    "请帮我查询", "请帮我查一下", "请帮我查", "请帮我看",
    "请查询", "请介绍", "请告诉我",
    "帮我查一下", "帮我查询", "帮我查", "帮我看",
    "的信息", "的资料", "是什么", "有哪些",
    "查询", "介绍", "检索", "看看",
)


def _search_terms(text: str) -> list:
    raw = (text or "").strip()
    cleaned = raw
    for noise in _QUERY_NOISE:
        cleaned = cleaned.replace(noise, "")
    cleaned = re.sub(r"[\s，。．！？、]+", "", cleaned).strip()
    terms = []
    if cleaned:
        terms.append(cleaned)
    if raw and raw not in terms:
        terms.append(raw)
    return terms


def _type_section(question: str) -> str:
    if "技能" not in (question or ""):
        return ""
    for name in _TYPE_ORDER:
        if f"{name}系" not in question:
            continue
        lines = []
        capture = False
        for line in load_rules().splitlines():
            if line.startswith(f"## {name}系"):
                capture = True
                lines.append(line)
                continue
            if capture and line.startswith("## "):
                break
            if capture:
                lines.append(line)
        text = "\n".join(lines).strip()
        if len(text) > 1800:
            text = text[:1800] + "\n…（本节后面还有技能，这里只节选开头）"
        return text
    return ""


def _boss_lines(mon: dict, focus: str = "") -> list:
    boss = str(mon.get("boss") or "").strip()
    can_boss = str(mon.get("can_boss") or "").strip() == "是"
    lines = []
    if can_boss and boss:
        lines.append(f"首领化：是。形态：{boss}（记在本条里，不是单独一只精灵）")
    elif boss:
        lines.append(f"首领化形态字段：{boss}")
    needles = []
    if focus:
        needles.append(focus)
        stem = _name_stem(focus)
        if stem and stem not in needles:
            needles.append(stem)
    if boss:
        needles.append(boss)
        stem = _name_stem(boss)
        if stem and stem not in needles:
            needles.append(stem)
    seen = set()
    for line in str(mon.get("record") or "").splitlines():
        stripped = line.strip().lstrip("- ").strip()
        if not stripped or stripped in seen:
            continue
        if any(needle and needle in stripped for needle in needles):
            seen.add(stripped)
            lines.append(stripped)
    return lines


def _elf_summary(mon: dict, focus: str = "") -> str:
    stats = mon.get("base_stats") or {}
    native = "、".join(str(item).split("｜")[0] for item in mon.get("native_skills") or []) or "未提供"
    stone = "、".join(str(item).split("｜")[0] for item in mon.get("stone_skills") or []) or "未提供"
    blood = "、".join(str(item).split("｜")[0] for item in mon.get("blood_skills") or []) or "未提供"
    parts = [
        f"精灵：{mon['name']}",
        f"属性：{'、'.join(mon.get('types') or []) or '未提供'}",
        f"标签：{mon.get('style') or '未提供'}",
        f"特性：{mon.get('trait') or '未提供'}",
        (
            "种族值："
            f"生命 {stats.get('hp', '未提供')}，"
            f"物攻 {stats.get('attack', '未提供')}，"
            f"魔攻 {stats.get('special_attack', '未提供')}，"
            f"物防 {stats.get('defense', '未提供')}，"
            f"魔防 {stats.get('special_defense', '未提供')}，"
            f"速度 {stats.get('speed', '未提供')}"
        ),
    ]
    parts.extend(_boss_lines(mon, focus))
    parts.extend([
        f"自带：{native}",
        f"技能石：{stone}",
        f"血脉：{blood}",
        "来源：knowledge/pokemon/" + mon["name"] + ".json",
    ])
    return "\n".join(parts)


def _add_pokemon_hit(hits: list, mon: dict, focus: str = "") -> None:
    name = mon["name"]
    if any(item.get("source") == f"knowledge/pokemon/{name}.json" for item in hits):
        return
    title = name
    boss = str(mon.get("boss") or "").strip()
    if focus and boss and (focus in boss or _name_stem(boss) == focus):
        title = f"{name} · {boss}"
    hits.append({
        "title": title,
        "source": f"knowledge/pokemon/{name}.json",
        "kind": "pokemon",
        "text": _elf_summary(mon, focus),
        "photo_name": name,
    })


def find_by_name(question: str) -> list:
    """正式名和首领形态别名。只返回资料里有的精灵。"""
    pokemon = load_pokemon()
    catalog = {mon["name"]: mon for mon in pokemon}
    names = _mentioned_names(question, pokemon)
    terms = _search_terms(question)
    if not names and terms:
        names = _mentioned_names(terms[0], pokemon)
    return [catalog[name] for name in names if name in catalog]


def find_by_type(type_name: str) -> list:
    """types 里包含该属性的全部已记录精灵。"""
    needle = (type_name or "").strip()
    if needle not in _TYPE_ORDER:
        return []
    return [mon for mon in load_pokemon() if needle in (mon.get("types") or [])]


def _skill_source_line(name: str) -> str:
    prefix = f"- {name}｜"
    for line in load_rules().splitlines():
        if line.startswith(prefix):
            return line[2:].strip()
    return ""


def find_by_skill(name: str):
    """板块 G 总表里这一行，不带回整节标题。"""
    entry = skill_catalog().get(name)
    if not entry or name == "聚能":
        return None
    line = _skill_source_line(name)
    effect = entry.get("effect") or ""
    category = entry.get("category") or "未提供"
    text = f"分类：{category}\n效果：{effect or '未提供'}"
    if line:
        text += f"\n原文：{line}"
    return {
        "title": name,
        "source": "knowledge/rules.md",
        "kind": "skill",
        "text": text,
        "photo_name": "",
    }


def _mentioned_skills(question: str) -> list:
    """按技能名从长到短匹配。『防御』必须像在点这个技能，而不是章节标题。"""
    text = question or ""
    catalog = skill_catalog()
    names = sorted((name for name in catalog if name and name != "聚能"), key=len, reverse=True)
    occupied = [False] * len(text)
    found = []
    for name in names:
        if name == "防御":
            if _DEFENSE_SKILL.search(text) and name not in found:
                found.append(name)
            continue
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            if not any(occupied[index:index + len(name)]):
                for cursor in range(index, index + len(name)):
                    occupied[cursor] = True
                if name not in found:
                    found.append(name)
                break
            start = index + 1
    return found


def _spoken_terms(question: str) -> list:
    terms = []
    for triggers, mapped in _SPOKEN_MAP:
        if any(word in (question or "") for word in triggers):
            for item in mapped:
                if item not in terms:
                    terms.append(item)
    return terms


def _asks_defend_mechanic(question: str) -> bool:
    text = question or ""
    reduction = any(word in text for word in ("减伤", "挡伤害", "防住了", "应对攻击"))
    clash = any(word in text for word in ("防御", "攻击", "打对面"))
    return reduction and clash


def _plate_g_categories() -> str:
    lines = []
    capture = False
    for line in load_rules().splitlines():
        if line.startswith("## 板块 G"):
            capture = True
            continue
        if not capture:
            continue
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped.startswith("- ") and any(word in stripped for word in ("攻击技能", "防御技能", "状态技能")):
            lines.append(stripped)
        if len(lines) >= 3:
            break
    return "\n".join(lines)


def _pool_has(items, name: str) -> bool:
    for item in items or []:
        head = str(item).split("｜")[0].strip()
        if head == name:
            return True
    return False


def _skill_holders(name: str) -> list:
    """已记录精灵里，谁会这招，以及它在自带、技能石还是血脉里。"""
    lines = []
    for mon in load_pokemon():
        bags = []
        if _pool_has(mon.get("native_skills"), name):
            bags.append("自带")
        if _pool_has(mon.get("stone_skills"), name):
            bags.append("技能石")
        if _pool_has(mon.get("blood_skills"), name):
            bags.append("血脉")
        if bags:
            lines.append(f"{mon['name']}：{'、'.join(bags)}")
    return lines


def _compose_skill_answer(names: list) -> dict:
    hits = []
    parts = []
    must_names = []
    must_tokens = []
    for name in names[:3]:
        hit = find_by_skill(name)
        if not hit:
            continue
        hits.append(hit)
        effect = (skill_catalog().get(name) or {}).get("effect") or ""
        category = (skill_catalog().get(name) or {}).get("category") or ""
        note = ""
        if category == "防御" and "减伤" in effect and "应对攻击" in effect:
            note = "防御类技能在应对攻击类技能时会减伤。"
            must_tokens.extend(["防御类", "应对攻击", "减伤"])
        if "应对状态" in effect and "打断" in effect:
            note = "这是在应对状态技能时造成打断，并按原文回复被打断技能的能耗，不是永久不能使用状态技能。"
            must_tokens.extend(["应对状态", "打断"])
        parts.append(f"{note}\n【{name}】\n{hit['text']}".strip())
        holders = _skill_holders(name)
        if holders:
            parts.append("已记录精灵里会这招的：\n" + "\n".join(holders))
            hit["text"] = hit["text"] + "\n" + "\n".join(holders)
        must_names.append(name)
    return {
        "answer": "\n\n".join(parts),
        "hits": hits,
        "must_names": must_names,
        "must_tokens": must_tokens,
    }


def _compose_defend_mechanic() -> dict:
    intro = _plate_g_categories()
    hits = []
    if intro:
        hits.append({
            "title": "板块 G 分类",
            "source": "knowledge/rules.md",
            "kind": "plate",
            "text": intro,
            "photo_name": "",
        })
    defense = find_by_skill("防御")
    examples = []
    for skill_name, entry in skill_catalog().items():
        if skill_name in {"防御", "聚能"}:
            continue
        effect = entry.get("effect") or ""
        if "减伤" in effect and "应对攻击" in effect:
            hit = find_by_skill(skill_name)
            if hit:
                examples.append(hit)
        if len(examples) >= 2:
            break
    if defense:
        hits.append(defense)
    hits.extend(examples)
    effect = (skill_catalog().get("防御") or {}).get("effect") or "减伤70%，应对攻击。"
    answer = (
        "防御类技能在应对攻击类技能时会减伤。"
        f"技能「防御」本身是{effect}\n\n"
    )
    if intro:
        answer += f"【板块 G 分类】\n{intro}\n\n"
    if defense:
        answer += f"【防御】\n{defense['text']}"
    if examples:
        answer += "\n\n例如：\n" + "\n\n".join(f"【{hit['title']}】\n{hit['text']}" for hit in examples)
    return {
        "answer": answer.strip(),
        "hits": hits,
        "must_names": ["防御"] if defense else [],
        "must_tokens": ["防御类", "应对攻击", "减伤"],
    }


def _detect_types(question: str) -> list:
    found = []
    text = question or ""
    for name in _TYPE_ORDER:
        if f"{name}系" in text or f"{name}属性" in text or f"属{name}" in text:
            found.append(name)
    return found


def _detect_plates(question: str) -> list:
    found = []
    text = question or ""
    terms = _search_terms(text)
    focus = terms[0] if terms else ""
    for keys, prefix in _PLATES:
        if any(key in text for key in keys) or (focus and any(key in focus for key in keys)):
            found.append(prefix)
    return found


def find_rules(question: str, intent: str, plates: list = None) -> list:
    """按已经判定的类别取板块。没判定时才退回关键字。"""
    hits = []
    if intent == "skills":
        section = _type_section(question)
        if section:
            hits.append({
                "title": "板块 G 节选",
                "source": "knowledge/rules.md",
                "kind": "plate",
                "text": section,
                "photo_name": "",
            })
            return hits
    chosen = [prefix for prefix in (plates or []) if prefix]
    if not chosen:
        chosen = _detect_plates(question)
    for prefix in chosen:
        excerpt = _plate_excerpt(prefix)
        if not excerpt:
            continue
        hits.append({
            "title": prefix,
            "source": "knowledge/rules.md",
            "kind": "plate",
            "text": excerpt if len(excerpt) <= 2200 else excerpt[:2200] + "\n…",
            "photo_name": "",
        })
    return hits


def _empty_result(plan: dict = None) -> dict:
    plan = plan or {}
    return {
        "found": False,
        "answer": "知识库没有这项资料。",
        "hits": [],
        "sources": [],
        "intent": plan.get("intent") or "unknown",
        "types": plan.get("types") or [],
        "names": plan.get("names") or [],
        "must_names": [],
        "must_tokens": [],
    }


def _finish(plan: dict, hits: list, answer: str, must_names: list = None, must_tokens: list = None) -> dict:
    if not hits:
        return _empty_result(plan)
    return {
        "found": True,
        "answer": answer,
        "hits": hits,
        "sources": _sources_of(hits),
        "intent": plan.get("intent") or "",
        "types": plan.get("types") or [],
        "names": plan.get("names") or [],
        "must_names": must_names or [],
        "must_tokens": must_tokens or [],
    }


def _type_names(types: list) -> str:
    return "、".join(types)


def _mon_types(mon: dict) -> str:
    return "、".join(mon.get("types") or []) or "未提供"


def _compose_type_answer(intent: str, types: list, mons: list) -> dict:
    label = _type_names(types)
    if not mons:
        return {
            "answer": f"知识库里没有属性含{label}的精灵。",
            "hits": [],
            "must_names": [],
            "must_tokens": [label] if label else [],
        }
    roster = "、".join(f"{mon['name']}（{_mon_types(mon)}）" for mon in mons)
    hits = []
    if intent == "recommend":
        preferred = [mon for mon in mons if "输出" in str(mon.get("style") or "")]
        ordered = preferred or list(mons)
        shown = ordered[:3]
        primary = shown[0]
        reason = "标签含「输出」" if "输出" in str(primary.get("style") or "") else "该属性列表中的第一只"
        others = [mon["name"] for mon in mons if mon["name"] != primary["name"]]
        for mon in shown:
            _add_pokemon_hit(hits, mon, "")
        answer = (
            f"推荐{primary['name']}。依据：{reason}。"
            f"属性：{_mon_types(primary)}。\n\n"
            f"【{primary['name']}】\n{_elf_summary(primary)}"
        )
        if len(shown) > 1:
            answer += "\n\n" + "\n\n".join(
                f"【{mon['name']}】\n{_elf_summary(mon)}" for mon in shown[1:]
            )
        if others:
            answer += f"\n\n同系还有：{'、'.join(others)}。"
        return {
            "answer": answer,
            "hits": hits,
            "must_names": [mon["name"] for mon in mons],
            "must_tokens": types[:],
        }
    primary = mons[0]
    _add_pokemon_hit(hits, primary, "")
    answer = f"知识库里属性含{label}的精灵：{roster}。\n\n【{primary['name']}】\n{_elf_summary(primary)}"
    return {
        "answer": answer,
        "hits": hits,
        "must_names": [mon["name"] for mon in mons],
        "must_tokens": types[:],
    }


def _hide_paths(text: str) -> str:
    kept = []
    for line in (text or "").splitlines():
        low = line.lower()
        if ".json" in low or "knowledge/" in low:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _pool_text(mon: dict) -> str:
    native = "、".join(str(item).split("｜")[0] for item in mon.get("native_skills") or []) or "未提供"
    stone = "、".join(str(item).split("｜")[0] for item in mon.get("stone_skills") or []) or "未提供"
    blood = "、".join(str(item).split("｜")[0] for item in mon.get("blood_skills") or []) or "未提供"
    return "\n".join([
        f"精灵：{mon['name']}",
        f"自带：{native}",
        f"技能石：{stone}",
        f"血脉：{blood}",
    ])


_DAMAGE_ASK = re.compile(r"伤害|打不出|没伤害|伤害低|威力怎么算")
_POOL_ASK = re.compile(r"技能池|自带技能|技能石|血脉技能|会什么招|有哪些招|会哪些招")
_CATEGORY_PLATES = {
    "type": ["板块 A"],
    "energy": ["板块 B"],
    "blood": ["板块 C"],
    "item": ["板块 D"],
    "damage": ["板块 M"],
    "ability": ["板块 N"],
    "skill": ["板块 G"],
}


def _category_plates(categories: list) -> list:
    found = []
    for name in categories or []:
        for plate in _CATEGORY_PLATES.get(name, []):
            if plate not in found:
                found.append(plate)
    return found


def lookup_by_plan(question: str, plan: dict) -> dict:
    intent = plan.get("intent") or "unknown"
    text = (question or "").strip()
    if intent == "lookup_one":
        mons = find_by_name(text)[:3]
        hits = []
        focus = (_search_terms(text) or [""])[0]
        notes = []
        for mon in mons:
            actual = list(mon.get("types") or [])
            asked = [name for name in (plan.get("types") or []) if name not in actual]
            if asked:
                notes.append(
                    f"{mon['name']}在资料里的属性是{_mon_types(mon)}，不是{_type_names(asked)}。"
                )
            _add_pokemon_hit(hits, mon, focus)
        if not hits:
            return _empty_result(plan)
        body = "\n\n".join(f"【{hit['title']}】\n{hit['text']}" for hit in hits)
        if notes:
            body = "\n".join(notes) + "\n\n" + body
        must_tokens = []
        for mon in mons:
            must_tokens.extend(mon.get("types") or [])
        for hit in hits:
            if "·" in (hit.get("title") or ""):
                must_tokens.append(hit["title"].split("·", 1)[1].strip())
        return _finish(plan, hits, body, [mon["name"] for mon in mons], must_tokens)
    if intent == "lookup_pool":
        mons = find_by_name(text)[:3]
        hits = []
        parts = []
        for mon in mons:
            body = _pool_text(mon)
            hits.append({
                "title": mon["name"],
                "source": f"knowledge/pokemon/{mon['name']}.json",
                "kind": "pokemon",
                "text": body,
                "photo_name": mon["name"],
            })
            parts.append(f"【{mon['name']}】\n{body}")
        if not hits:
            return _empty_result(plan)
        return _finish(plan, hits, "\n\n".join(parts), [mon["name"] for mon in mons], ["自带", "技能石", "血脉"])
    if intent in {"list", "recommend"}:
        mons = []
        for type_name in plan.get("types") or []:
            for mon in find_by_type(type_name):
                if all(item["name"] != mon["name"] for item in mons):
                    mons.append(mon)
        composed = _compose_type_answer(intent, plan.get("types") or [], mons)
        if not composed["hits"]:
            empty = _empty_result(plan)
            empty["answer"] = composed["answer"]
            return empty
        return _finish(
            plan,
            composed["hits"],
            composed["answer"],
            composed["must_names"],
            composed["must_tokens"],
        )
    if intent == "lookup_skill":
        composed = _compose_skill_answer(plan.get("skills") or [])
        if not composed["hits"]:
            return _empty_result(plan)
        return _finish(plan, composed["hits"], composed["answer"], composed["must_names"], composed["must_tokens"])
    if intent == "mechanic_defend":
        composed = _compose_defend_mechanic()
        if not composed["hits"]:
            return _empty_result(plan)
        return _finish(plan, composed["hits"], composed["answer"], composed["must_names"], composed["must_tokens"])
    if intent in {"rules", "skills"}:
        hits = find_rules(text, intent, plan.get("plates"))
        if not hits:
            return _empty_result(plan)
        answer = "\n\n".join(f"【{hit['title']}】\n{hit['text']}" for hit in hits)
        tokens = ["技能石"] if any(hit.get("title") == "板块 C" for hit in hits) else []
        if any(hit.get("title") == "板块 M" for hit in hits):
            tokens.append("伤害量")
        if intent == "skills":
            tokens.append("技能")
        return _finish(plan, hits, answer, [], tokens)
    rescued = _rescue_by_spoken(text)
    if rescued:
        return rescued
    return _empty_result(plan)


def _rescue_by_spoken(question: str) -> dict:
    """规则没定意图时，用口语映射到总表效果里再找几行。"""
    if "打断" in (question or "") and "状态" in (question or "") and find_by_skill("截拳"):
        plan = {"intent": "lookup_skill", "types": [], "names": [], "skills": ["截拳"], "plates": []}
        composed = _compose_skill_answer(["截拳"])
        return _finish(plan, composed["hits"], composed["answer"], composed["must_names"], composed["must_tokens"])
    terms = [term for term in _spoken_terms(question) if term not in {"防御技能"}]
    if not terms:
        return {}
    if any(term in {"减伤", "应对攻击"} for term in terms):
        plan = {"intent": "mechanic_defend", "types": [], "names": [], "skills": ["防御"], "plates": []}
        composed = _compose_defend_mechanic()
        if composed["hits"]:
            return _finish(plan, composed["hits"], composed["answer"], composed["must_names"], composed["must_tokens"])
    hits = []
    for skill_name, entry in skill_catalog().items():
        blob = f"{entry.get('effect') or ''} {_skill_source_line(skill_name)}"
        if any(term and term in blob for term in terms):
            hit = find_by_skill(skill_name)
            if hit:
                hits.append(hit)
        if len(hits) >= 3:
            break
    if not hits:
        return {}
    plan = {"intent": "lookup_skill", "types": [], "names": [], "skills": [hit["title"] for hit in hits], "plates": []}
    answer = "\n\n".join(f"【{hit['title']}】\n{hit['text']}" for hit in hits)
    return _finish(plan, hits, answer, [hit["title"] for hit in hits], terms)


def _plan_by_rules(question: str) -> dict:
    text = (question or "").strip()
    names = [mon["name"] for mon in find_by_name(text)]
    skills = _mentioned_skills(text)
    types = _detect_types(text)
    plates = _detect_plates(text)
    plan = {
        "intent": "unknown",
        "types": types,
        "names": names,
        "skills": skills,
        "plates": plates,
        "queries": [],
        "focus": "",
        "need_rag": True,
        "source": "rules",
    }
    if _DAMAGE_ASK.search(text):
        plan["intent"] = "rules"
        plan["focus"] = "damage"
        plan["plates"] = ["板块 M"]
        if re.search(r"克制|抵抗", text):
            plan["plates"].append("板块 A")
        plan["queries"] = ["板块 M 伤害公式 威力 攻防比 本系加成 克制倍率"]
        plan["skills"] = []
        return plan
    if names and _POOL_ASK.search(text):
        plan["intent"] = "lookup_pool"
        plan["focus"] = "pool"
        plan["skills"] = []
        plan["queries"] = [f"{name} 自带 技能石 血脉" for name in names[:2]]
        return plan
    if skills:
        plan["intent"] = "lookup_skill"
        plan["focus"] = "skill"
        plan["plates"] = ["板块 G"]
        plan["queries"] = []
        for name in skills[:2]:
            plan["queries"].extend([name, f"板块 G {name}", f"哪些精灵会{name}"])
        return plan
    if names:
        plan["intent"] = "lookup_one"
        plan["skills"] = []
        plan["queries"] = names[:2]
        return plan
    if "技能" in text and types:
        plan["intent"] = "skills"
        return plan
    if types and any(word in text for word in ("推荐", "一只", "一个")):
        plan["intent"] = "recommend"
        return plan
    if types and any(word in text for word in ("有什么", "哪些", "列出", "有哪些")):
        plan["intent"] = "list"
        return plan
    if types:
        plan["intent"] = "list"
        return plan
    if plates:
        plan["intent"] = "rules"
        plan["types"] = []
        return plan
    if _asks_defend_mechanic(text):
        plan["intent"] = "mechanic_defend"
        plan["skills"] = ["防御"]
        return plan
    if "打断" in text and "状态" in text and find_by_skill("截拳"):
        plan["intent"] = "lookup_skill"
        plan["skills"] = ["截拳"]
        return plan
    return plan


def _plan_with_model(question: str) -> dict:
    """规则对不上时，让短超时模型只产出意图 JSON。失败就当没规划。"""
    from llm_provider import get_team_invoke

    allowed = "、".join(_TYPE_ORDER)
    prompt = (
        "只输出一个 JSON，不要解释，不要编造资料里没有的精灵。\n"
        'schema：{"intent":"list|recommend|lookup_one|lookup_skill|mechanic_defend|rules|skills","types":[],"names":[],"skills":[],"need_rag":true}\n'
        f"types 只能从这些属性里选：{allowed}。names 只能是用户点到的精灵。skills 只能是总表里的技能名。\n"
        f"问题：{question}"
    )
    try:
        raw = _message_text(get_team_invoke()(prompt))
    except Exception as exc:
        logger.warning("检索意图规划失败: %s", exc)
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        import json
        data = json.loads(raw[start:end + 1])
    except Exception:
        return {}
    intent = str(data.get("intent") or "")
    if intent not in {"list", "recommend", "lookup_one", "lookup_skill", "mechanic_defend", "rules", "skills"}:
        return {}
    types = [name for name in (data.get("types") or []) if name in _TYPE_ORDER]
    catalog = {mon["name"]: mon for mon in load_pokemon()}
    names = []
    for name in data.get("names") or []:
        if name in catalog and name not in names:
            names.append(name)
            continue
        for mon in find_by_name(str(name)):
            if mon["name"] not in names:
                names.append(mon["name"])
    catalog = skill_catalog()
    skills = [name for name in (data.get("skills") or []) if name in catalog and name != "聚能"]
    if intent == "lookup_one" and not names:
        return {}
    if intent in {"list", "recommend"} and not types:
        return {}
    if intent == "lookup_skill" and not skills:
        return {}
    if intent == "mechanic_defend" and "防御" not in skills:
        skills = ["防御"]
    return {
        "intent": intent,
        "types": types,
        "names": names,
        "skills": skills,
        "plates": _detect_plates(question) if intent == "rules" else [],
        "need_rag": bool(data.get("need_rag", True)),
        "source": "model",
    }


def _apply_model_brief(plan: dict, question: str) -> dict:
    """模型把原句改成检索短句，并补类别。对不上资料的名字丢掉。规则已经判定的意图不改。"""
    from llm_provider import get_team_invoke

    prompt = (
        "把用户的话改成适合查资料的短句，并判断类别。只输出一个 JSON，不要解释。\n"
        "categories 只能从 skill、pokemon、type、energy、blood、item、damage、ability 里选。\n"
        "queries 最多 3 条，用资料里的叫法。skills 只写技能名。names 只写精灵名。没有就空数组。\n"
        '{"queries":[],"categories":[],"skills":[],"names":[]}\n'
        f"原句：{question}"
    )
    try:
        raw = _message_text(get_team_invoke()(prompt))
    except Exception as exc:
        logger.warning("检索改写失败: %s", type(exc).__name__)
        return plan
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return plan
    try:
        import json
        data = json.loads(raw[start:end + 1])
    except Exception:
        return plan
    catalog = skill_catalog()
    pokemon = {mon["name"] for mon in load_pokemon()}
    skills = [name for name in (data.get("skills") or []) if name in catalog and name != "聚能"]
    names = [name for name in (data.get("names") or []) if name in pokemon]
    queries = []
    for item in data.get("queries") or []:
        text = str(item or "").strip()
        if text and text not in queries:
            queries.append(text)
    categories = [name for name in (data.get("categories") or []) if name in _CATEGORY_PLATES]
    if plan.get("intent") == "unknown":
        if skills:
            plan["intent"] = "lookup_skill"
            plan["focus"] = "skill"
            plan["skills"] = skills
            plan["plates"] = ["板块 G"]
        elif "damage" in categories:
            plan["intent"] = "rules"
            plan["focus"] = "damage"
            plan["plates"] = _category_plates(categories) or ["板块 M"]
        elif names and "pokemon" in categories:
            plan["intent"] = "lookup_one"
            plan["names"] = names
        elif categories:
            plan["intent"] = "rules"
            plan["plates"] = _category_plates(categories)
            plan["focus"] = categories[0]
    if queries:
        plan["queries"] = queries[:3]
        plan["source"] = "model" if plan.get("intent") != "unknown" else plan.get("source")
    return plan


def plan_query(question: str, allow_model: bool = False) -> dict:
    plan = _plan_by_rules(question)
    if allow_model:
        plan = _apply_model_brief(plan, question)
        if plan["intent"] == "unknown":
            modeled = _plan_with_model(question)
            if modeled:
                return modeled
    return plan


def _parse_detail(plan: dict) -> str:
    queries = "；".join((plan.get("queries") or [])[:2])
    if queries:
        return f"改写成 {queries}"
    intent = plan.get("intent") or "unknown"
    if plan.get("skills"):
        return f"意图 {intent}，技能 {_type_names(plan['skills'][:3])}"
    if plan.get("types"):
        return f"意图 {intent}，属性 {_type_names(plan['types'])}"
    if plan.get("names"):
        return f"意图 {intent}，名字 {_type_names(plan['names'][:3])}"
    if plan.get("plates"):
        return f"意图 {intent}，{_type_names(plan['plates'])}"
    return f"意图 {intent}"


def search_knowledge(question: str) -> dict:
    """同步查找。只用程序规则理解意图，不调模型。"""
    plan = plan_query(question, allow_model=False)
    return lookup_by_plan(question, plan)


def blank_steps() -> list:
    return [
        {"id": step_id, "label": label, "status": "pending", "detail": ""}
        for step_id, label in KNOWLEDGE_STEPS
    ]


def _sources_of(hits: list) -> list:
    sources = []
    for hit in hits:
        source = hit.get("source") or ""
        if source and source not in sources:
            sources.append(source)
    return sources


def _retrieve_query(question: str, plan: dict) -> str:
    rewritten = [item for item in (plan.get("queries") or []) if item]
    if rewritten:
        return " ".join(rewritten[:3])
    parts = []
    for skill in plan.get("skills") or []:
        parts.append(skill)
        if skill == "防御":
            parts.append("防御 减伤70% 应对攻击")
        if skill == "截拳":
            parts.append("截拳 应对状态 打断")
    if "板块 M" in (plan.get("plates") or []) or "伤害" in (question or ""):
        parts.append("板块 M 伤害")
    if plan.get("intent") == "mechanic_defend":
        parts.append("防御 减伤70% 应对攻击")
    parts.extend(plan.get("names") or [])
    parts.extend(plan.get("types") or [])
    parts.extend(_spoken_terms(question))
    unique = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    return " ".join(unique) if unique else (question or "")


def _lookup_detail(question: str, result: dict) -> str:
    if result.get("intent") == "lookup_skill":
        names = "、".join(result.get("names") or []) or "、".join(
            hit.get("title") or "" for hit in result.get("hits") or [] if hit.get("kind") == "skill"
        )
        return f"命中技能 {names}" if names else "没有命中技能"
    if result.get("intent") == "mechanic_defend":
        return "机制：防御类应对攻击会减伤"
    if result.get("intent") in {"list", "recommend"}:
        types = "、".join(result.get("types") or []) or "未识别"
        names = "、".join(
            hit.get("title") or ""
            for hit in result.get("hits") or []
            if hit.get("kind") == "pokemon"
        ) or "无"
        return f"类型过滤：{types}，命中{names}"
    if not result.get("found"):
        return "没有结构化命中"
    focus = (_search_terms(question) or [""])[0]
    for hit in result.get("hits") or []:
        if hit.get("kind") != "pokemon":
            continue
        title = hit.get("title") or ""
        if "·" in title:
            name, boss = [part.strip() for part in title.split("·", 1)]
            return f"命中{name}.json（boss={boss}）"
        filename = Path(hit.get("source") or "").name or title
        if focus and focus in (hit.get("text") or ""):
            return f"命中{filename}"
    titles = "、".join(item.get("title") or "" for item in (result.get("hits") or [])[:3])
    return f"命中{titles}" if titles else "没有结构化命中"


def _pokemon_page(mon: dict) -> str:
    types = "、".join(mon.get("types") or []) or "未提供"
    return "\n".join([
        f"精灵：{mon.get('name') or ''}",
        f"属性：{types}",
        f"标签：{mon.get('style') or '未提供'}",
        f"特性：{mon.get('trait') or '未提供'}",
        f"首领形态：{mon.get('boss') or '无'}",
        str(mon.get("record") or ""),
    ])


def knowledge_documents() -> list:
    """rules.md 切块 + 每只精灵一条 JSON 摘要。精灵事实只来自 JSON。"""
    from langchain_core.documents import Document

    documents = []
    for chunk in rule_chunks():
        documents.append(Document(
            page_content=chunk["text"],
            metadata={"source": "knowledge/rules.md", "section": chunk["section"]},
        ))
    for mon in load_pokemon():
        name = mon["name"]
        documents.append(Document(
            page_content=_pokemon_page(mon),
            metadata={"source": f"knowledge/pokemon/{name}.json", "section": name},
        ))
    return documents


def _knowledge_source(source: str) -> bool:
    text = (source or "").replace("\\", "/")
    return text.startswith("knowledge/") or text.endswith("rules.md") or "/rules.md" in text


def ensure_knowledge_index():
    """返回 (retriever or None, 'reuse'|'built'|'skip', detail)。失败不抛给调用方。"""
    global _knowledge_retriever, _knowledge_docs, _index_unavailable
    with _INDEX_LOCK:
        if _knowledge_retriever is not None:
            return _knowledge_retriever, "reuse", "复用已有索引"
        if _index_unavailable:
            return None, "skip", _index_unavailable
        try:
            from config import DATA_DIR
            from qa_chain import build_retriever
            from vectorstore import build_or_load_vectorstore

            documents = knowledge_documents()
            persist = str(Path(DATA_DIR) / "knowledge_index")
            vectorstore = build_or_load_vectorstore(documents, persist_directory=persist)
            retriever = build_retriever(
                vectorstore,
                documents=documents,
                parent_documents=None,
                user_id=None,
                adaptive=False,
            )
            _knowledge_retriever = retriever
            _knowledge_docs = documents
            return retriever, "built", "已建成检索专用索引"
        except Exception as exc:
            logger.warning("检索专用索引不可用: %s", exc)
            _index_unavailable = "向量库未就绪"
            return None, "skip", _index_unavailable


def retrieve_passages(query: str) -> tuple:
    """返回 (hits, status, detail)。索引未就绪时 skip，不抛错。"""
    retriever, index_state, index_detail = ensure_knowledge_index()
    if retriever is None:
        return [], "skip", index_detail or "向量不可用，未召回", index_state
    try:
        hits = _retrieved_hits(retriever, query)
    except Exception:
        return [], "skip", "召回失败，沿用结构化结果", index_state
    names = []
    for hit in hits:
        filename = Path(hit["source"]).name
        if filename not in names:
            names.append(filename)
    shown = "、".join(names[:2]) or "无"
    return hits, "done", f"召回 {len(hits)} 条，来源 {shown}", index_state


def _retrieved_hits(retriever, question: str) -> list:
    from config import RETRIEVAL_K

    try:
        docs = retriever.invoke(question)
    except Exception as exc:
        logger.warning("知识片段召回失败: %s", exc)
        raise
    hits = []
    for doc in docs or []:
        source = str((doc.metadata or {}).get("source") or "")
        if not _knowledge_source(source):
            continue
        text = (doc.page_content or "").strip()
        if not text:
            continue
        title = str((doc.metadata or {}).get("section") or Path(source).name)
        hits.append({
            "title": title,
            "source": source.replace("\\", "/"),
            "kind": "chunk",
            "text": text[:1800],
            "photo_name": "",
        })
        if len(hits) >= RETRIEVAL_K:
            break
    return hits


def _merge_hits(primary: list, extra: list) -> list:
    merged = []
    seen = set()
    for hit in list(primary or []) + list(extra or []):
        key = (hit.get("source") or "", (hit.get("text") or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
    return merged


def _clip(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + "\n…"


def _message_text(result) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    return str(content or "").strip()


_NO_MARKDOWN = (
    "不要使用 Markdown 井号标题，不要写 #、## 或 ###。\n"
    "小节用【攻防比太低】这种括号标题，或单独一行短标题。\n"
    "不要用 ``` 代码围栏包整篇回答，也不要用 [标题](网址) 这种写法。\n"
)


def _search_accept(answer: str, structured: dict) -> bool:
    from agents.dengdeng_persona import contains_banned

    body = answer or ""
    if contains_banned(body):
        return False
    if "##" in body or "```" in body or body.lstrip().startswith("#"):
        return False
    if "灯灯" not in body or "小洛克" not in body:
        return False
    source = structured.get("answer") or ""
    if "更可能获胜" in source and "更可能获胜" not in body:
        return False
    if "不是模拟赛" in source and "不是模拟赛" not in body:
        return False
    if "不是你们亲自点的那盘" in source and "不是你们亲自点的那盘" not in body:
        return False
    if "身边的小洛克这回赢了" in source and "身边的小洛克这回赢了" not in body:
        return False
    if "对面那只" in source and "对面那只" not in body:
        return False
    if "这场还没有分出输赢" in source and "这场还没有分出输赢" not in body:
        return False
    if "应对状态" in source and "应对状态" not in body:
        return False
    if "打断" in source and "打断" not in body:
        return False
    if "双灯鱼" in (structured.get("must_names") or []) and "首领化" in body:
        return False
    return _keeps_facts(body, structured)


def _generate_answer(question: str, hits: list, web_results: list = None, structured: dict = None) -> str:
    from agents.dengdeng_persona import build_search_user
    from agents.dengdeng_reply import reply_search

    facts = structured or {"hits": hits, "answer": "", "must_names": [], "must_tokens": []}
    user_text = build_search_user(
        question,
        hits,
        web_results,
        facts.get("must_names"),
        facts.get("must_tokens"),
    )
    summary = (facts.get("spoken_seed") or facts.get("answer") or "").strip()
    if "双灯鱼" in (facts.get("must_names") or []):
        summary = summary.replace("已计入首领化。", "")
    result = reply_search(user_text, lambda text: _search_accept(text, facts), summary)
    logger.info("检索成文经由 %s", result["via"])
    return result["text"]


def _keeps_facts(generated: str, structured: dict) -> bool:
    if not generated:
        return False
    source = "\n".join(hit.get("text") or "" for hit in structured.get("hits") or [])
    if "永久" in generated and "永久" not in source and "永久" not in (structured.get("answer") or ""):
        return False
    for name in structured.get("must_names") or []:
        if name not in generated:
            return False
    for token in structured.get("must_tokens") or []:
        if token and token not in generated:
            return False
    return True


_OFF_GAME = re.compile(r"宝可梦|神奇宝贝|口袋妖怪|52poke|bulbapedia|pokemon|pokémon", re.I)


_PAGE_GAME = re.compile(r"页游|超进化|4399|7k7k|51wan")
_PREFER_HOSTS = ("wiki.biligame.com", "wikipedia.org", "rocom.qq.com")


def _web_queries(question: str, plan: dict) -> list:
    queries = []

    def add(value: str) -> None:
        text = (value or "").strip()
        if text and "洛克王国世界" not in text and "洛克王国：世界" not in text:
            text = f"洛克王国世界 {text}"
        if text and text not in queries:
            queries.append(text)

    add(question)
    for name in (plan.get("names") or [])[:2]:
        add(name)
    for skill in (plan.get("skills") or [])[:2]:
        add(skill)
    return queries[:3]


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url or "").hostname or "").removeprefix("www.")


def _on_game_page(item: dict) -> bool:
    blob = f"{item.get('title') or ''} {item.get('url') or ''} {item.get('snippet') or ''}"
    if _OFF_GAME.search(blob) or _PAGE_GAME.search(blob):
        return False
    host = _host_of(item.get("url") or "")
    if any(skip in host for skip in ("4399.com", "7k7k.com", "51wan.com", "bilibili.com", "youtube.com")):
        return False
    return True


def _page_rank(item: dict) -> int:
    host = _host_of(item.get("url") or "")
    if any(name in host for name in _PREFER_HOSTS):
        return 0
    blob = f"{item.get('title') or ''} {item.get('snippet') or ''}"
    if "世界" in blob:
        return 1
    return 2


_AD_WORDS = ("模拟器", "雷电", "百度", "安全校验", "搜狐", "平台声明", "发布于", "阅读", "卡顿", "高清大屏", "查看TA", "新闻体育")
_TYPE_WORD = "水|火|草|电|冰|龙|地|光|毒|虫|武|翼|萌|幽|恶|机械|幻|普通"


def _clauses(blob: str) -> list:
    pieces = []
    for chunk in re.split(r"[。！？\n；]", blob or ""):
        sent = re.sub(r"\s+", "", chunk).strip(" ，,、")
        if len(sent) < 6:
            continue
        if any(word in sent for word in _AD_WORDS):
            continue
        if sent not in pieces:
            pieces.append(sent)
    return pieces


def _sprite_card(name: str, blobs: list) -> str:
    """把外面读到的句子收成和名录精灵卡一样的栏目。标签和首领化留空。"""
    clauses = []
    for blob in blobs or []:
        clauses.extend(_clauses(blob))
    types = []
    evolutions = []
    trait = ""
    stats = ""
    obtains = []
    skill_lines = []
    for sent in clauses:
        if name and name not in sent:
            kind_hits = []
        elif len(re.findall(rf"(?<!克制)(?<!抵抗)({_TYPE_WORD})系", sent)) > 2:
            kind_hits = []
        else:
            kind_hits = re.findall(rf"(?<!克制)(?<!抵抗)({_TYPE_WORD})系", sent)
        for kind in kind_hits:
            if kind not in types:
                types.append(kind)
        if not trait:
            matched = re.search(r"特性(?:是|为|：)([^，,]{1,16})", sent)
            if matched:
                trait = matched.group(1)
        if not stats and "生命" in sent and re.search(r"\d", sent) and any(word in sent for word in ("物攻", "魔攻", "速度")):
            stats = sent[:80]
        for level, form in re.findall(r"(\d+)级(?:初始形态为|会进化为|进化为)([^，,]{1,8})", sent):
            form = re.sub(r"^最终形态", "", form)
            line = f"{level}级{form}"
            if line not in evolutions:
                evolutions.append(line)
        if "至" in sent:
            for level, form in re.findall(r"至(\d+)级.{0,12}进化为([^，。]{1,8})", sent):
                form = re.sub(r"^最终形态", "", form)
                line = f"{level}级{form}"
                if line not in evolutions:
                    evolutions.append(line)
        if "枭眠之星" in sent and "投放" in sent and "收集枭眠之星后投放果实" not in obtains:
            obtains.append("收集枭眠之星后投放果实")
        if ("清风山" in sent or "杰诺斯" in sent) and "清风山杰诺斯浅海可能遭遇" not in obtains:
            obtains.append("清风山杰诺斯浅海可能遭遇")
        if re.search(r"技能|招式|技能石|血脉|自带", sent):
            skill_lines.append(sent)
    skills = []
    if skill_lines:
        from pokemon_kb import skill_catalog

        blob = "。".join(skill_lines)
        for skill in sorted(skill_catalog(), key=len, reverse=True):
            if len(skill) < 2 or skill == "聚能" or skill in skills:
                continue
            if re.search(rf"{re.escape(skill)}(?!的)", blob):
                skills.append(skill)
            if len(skills) >= 8:
                break
    conflicts = []
    seen_form = {}
    for line in evolutions:
        matched = re.match(r"(\d+)级(.+)", line)
        if not matched:
            continue
        level, form = matched.group(1), matched.group(2)
        previous = seen_form.get(form)
        if previous and previous != level:
            conflicts.append(f"{form}的进化等级说法不一致：{previous}级和{level}级")
        seen_form[form] = level
    if len(types) > 1:
        conflicts.append(f"属性说法不一致：{'、'.join(types)}")
        type_line = "说法不一致"
    else:
        type_line = types[0] if types else "未提供"
    conflict = ("。".join(conflicts) + "。") if conflicts else ""
    missing = []
    if type_line == "未提供":
        missing.append("属性")
    if not trait:
        missing.append("特性")
    if not stats:
        missing.append("种族值")
    if not skills:
        missing.append("技能池")
    lines = [
        f"精灵：{name}",
        f"属性：{type_line}",
        "标签：未提供",
        f"特性：{trait or '未提供'}",
        f"种族值：{stats or '未提供'}",
        "首领化：未提供",
        "自带：未提供",
        "技能石：未提供",
        "血脉：未提供",
    ]
    if skills:
        lines.append("外面提到的技能：" + "、".join(skills))
    if evolutions:
        lines.append("进化：" + "，".join(evolutions[:4]))
    if obtains:
        lines.append("获取：" + "；".join(obtains[:2]))
    gap = ("还没读到：" + "、".join(missing) + "。") if missing else "外面读到的字段够讲这只精灵。"
    lines.append("证据：" + conflict + gap + "标签和首领化留空。")
    return "\n".join(lines)


def _card_field(card: str, label: str) -> str:
    matched = re.search(rf"^{re.escape(label)}：(.+)$", card or "", re.M)
    value = matched.group(1).strip() if matched else ""
    return "" if value in {"", "未提供"} else value


def _card_is_thin(text: str) -> bool:
    body = text or ""
    if not body.startswith("精灵："):
        return True
    if "说法不一致" in body or "属性：未提供" in body:
        return True
    return bool(re.search(r"还没读到：[^。]*技能池", body))


def _wiki_card(name: str, html: str) -> str:
    """从洛克王国世界图鉴页抽出和名录一样的栏目。标签和首领化留空。"""
    ident = re.search(r'class="roco-ident-types">(.*?)</div>', html or "")
    types = []
    for kind in re.findall(r'data-type="([^"]+)"', ident.group(1) if ident else ""):
        if kind and kind not in types and kind not in {"无", "无系别"}:
            types.append(kind)
    feature = ""
    feature_name = re.search(r'class="roco-feature-name">([^<]+)', html or "")
    feature_desc = re.search(r'class="roco-feature-desc">(.*?)</div>', html or "", re.S)
    if feature_name:
        feature = feature_name.group(1).strip()
        if feature_desc:
            detail = re.sub(r"<[^>]+>", "", feature_desc.group(1))
            detail = re.sub(r"\s+", "", detail).strip("。")
            if detail:
                feature = f"{feature}。{detail}。"
    stats = {}
    for label, value in re.findall(r'class="roco-stat-name">([^<]+)</span>.*?data-val="(\d+)"', html or ""):
        if label not in stats:
            stats[label] = value
    stat_line = ""
    if stats.get("生命"):
        stat_line = (
            f"生命 {stats.get('生命', '未提供')}，"
            f"物攻 {stats.get('攻击', '未提供')}，"
            f"魔攻 {stats.get('魔攻', '未提供')}，"
            f"物防 {stats.get('物防', '未提供')}，"
            f"魔防 {stats.get('魔防', '未提供')}，"
            f"速度 {stats.get('速度', '未提供')}"
        )
    native, stone, blood = [], [], []
    seen = set()
    for chunk in (html or "").split('class="roco-sk-card"')[1:]:
        piece = chunk[:2400]
        source = re.search(r'data-source="(level|machine|blood|legendary)"', piece)
        skill = re.search(r'class="roco-sk-name">([^<]+)', piece)
        level = re.search(r'class="roco-sk-lv">([^<]*)', piece)
        if not source or not skill:
            continue
        skill_name = skill.group(1).strip()
        key = (source.group(1), skill_name)
        if not skill_name or key in seen:
            continue
        seen.add(key)
        mark = (level.group(1).strip() if level else "")
        if source.group(1) == "blood":
            kind = mark.replace("血脉·", "").strip()
            blood.append(f"{skill_name}｜{kind}血脉" if kind else skill_name)
        elif source.group(1) == "machine":
            stone.append(skill_name)
        else:
            native.append(f"{skill_name}｜{mark}" if mark.startswith("LV") else skill_name)
    evo_names = []
    for item in re.findall(r'class="roco-evo-name-main">(?:<a[^>]*>)?([^<]+)', html or ""):
        item = item.strip()
        if not item or item in evo_names:
            if evo_names:
                break
            continue
        evo_names.append(item)
    pills = [re.sub(r"<[^>]+>", "", item).strip() for item in re.findall(r'class="roco-evo-conn-pill">(.*?)</div>', html or "", re.S)]
    evolutions = []
    for index, form in enumerate(evo_names[1:], start=0):
        pill = pills[index] if index < len(pills) else ""
        if "首领" in pill:
            continue
        level = re.search(r"LV(\d+)", pill)
        evolutions.append(f"{level.group(1)}级{form}" if level else form)
        if len(evolutions) >= 4:
            break

    def join(items: list) -> str:
        shown = items[:20]
        text = "、".join(shown)
        if len(items) > len(shown):
            text += "等"
        return text

    lines = [
        f"精灵：{name}",
        f"属性：{'、'.join(types) or '未提供'}",
        "标签：未提供",
        f"特性：{feature or '未提供'}",
        f"种族值：{stat_line or '未提供'}",
        "首领化：未提供",
        f"自带：{join(native) or '未提供'}",
        f"技能石：{join(stone) or '未提供'}",
        f"血脉：{join(blood) or '未提供'}",
    ]
    if evolutions:
        lines.append("进化：" + "，".join(evolutions))
    missing = []
    if not types:
        missing.append("属性")
    if not feature:
        missing.append("特性")
    if not stat_line:
        missing.append("种族值")
    if not native and not stone and not blood:
        missing.append("技能池")
    gap = ("还没读到：" + "、".join(missing) + "。") if missing else "图鉴上的字段够讲这只精灵。"
    lines.append("证据：" + gap + "标签和首领化留空。")
    return "\n".join(lines)


def _wiki_lookup(name: str):
    """优先打开洛克王国世界图鉴里同名的一页。没有这一页就返回空。"""
    import json
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    from web_search import fetch_html

    title = (name or "").strip()
    if not title:
        return None
    api = "https://wiki.biligame.com/nrc/api.php?action=opensearch&limit=5&format=json&search=" + quote(title)
    page = ""
    try:
        with urlopen(Request(api, headers={"User-Agent": "Mozilla/5.0"}), timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", "replace") or "[]")
        for label, link in zip(payload[1], payload[3]):
            if label == title and "wiki.biligame.com" in link and "/nrc/" in link:
                page = link
                break
    except (OSError, json.JSONDecodeError, IndexError, TypeError, ValueError):
        page = ""
    if not page:
        return None
    html = fetch_html(page)
    if not html or "roco-ident-types" not in html or "无法确定精灵数据" in html:
        return None
    card = _wiki_card(title, html)
    if "属性：未提供" in card:
        return None
    return {"title": f"洛克王国世界图鉴·{title}", "url": page, "extract": card}


def _ace_label(question: str) -> str:
    matched = re.search(r"以\s*(.{1,16}?)\s*为\s*(?:核心|主力)", question or "")
    return matched.group(1).strip() if matched else ""


def _guest_ready(name: str, card: str) -> dict:
    skills = []
    for pool_name in ("自带", "技能石"):
        for item in re.split(r"[、，]", _card_field(card, pool_name)):
            short = item.split("｜")[0].strip()
            if short and short not in skills:
                skills.append(short)
            if len(skills) >= 4:
                break
        if len(skills) >= 4:
            break
    type_line = _card_field(card, "属性")
    if "不一致" in type_line:
        type_line = ""
    types = [part for part in re.split(r"[、，]", type_line) if part]
    if len(skills) < 4 or not types:
        return {}
    known = {"联防", "输出", "消强", "充能", "倾斜"}
    tags = [part for part in re.split(r"[、，]", _card_field(card, "标签")) if part in known]
    blood = "首领血脉" if _card_field(card, "首领化") == "是" else "初始血脉"
    return {"name": name, "types": types, "skills": skills[:4], "blood": blood, "tags": tags}


def ace_guest(question: str, session_id: str = ""):
    """点名的主力不在名录里时，用这段对话记下的精灵卡。卡片不够就说明排不成。"""
    from agents.chat_notebook import recall_pages, remember_page
    from pokemon_kb import _mentioned_names, load_pokemon

    label = _ace_label(question)
    if not label or _mentioned_names(label, load_pokemon()):
        return None
    pages = [page for page in recall_pages(session_id, label) if page.get("name") == label]
    card = present_outside_sprite(label, pages[0].get("text") or "") if pages else ""
    sources = (pages[0].get("sources") if pages else None) or []
    if _card_is_thin(card):
        wiki = _wiki_lookup(label)
        if wiki:
            card = wiki["extract"]
            sources = [{"title": wiki["title"], "url": wiki["url"]}]
            remember_page(session_id, label, card, sources)
            pages = recall_pages(session_id, label)
            card = present_outside_sprite(label, pages[0].get("text") or "") if pages else card
    ready = _guest_ready(label, card)
    if not ready:
        return {"blocked": outside_team_speech(label, card)}
    return ready


def outside_team_speech(name: str, card: str) -> str:
    """配队口吻。未知栏目用占位。缺了属性和技能池就说明排不成。"""
    type_line = _card_field(card, "属性")
    if "不一致" in type_line:
        type_line = ""
    pools = []
    for label in ("自带", "技能石", "血脉"):
        for item in re.split(r"[、，]", _card_field(card, label)):
            short = item.split("｜")[0].strip()
            if short and short not in pools:
                pools.append(short)
    bloods = [item for item in re.split(r"[、，]", _card_field(card, "血脉")) if item.strip()]
    blood = "未提供"
    if len(bloods) == 1 and "血脉" in bloods[0]:
        blood = bloods[0].split("｜")[-1].strip() or "未提供"
    skill_text = "、".join(pools[:4]) if pools else "未提供"
    line = f"{name}｜标签：未提供｜血脉：{blood}｜技能：{skill_text}"
    missing = []
    if not type_line:
        missing.append("属性")
    if skill_text == "未提供":
        missing.append("技能池")
    head = f"噔噔！灯灯想以{name}为核心排一套出场，还排不成。"
    if missing:
        reason = f"还没读到{'、'.join(missing)}。缺了这些就填不满四栏，灯灯先不记新的一套出场。"
    else:
        reason = f"属性是{type_line}。仓库里没有{name}，灯灯先不记新的一套出场。要是仓库里有它，就能以它为核心。"
    return f"{head}\n{line}\n{reason}标签和首领化留空。"


def _compress_extract(name: str, body: str) -> str:
    text = (body or "").strip()
    if not text or _OFF_GAME.search(text) or _PAGE_GAME.search(text):
        return ""
    kept = []
    seen = set()
    for piece in re.split(r"[。！？\n]", text):
        sent = piece.strip()
        if len(sent) < 8 or len(sent) > 160:
            continue
        if name and name not in sent and not any(word in sent for word in ("精灵", "技能", "属性", "进化", "特性", "获取")):
            continue
        if sent in seen:
            continue
        seen.add(sent)
        kept.append(sent)
        if sum(len(item) for item in kept) > 420:
            break
    return "。".join(kept[:5])


def _gather_web(question: str, plan: dict) -> dict:
    from agents.rag_agent import _leftover_name
    from pokemon_kb import load_pokemon
    from web_search import extract_pages, search_web

    subject = _leftover_name(question, load_pokemon())
    wiki = _wiki_lookup(subject) if subject else None
    if wiki:
        return {"reason": "ok", "results": [wiki], "detail": f"读了 {wiki['title']}"}
    found = []
    seen = set()
    detail = "没有查到网页"
    for query in _web_queries(question, plan):
        outcome = search_web(query, limit=5)
        if outcome.get("reason") == "no_key":
            return {"reason": "no_key", "results": [], "detail": "未配置密钥"}
        if outcome.get("reason") == "error" and not found:
            detail = outcome.get("detail") or "没有查到网页"
        for item in outcome.get("results") or []:
            url = item.get("url") or ""
            blob = f"{item.get('title') or ''} {item.get('snippet') or ''}"
            if not url or url in seen or not _on_game_page(item):
                continue
            if subject and subject not in blob:
                continue
            seen.add(url)
            found.append({"title": item.get("title") or url, "url": url, "snippet": item.get("snippet") or ""})
            if len(found) >= 5:
                break
        if len(found) >= 5:
            break
    if not found:
        return {"reason": "empty", "results": [], "detail": detail}
    found.sort(key=_page_rank)
    pages = extract_pages([item["url"] for item in found[:2]])
    kept = []
    for item in found:
        if len(kept) >= 2:
            break
        raw = pages.get(item["url"]) or item.get("snippet") or ""
        brief = _compress_extract(subject, raw)
        if not brief:
            continue
        item["extract"] = brief
        kept.append(item)
    if not kept:
        return {"reason": "empty", "results": [], "detail": "打开了页面，没读出可用正文"}
    titles = "、".join(item["title"][:18] for item in kept)
    return {"reason": "ok", "results": kept, "detail": f"读了 {titles}"}


def _append_web_sources(answer: str, web_results: list) -> str:
    if not web_results:
        return answer
    lines = ["", "来源"]
    for item in web_results:
        title = (item.get("title") or "网页").replace("｜", " ")
        url = item.get("url") or ""
        if url:
            lines.append(f"{title}｜{url}")
    return (answer or "").rstrip() + "\n" + "\n".join(lines)


def _matchup_pair(question: str):
    """问句里点了两只，并且在问输赢。顺序按原句里先出现的名字。"""
    text = question or ""
    if not re.search(r"对战|谁会赢|谁赢|打得过", text):
        return None
    from pokemon_kb import _mentioned_names, _name_stem, load_pokemon

    names = []
    for name in _mentioned_names(text, load_pokemon()):
        if name not in names:
            names.append(name)
    if len(names) < 2:
        return None

    def position(name: str) -> int:
        stem = _name_stem(name)
        spots = [text.find(token) for token in (name, stem) if token and token in text]
        return min(spots) if spots else len(text)

    ranked = sorted(names, key=position)
    return ranked[0], ranked[1]


def _bout_payload(left: str, right: str):
    from agents.dengdeng_persona import matchup_spoken
    from battle import scripted_bout

    bout = scripted_bout(left, right)
    if not bout.get("ok") or not bout.get("frames"):
        return None
    return {
        "sprite_a": left,
        "sprite_b": right,
        "winner": bout.get("winner") or "",
        "spoken": matchup_spoken(left, right, bout.get("winner") or ""),
        "lines": bout.get("lines") or [],
        "frames": bout.get("frames") or [],
        "ok": True,
    }


def _trial_view(battle: dict) -> dict:
    return {
        "intro": "灯灯来想一想，这两只精灵对战会是什么情况呢，让灯灯来模拟一下。",
        "closing": battle.get("spoken") or "",
        "frames": battle.get("frames") or [],
        "pace_ms": 2000,
    }


def _looks_like_call(text: str) -> bool:
    body = text or ""
    return '"name"' in body and '"arguments"' in body


def _clean_voice(text: str, fallback: str) -> str:
    from agents.dengdeng_persona import contains_banned

    body = (text or "").strip()
    if not body or contains_banned(body) or _looks_like_call(body):
        return fallback
    return body


def _safe_fallback(structured: dict) -> str:
    from agents.dengdeng_persona import contains_banned, wrap_facts

    spoken = (structured.get("spoken_seed") or "").strip()
    if spoken and not contains_banned(spoken):
        return spoken
    wrapped = wrap_facts(_hide_paths(structured.get("answer") or ""))
    if wrapped and not contains_banned(wrapped):
        return wrapped
    return "噔噔！灯灯在洛克百科中翻到了这些，讲给小洛克听。"


def _attach_prompt_fc(question: str, structured: dict, hits: list) -> dict:
    """图鉴已经查完。开战只认模型输出的函数 JSON，不在这里用谁赢正则。"""
    try:
        from agents.prompt_function_calling import run_prompt_fc
        fc = run_prompt_fc(question, mode="search")
    except Exception as exc:
        logger.warning("prompt fc unavailable: %s", type(exc).__name__)
        return {}
    battle = fc.get("battle") or None
    if not battle or not battle.get("spoken"):
        return fc
    from agents.dengdeng_persona import contains_banned, matchup_spoken

    spoken = battle.get("spoken") or ""
    if contains_banned(spoken):
        spoken = matchup_spoken(battle.get("sprite_a") or "", battle.get("sprite_b") or "", battle.get("winner") or "")
    hits.append({
        "title": "试场",
        "source": "knowledge/rules.md",
        "kind": "matchup",
        "text": _hide_paths(spoken + "\n" + "\n".join(battle.get("lines") or [])),
        "photo_name": "",
    })
    structured["spoken_seed"] = spoken
    structured["answer"] = ((structured.get("answer") or "").rstrip() + "\n\n" + spoken).strip()
    must = list(structured.get("must_names") or [])
    for name in (battle.get("sprite_a"), battle.get("sprite_b")):
        if name and name not in must:
            must.append(name)
    structured["must_names"] = must
    tokens = list(structured.get("must_tokens") or [])
    for token in ("不是你们亲自点的那盘", "赢"):
        if token not in tokens:
            tokens.append(token)
    structured["must_tokens"] = tokens
    battle["spoken"] = spoken
    return fc


def present_outside_sprite(name: str, text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("精灵："):
        return raw
    return _sprite_card(name or "这只精灵", [raw])


def _notebook_card(question: str, pages: list) -> dict:
    parts = []
    sources = []
    for page in pages:
        name = page.get("name") or "这只精灵"
        body = present_outside_sprite(name, page.get("text") or "")
        page["text"] = body
        parts.append(f"【{name}】\n{body}")
        for item in page.get("sources") or []:
            title = item.get("title") or ""
            if name not in title and "世界" not in title:
                continue
            if item not in sources:
                sources.append(item)
    answer = "噔噔！灯灯按这段对话里记下的精灵卡来讲。\n\n" + "\n\n".join(parts)
    return {"answer": answer, "sources": sources}


def _store_web_page(session_id: str, question: str, web_results: list) -> None:
    if not session_id or not web_results:
        return
    from agents.chat_notebook import remember_page
    from agents.rag_agent import _leftover_name
    from pokemon_kb import load_pokemon

    name = _leftover_name(question, load_pokemon())
    if not name:
        return
    chunks = []
    kept = []
    for item in web_results[:2]:
        url = item.get("url") or ""
        if any(host in url for host in ("youtube.com", "youtu.be")):
            continue
        piece = (item.get("extract") or item.get("snippet") or "").strip()
        if piece and not _OFF_GAME.search(piece):
            chunks.append(piece)
            kept.append({"title": item.get("title") or "", "url": item.get("url") or ""})
    if not chunks:
        return
    card = chunks[0] if chunks[0].startswith("精灵：") else _sprite_card(name, chunks)
    remember_page(session_id, name, card, kept)


def run_knowledge_search(question: str, report, use_web: bool = False, session_id: str = "") -> dict:
    """先拆问题。胜负题去模拟对战，名录里没有的名字直接说没翻到，其余再查本地。"""
    text = (question or "").strip()
    from agents.chat_notebook import learn, recall_pages, style_sentence
    from agents.rag_agent import search_preface
    from agents.thoughts import note_thought

    fresh = learn(session_id, text)
    if fresh:
        note_thought("灯灯记下你的规矩了")
    report("parse", "running", "", "正在理解问题…")
    preface = search_preface(text)
    remembered = recall_pages(session_id, text)
    from pokemon_kb import _mentioned_names, load_pokemon

    known = _mentioned_names(text, load_pokemon())
    outside_pages = [page for page in remembered if page.get("name") not in set(known)]
    if outside_pages and not known and preface.get("action") != "trial":
        refreshed = False
        if use_web:
            from agents.chat_notebook import remember_page

            for page in outside_pages:
                label = page.get("name") or ""
                if not _card_is_thin(page.get("text") or ""):
                    continue
                wiki = _wiki_lookup(label)
                if not wiki:
                    continue
                page["text"] = wiki["extract"]
                page["sources"] = [{"title": wiki["title"], "url": wiki["url"]}]
                remember_page(session_id, label, wiki["extract"], page["sources"])
                refreshed = True
        remembered = outside_pages
        card = _notebook_card(text, remembered)
        names = "、".join(page.get("name") or "" for page in remembered if page.get("name"))
        report("parse", "done", f"这段对话里已经有{names}", "正在按记下的资料讲…")
        report("lookup", "done", f"命中{names}", "正在按记下的资料讲…")
        if refreshed:
            report("web", "done", "读了洛克王国世界图鉴", "正在按记下的资料讲…")
        else:
            report("web", "skip", "这段对话里已经有了", "正在按记下的资料讲…")
        for step_id in ("index", "retrieve"):
            report(step_id, "skip", "这段对话里已经有了", "正在按记下的资料讲…")
        from agents.chat_notebook import remember_page

        for page in remembered:
            remember_page(session_id, page.get("name") or "", page.get("text") or "", page.get("sources") or [])
        answer = card["answer"]
        habit = style_sentence(session_id)
        if habit and habit not in answer:
            answer = answer.rstrip() + "\n\n" + habit
        answer = _append_web_sources(answer, card["sources"])
        report("generate", "done", "灯灯按这段对话里记下的讲", "正在合并结果…")
        report("done", "done", "用的是这段对话里的资料", "检索完成")
        return {
            "found": True,
            "answer": answer,
            "hits": [{"title": page.get("name") or "", "text": page.get("text") or "", "source": "这段对话"} for page in remembered],
            "sources": ["这段对话"],
            "web_sources": [{"title": item.get("title") or "", "url": item.get("url") or ""} for item in card["sources"]],
            "trial": None,
        }
    if preface.get("action") == "empty" and not use_web:
        report("parse", "done", "没有可查的名字", "检索完成")
        for step_id in ("lookup", "web", "index", "retrieve", "generate"):
            report(step_id, "skip", "这一问不用再查" if step_id != "web" else "未开启联网", "检索完成")
        report("done", "done", "没有翻到", "检索完成")
        return {
            "found": False,
            "answer": preface.get("answer") or "灯灯没有翻到相关信息。",
            "hits": [],
            "sources": [],
            "web_sources": [],
            "trial": None,
        }
    if preface.get("action") == "trial" and preface.get("trial"):
        report("parse", "done", "这是在问输赢", "灯灯开始模拟这场对战")
        for step_id in ("lookup", "web", "index", "retrieve"):
            report(step_id, "skip", "改去模拟对战", "灯灯开始模拟这场对战")
        report("generate", "done", "灯灯开始模拟这场对战", "正在合并结果…")
        report("done", "done", "模拟对战", "检索完成")
        return {
            "found": True,
            "answer": preface["trial"]["intro"],
            "hits": [],
            "sources": [],
            "web_sources": [],
            "trial": preface["trial"],
        }

    outside_only = preface.get("action") == "empty"
    if outside_only:
        report("parse", "done", "没有可查的名字", "灯灯到外面看一眼")
        plan = {
            "intent": "unknown",
            "queries": [text],
            "names": [],
            "skills": [],
            "plates": [],
            "focus": "",
            "need_rag": False,
        }
        structured = {
            "found": False,
            "answer": preface.get("answer") or "灯灯没有翻到相关信息。",
            "hits": [],
            "must_names": [],
            "must_tokens": [],
            "intent": "unknown",
        }
        report("lookup", "skip", "名录里没有", "灯灯到外面看一眼")
        retrieved = []
        hits = []
        report("index", "skip", "名录里没有", "灯灯到外面看一眼")
        report("retrieve", "skip", "名录里没有", "灯灯到外面看一眼")
    else:
        plan = plan_query(text, allow_model=True)
        report("parse", "done", _parse_detail(plan), "正在按意图查找…")

        report("lookup", "running", "", "正在按意图查找…")
        structured = lookup_by_plan(text, plan)
        report("lookup", "done", _lookup_detail(text, structured), "正在准备知识索引…")

        query = _retrieve_query(text, plan)
        focused = plan.get("focus") in {"skill", "pool", "damage"}
        if focused:
            retrieved = []
            report("index", "skip", "按类别查", "正在合并类别结果…")
            report("retrieve", "skip", "按类别查", "正在根据资料生成回答…")
        else:
            report("index", "running", "", "正在准备知识索引…")
            retrieved, retrieve_status, retrieve_detail, index_state = retrieve_passages(query)
            if index_state == "reuse":
                report("index", "skip", "复用已有索引", "正在召回资料片段…")
            elif index_state == "built":
                report("index", "done", "已建成检索专用索引", "正在召回资料片段…")
            else:
                report("index", "skip", "向量库未就绪", "向量库未就绪，沿用结构化结果")
            if retrieve_status == "done":
                report("retrieve", "done", retrieve_detail, "正在根据资料生成回答…")
            else:
                report("retrieve", "skip", retrieve_detail or "向量不可用，未召回", "正在合并结果…")
        hits = _merge_hits(structured.get("hits") or [], retrieved)

    web_results = []
    web_reason = "off"
    if hits:
        report("web", "skip", "百科已经有了" if use_web else "未开启联网", "正在根据资料生成回答…")
    elif not use_web:
        report("web", "skip", "未开启联网", "正在根据资料生成回答…")
    else:
        report("web", "running", "", "正在联网搜寻…")
        gathered = _gather_web(text, plan)
        web_reason = gathered.get("reason") or "empty"
        web_results = gathered.get("results") or []
        if web_reason == "no_key":
            report("web", "skip", "未配置密钥", "正在根据资料生成回答…")
        elif web_results:
            report("web", "done", gathered.get("detail") or f"{len(web_results)} 条", "正在根据资料生成回答…")
            if outside_only:
                _store_web_page(session_id, text, web_results)
        else:
            report("web", "skip", gathered.get("detail") or "没有查到网页", "正在根据资料生成回答…")

    fc = _attach_prompt_fc(text, structured, hits)
    battle = (fc or {}).get("battle") or {}
    if not battle.get("frames"):
        pair = _matchup_pair(text)
        if pair:
            battle = _bout_payload(*pair) or {}
    trial = _trial_view(battle) if battle.get("frames") else None
    fallback_voice = _safe_fallback(structured)
    local_answer = (structured.get("answer") or "").strip()
    generated = ""
    if trial:
        generated = trial["intro"]
        report("generate", "done", "灯灯开始模拟这场对战", "正在合并结果…")
    elif plan.get("focus") in {"skill", "pool", "damage"} and local_answer and local_answer != "知识库没有这项资料。":
        from agents.dengdeng_persona import wrap_facts

        generated = wrap_facts(local_answer)
        report("generate", "done", "灯灯按翻到的类别讲", "正在合并结果…")
    elif not hits and web_results:
        chunks = [item.get("extract") or "" for item in web_results if item.get("extract")]
        from agents.rag_agent import _leftover_name
        from pokemon_kb import load_pokemon

        subject = _leftover_name(text, load_pokemon()) or "这只精灵"
        ready = next((item for item in chunks if item.startswith("精灵：")), "")
        if ready:
            generated = "噔噔！名录里没有这只。灯灯按精灵卡的栏目，把外面读到的收成下面这样。\n\n" + ready
            report("generate", "done", "灯灯按读到的正文讲", "正在合并结果…")
        elif chunks:
            generated = "噔噔！名录里没有这只。灯灯按精灵卡的栏目，把外面读到的收成下面这样。\n\n" + _sprite_card(subject, chunks)
            report("generate", "done", "灯灯按读到的正文讲", "正在合并结果…")
        else:
            miss = (preface.get("answer") or "").strip() if outside_only else "灯灯在洛克百科里没翻到这个。"
            generated = (miss or "灯灯在洛克百科里没翻到这个。") + "\n\n灯灯打开了页面，没读出可用正文。"
            report("generate", "done", "没读出正文", "正在合并结果…")
    elif not hits and not web_results and not battle:
        from agents.dengdeng_persona import pick_cry

        generated = pick_cry()
        report("generate", "done", "没有可引用的资料", "正在合并结果…")
    elif fc.get("json_only"):
        generated = fallback_voice
        report("generate", "done", "灯灯改用试场或百科口吻", "正在合并结果…")
    else:
        report("generate", "running", "", "灯灯正在把资料说给小洛克听…")
        try:
            web_for_voice = [] if hits else web_results
            generated = _clean_voice(_generate_answer(text, hits, web_for_voice, structured), fallback_voice)
            report("generate", "done", "灯灯已根据给定资料作答", "正在合并结果…")
        except TimeoutError:
            generated = fallback_voice
            report("generate", "skip", "等待模型超时，灯灯改讲自己记得的", "正在合并结果…")
        except Exception as exc:
            logger.warning("检索生成失败: %s", type(exc).__name__)
            generated = fallback_voice
            report("generate", "skip", "模型不可用，灯灯改讲自己记得的", "正在合并结果…")

    if generated:
        answer = generated
    elif hits and local_answer and local_answer != "知识库没有这项资料。":
        from agents.dengdeng_persona import wrap_facts

        answer = wrap_facts(local_answer)
    elif web_results and not hits:
        answer = "灯灯在洛克百科里没翻到这个。外面的话只当背景，不是游戏里的种族值或技能效果。"
    elif not hits:
        answer = "灯灯没有翻到相关信息。"
    else:
        from agents.dengdeng_persona import pick_cry

        answer = pick_cry()
    if web_reason == "no_key":
        answer = answer.rstrip() + "\n\n灯灯这次没有到外面去看。"
    if not hits:
        answer = _append_web_sources(answer, web_results)
    note = (preface or {}).get("note") or ""
    if note and note not in answer:
        answer = answer.rstrip() + "\n\n" + note
    sources = _sources_of(hits)
    report("done", "done", f"合并 {len(hits)} 条资料", "检索完成")
    return {
        "found": bool(hits) or bool(web_results),
        "answer": answer,
        "hits": hits,
        "sources": sources,
        "web_sources": [] if hits else [{"title": item["title"], "url": item["url"]} for item in web_results],
        "trial": trial,
    }
