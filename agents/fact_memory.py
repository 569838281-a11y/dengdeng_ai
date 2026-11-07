"""可更新事实记忆。

工作记忆仍是最近对话，由块挑选保留。
长期事实来自这段对话里对精灵栏目的修改：同一只、同一栏，后一次覆盖前一次。
外号和原名指向同一只。同一套出场只记成队友，不记成对手或核心伙伴。
检索把三项加在一起：实体是否被问到、栏目词是否出现、问句和事实的字面相关度。
问到的那只精灵的修改是汇点，预算不够也不能丢。不写名录。
"""
import re

from agents.kv_blocks import make_block, qk_scores

_SLOT = re.compile(r"第[一二三四五六1-6]位是([^，。]{1,24})")
_LINEUP_ASK = re.compile(r"队伍|出场|队友|一起|和谁|谁和|伙伴|对手")
_PROFILE = re.compile(
    r"具体信息|具体资料|全部信息|所有信息|全部资料|详细信息|都讲讲|介绍一下|"
    r"的属性|的技能|的种族值|的特性|的血脉|的标签|的首领化|的资料|的信息"
)


def _book(session_id: str) -> dict:
    from agents.chat_notebook import _LOCK, _BOOKS, _load_locked

    sid = (session_id or "").strip()
    if not sid:
        return {}
    with _LOCK:
        _load_locked()
        book = _BOOKS.get(sid) or {}
        return {
            "patches": dict(book.get("patches") or {}),
        }


def list_facts(session_id: str) -> list:
    """把记事里的栏目修改摊成事实。一条事实只描述一只精灵的一个栏目。"""
    facts = []
    for entity, patch in _book(session_id)["patches"].items():
        if not entity or not isinstance(patch, dict):
            continue
        for field, value in patch.items():
            text_value = str(value or "").strip()
            if not text_value:
                continue
            facts.append({
                "id": f"fact-{entity}-{field}",
                "entity": entity,
                "field": field,
                "value": text_value,
                "text": f"{entity}的{field}是{text_value}",
            })
    return facts


def _entity_hit(question: str, fact: dict) -> float:
    return 1.0 if fact["entity"] and fact["entity"] in (question or "") else 0.0


def _keyword_hit(question: str, fact: dict) -> float:
    text = question or ""
    if fact["field"] and fact["field"] in text:
        return 1.0
    if fact["field"] == "属性" and "系" in text:
        return 0.5
    return 0.0


def rank_facts(question: str, facts: list) -> list:
    """实体 1.5、栏目词 1.0、问句相关度三者相加。返回带分数的事实，高分在前。"""
    if not facts:
        return []
    blocks = [
        make_block(fact["id"], "长期记忆", fact["text"], entities=[fact["entity"]])
        for fact in facts
    ]
    lexical = qk_scores(question, blocks, [])
    ranked = []
    for fact, lexical_score in zip(facts, lexical):
        entity = _entity_hit(question, fact)
        keyword = _keyword_hit(question, fact)
        score = 1.5 * entity + keyword + lexical_score
        item = dict(fact)
        item["score"] = score
        item["entity_hit"] = entity
        item["keyword_hit"] = keyword
        item["lexical"] = lexical_score
        ranked.append(item)
    ranked.sort(key=lambda fact: fact["score"], reverse=True)
    return ranked


def roster_members(text: str) -> list:
    """从一套出场的句子里取出六位队友。没有套号或不足两位就不当成出场。"""
    body = text or ""
    if not re.search(r"第\s*\d+\s*套", body):
        return []
    names = []
    for match in _SLOT.finditer(body):
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names if len(names) >= 2 else []


def teammate_sentence(names: list) -> str:
    shown = "、".join(name for name in names if name)
    return f"同一套出场的队友是{shown}。他们只是一起出场。"


def is_sprite_profile(question: str) -> bool:
    return bool(_PROFILE.search(question or ""))


def asks_lineup(question: str) -> bool:
    return bool(_LINEUP_ASK.search(question or ""))


def absorb_history(session_id: str, history) -> None:
    """把已经说过的出场收成队友名单。同一组只留一份。"""
    from agents.chat_notebook import remember_lineup

    if not (session_id or "").strip():
        return
    for message in history or []:
        if not isinstance(message, dict) or message.get("role") == "user":
            continue
        names = roster_members(str(message.get("content") or ""))
        if names:
            remember_lineup(session_id, names)


def _relation_facts(session_id: str, question: str) -> list:
    from agents.chat_notebook import alias_map, lineups_of

    facts = []
    for alias, canonical in alias_map(session_id).items():
        facts.append({
            "id": f"alias-{alias}",
            "entity": canonical,
            "field": "叫法",
            "value": alias,
            "text": f"{alias}就是{canonical}，两个叫法是同一只",
        })
    if is_sprite_profile(question) and not asks_lineup(question):
        return facts
    for names in lineups_of(session_id):
        if asks_lineup(question) and not any(name in (question or "") for name in names):
            continue
        facts.append({
            "id": "lineup-" + "-".join(names),
            "entity": names[0],
            "field": "队友",
            "value": "、".join(names),
            "text": teammate_sentence(names),
        })
    return facts


def soften_relations(question: str, blocks: list) -> list:
    """问一只精灵的资料时，不把同队名单塞进这一轮。问出场时，改写成队友。"""
    profile = is_sprite_profile(question) and not asks_lineup(question)
    prepared = []
    for block in blocks or []:
        names = roster_members(block.get("text") or "")
        if len(names) < 2:
            prepared.append(block)
            continue
        if profile:
            continue
        prepared.append(make_block(
            block.get("id") or "lineup",
            block.get("source") or "对话",
            teammate_sentence(names),
            role=block.get("role") or "",
            entities=names,
            sink=asks_lineup(question),
            importance=block.get("importance") or 0,
        ))
    return prepared


_VAGUE = re.compile(r"^(?:好的|随便|那支很强|很强|不错|不知道|嗯+|哦+)[。！]?$")
_REWRITE = re.compile(r"(技能|特性|种族值).{0,8}(改成|改为|写成|覆盖|是|为)")
_COUNT = re.compile(r"[一二三四五六七八九十两几\d]+\s*只")


def concrete_composition(text: str) -> bool:
    """具体到能继续找位子：点了名、点了属性，或说了打法。"""
    body = text or ""
    if "系" in body or "印记" in body or "打法" in body:
        return True
    from pokemon_kb import _mentioned_names, load_pokemon

    return bool(_mentioned_names(body, load_pokemon()))


def composition_types(text: str) -> list:
    from pokemon_kb import _TYPE_ORDER

    found = []
    for kind in _TYPE_ORDER:
        if f"{kind}系" in (text or "") and kind not in found:
            found.append(kind)
    return found


def admit_utterance(session_id: str, text: str, gap: dict) -> dict:
    """先判断这句能不能填上当前缺口。能填才写入这段对话，来源标成玩家。"""
    body = (text or "").strip()
    label = str((gap or {}).get("label") or "").strip()
    kind = str((gap or {}).get("kind") or "").strip()
    if not gap or not label:
        return {"keep": False, "reason": "这句话对不上还空着的资料", "text": ""}
    if not body or _VAGUE.match(body):
        return {"keep": False, "reason": f"这句话太含糊，还缺{label}", "text": ""}
    if _REWRITE.search(body):
        return {"keep": False, "reason": "不能改写名录里的技能、特性和克制", "text": ""}
    if kind == "count":
        if not _COUNT.search(body):
            return {"keep": False, "reason": "还缺要改的只数", "text": ""}
    elif kind in {"composition", "identity", "meta"}:
        if not concrete_composition(body):
            return {"keep": False, "reason": f"还缺{label}的组成和打法", "text": ""}
    else:
        return {"keep": False, "reason": f"这句话对不上{label}", "text": ""}
    from agents.chat_notebook import remember_admitted

    remember_admitted(session_id, body, label)
    return {"keep": True, "reason": "", "text": body}


def fact_blocks(session_id: str, question: str) -> list:
    """收成长期记忆块。问句点到的精灵，其修改和外号强制留下。"""
    blocks = []
    facts = list_facts(session_id) + _relation_facts(session_id, question)
    for fact in rank_facts(question, facts):
        mentioned = fact["entity_hit"] > 0 or fact["field"] == "叫法" and (
            fact["value"] in (question or "") or fact["entity"] in (question or "")
        )
        if fact["field"] == "队友":
            mentioned = asks_lineup(question) and any(
                name in (question or "") for name in str(fact["value"]).split("、")
            )
        blocks.append(make_block(
            fact["id"],
            "长期记忆",
            fact["text"],
            entities=[fact["entity"]],
            sink=mentioned,
            importance=fact["score"],
        ))
    from agents.chat_notebook import admitted_of

    for index, item in enumerate(admitted_of(session_id), 1):
        label = item.get("label") or ""
        said = item.get("text") or ""
        if not said:
            continue
        blocks.append(make_block(
            f"admit-{index}",
            "玩家",
            f"玩家补充的{label}：{said}",
            entities=[label] if label else [],
            sink=bool(label) and label in (question or ""),
            importance=0.9,
        ))
    return blocks
