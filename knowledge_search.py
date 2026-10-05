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


def find_rules(question: str, intent: str) -> list:
    """板块节选。技能表只在意图是 skills 时抽取，避免把系别技能表当成精灵名单。"""
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
    for prefix in _detect_plates(question):
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
        hits = find_rules(text, intent)
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
        "need_rag": True,
        "source": "rules",
    }
    if names:
        plan["intent"] = "lookup_one"
        plan["skills"] = []
        return plan
    if skills:
        plan["intent"] = "lookup_skill"
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


def plan_query(question: str, allow_model: bool = False) -> dict:
    plan = _plan_by_rules(question)
    if plan["intent"] != "unknown":
        return plan
    if allow_model:
        modeled = _plan_with_model(question)
        if modeled:
            return modeled
    return plan


def _parse_detail(plan: dict) -> str:
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
    body = answer or ""
    if "##" in body or "```" in body or body.lstrip().startswith("#"):
        return False
    if "灯灯" not in body or "小洛克" not in body:
        return False
    source = structured.get("answer") or ""
    if "更可能获胜" in source and "更可能获胜" not in body:
        return False
    if "不是模拟赛" in source and "不是模拟赛" not in body:
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
    summary = (facts.get("answer") or "").strip()
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


def _web_queries(question: str, plan: dict) -> list:
    queries = []

    def add(value: str) -> None:
        text = (value or "").strip()
        if text and text not in queries:
            queries.append(text)

    add(question)
    for name in (plan.get("names") or [])[:3]:
        add(name)
    for skill in (plan.get("skills") or [])[:3]:
        add(skill)
    return queries[:4]


def _gather_web(question: str, plan: dict) -> dict:
    from urllib.parse import urlparse
    from web_search import search_web

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
            if not url or url in seen:
                continue
            seen.add(url)
            found.append({"title": item.get("title") or url, "url": url, "snippet": item.get("snippet") or ""})
            if len(found) >= 5:
                break
        if len(found) >= 5:
            break
    if not found:
        return {"reason": "empty", "results": [], "detail": detail}
    hosts = []
    for item in found:
        host = (urlparse(item["url"]).hostname or "").removeprefix("www.")
        if host and host not in hosts:
            hosts.append(host)
    host_text = "、".join(hosts[:3])
    return {"reason": "ok", "results": found, "detail": f"{len(found)} 条，{host_text}" if host_text else f"{len(found)} 条"}


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


def run_knowledge_search(question: str, report, use_web: bool = False) -> dict:
    """理解意图后查本地资料，再尽量用专用索引补片段。report(step_id, status, detail, message)。"""
    text = (question or "").strip()
    report("parse", "running", "", "正在理解问题…")
    plan = plan_query(text, allow_model=True)
    report("parse", "done", _parse_detail(plan), "正在按意图查找…")

    report("lookup", "running", "", "正在按意图查找…")
    structured = lookup_by_plan(text, plan)
    report("lookup", "done", _lookup_detail(text, structured), "正在准备知识索引…")

    web_results = []
    web_reason = "off"
    if not use_web:
        report("web", "skip", "未开启联网", "正在准备知识索引…")
    else:
        report("web", "running", "", "正在联网搜寻…")
        gathered = _gather_web(text, plan)
        web_reason = gathered.get("reason") or "empty"
        web_results = gathered.get("results") or []
        if web_reason == "no_key":
            report("web", "skip", "未配置密钥", "正在准备知识索引…")
        elif web_results:
            report("web", "done", gathered.get("detail") or f"{len(web_results)} 条", "正在准备知识索引…")
        else:
            report("web", "skip", gathered.get("detail") or "没有查到网页", "正在准备知识索引…")

    query = _retrieve_query(text, plan)
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

    if plan.get("intent") == "matchup":
        hits = list(structured.get("hits") or [])
    else:
        hits = _merge_hits(structured.get("hits") or [], retrieved)
    generated = ""
    if not hits and not web_results:
        from agents.dengdeng_persona import pick_cry

        generated = pick_cry()
        report("generate", "done", "没有可引用的资料", "正在合并结果…")
    else:
        report("generate", "running", "", "灯灯正在把资料说给小洛克听…")
        try:
            generated = _generate_answer(text, hits, web_results, structured)
            report("generate", "done", "灯灯已根据给定资料作答", "正在合并结果…")
        except TimeoutError:
            from agents.dengdeng_persona import wrap_facts

            generated = wrap_facts(structured.get("answer") or "")
            report("generate", "skip", "等待模型超时，灯灯改讲自己记得的", "正在合并结果…")
        except Exception as exc:
            from agents.dengdeng_persona import wrap_facts

            logger.warning("检索生成失败: %s", exc)
            generated = wrap_facts(structured.get("answer") or "")
            report("generate", "skip", "模型不可用，灯灯改讲自己记得的", "正在合并结果…")

    local_answer = (structured.get("answer") or "").strip()
    if generated:
        answer = generated
    elif hits and local_answer and local_answer != "知识库没有这项资料。":
        from agents.dengdeng_persona import wrap_facts

        answer = wrap_facts(local_answer)
    elif web_results:
        answer = "灯灯在洛克百科里没翻到这个。外面的话只当背景，不是游戏里的种族值或技能效果。"
    else:
        from agents.dengdeng_persona import pick_cry

        answer = pick_cry()
    if web_reason == "no_key":
        answer = answer.rstrip() + "\n\n未配置搜索密钥，本次没有联网。"
    answer = _append_web_sources(answer, web_results)
    sources = _sources_of(hits)
    report("done", "done", f"合并 {len(hits)} 条资料", "检索完成")
    return {
        "found": bool(hits) or bool(web_results),
        "answer": answer,
        "hits": hits,
        "sources": sources,
        "web_sources": [{"title": item["title"], "url": item["url"]} for item in web_results],
    }
