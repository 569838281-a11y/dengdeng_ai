"""Mem0 抽出并更新事实，Letta 把最近几条放在手头，Graphiti 用时间把旧数字标成失效。

数字留在事实里。下次问到同一只的同一栏，用这条，不再回名录。
出场率冠军按谓词 appearance_rate_top1 写入 archival（MemGPT 式按需召回）。
"""
import re
import time

_FIELDS = ("种族值", "技能", "克制", "特性", "属性")
_RATE_PRED = "appearance_rate_top1"
_RATE_SOURCE = "出场率"
_CORE_BUDGET = 180
_SKIP = ("没想起", "没翻到", "没有翻到", "跟灯灯说一下", "暂时不敢", "不敢认定")


def clear_memory(session_id: str) -> None:
    """测试或换会话时清空 archival / core。"""
    sid = (session_id or "").strip()
    if not sid:
        return
    from agents.chat_notebook import _LOCK, _book, _save_locked

    with _LOCK:
        book = _book(sid)
        book["memory"] = {"edges": [], "core": []}
        _save_locked()


def absorb_exchange(session_id: str, question: str, answer: str) -> list:
    """一轮说完后抽出事实。新的加上，同一栏数字变了就让旧的失效。"""
    if not (session_id or "").strip():
        return []
    events = []
    for fact in extract_facts(question, answer):
        events.append(_update(session_id, fact, question))
    return [item for item in events if item]


def extract_facts(question: str, answer: str) -> list:
    """从这一问和这一答里抽出带栏目的事实。数字留在取值里。"""
    body = (answer or "").strip()
    if not body or any(word in body for word in _SKIP):
        return []
    body = re.sub(r"^(灯灯翻到：|灯灯记得：|灯灯按你说的，)", "", body).strip()
    found = []
    pattern = re.compile(
        r"([\u4e00-\u9fffA-Za-z0-9（）()]{2,16})的(种族值|技能|克制|特性|属性)(?:是|为|：|:)\s*([^。\n]{1,80})"
    )
    for match in pattern.finditer(body):
        if match.group(3).strip() in {"多少", "什么", "谁", "哪些"}:
            continue
        found.append(_fact(match.group(1), match.group(2), match.group(3)))
    # 谓词：出场率最高的精灵是〔名录〕（Letta archival 可按谓词召回）
    rate_fact = _extract_rate_champion(body)
    if rate_fact:
        found.append(rate_fact)
    from pokemon_kb import _mentioned_names, load_pokemon

    names = []
    for name in _mentioned_names(question or "", load_pokemon()):
        if name not in names:
            names.append(name)
    field = next((label for label in _FIELDS if label in (question or "")), "")
    if len(names) == 1 and field and not any(
        item["source"] == names[0] and item["relation"] == field for item in found
    ):
        value = re.sub(r"\s+", " ", body)[:80].strip(" ，,。")
        if value and (re.search(r"\d", value) or field in {"技能", "克制", "特性", "属性"}):
            found.append(_fact(names[0], field, value))
    kept = []
    seen = set()
    for item in found:
        key = (item["source"], item["relation"], item["value"])
        if not item["value"] or key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def archival_memory_search(session_id: str, question: str) -> list:
    """还有效的边。问句里的精灵和栏目排在前面；出场率问优先谓词边。"""
    text = question or ""
    ranked = []
    rate_q = _rate_question(text)
    for edge in _valid(session_id):
        score = 0
        if rate_q and edge.get("relation") == _RATE_PRED:
            score += 5
        if edge.get("source") and edge["source"] in text:
            score += 2
        if edge.get("relation") and edge["relation"] in text:
            score += 2
        head = (edge.get("value") or "")[:12]
        if head and head in text:
            score += 1
        if score:
            item = dict(edge)
            item["score"] = score
            ranked.append(item)
    ranked.sort(key=lambda edge: (edge["score"], edge.get("valid_at") or 0), reverse=True)
    return ranked


def core_block(session_id: str) -> str:
    """手头这几条，给不检索的回答看。"""
    if not (session_id or "").strip():
        return ""
    lines = []
    for edge in _core_edges(session_id):
        if edge.get("text"):
            lines.append(edge["text"])
    return "\n".join(lines)


def recall_answer(session_id: str, question: str) -> str:
    """按栏目或出场率谓词召回。故事类问句不取精灵边（防串台）。"""
    text = question or ""
    try:
        from agents.story_read import is_persona_story

        if is_persona_story(text):
            return ""
    except Exception:
        pass
    if _rate_question(text):
        hits = [
            edge
            for edge in _valid(session_id)
            if edge.get("relation") == _RATE_PRED and (edge.get("text") or edge.get("value"))
        ]
        if hits:
            hits.sort(key=lambda edge: edge.get("valid_at") or 0, reverse=True)
            text_out = hits[0].get("text") or f"出场率最高的精灵是{hits[0].get('value')}。"
            return "灯灯记得：" + text_out
    from pokemon_kb import _mentioned_names, load_pokemon

    names = []
    for name in _mentioned_names(text, load_pokemon()):
        if name not in names:
            names.append(name)
    field = next((label for label in _FIELDS if label in text), "")
    if len(names) != 1 or not field:
        return ""
    hits = [
        edge for edge in archival_memory_search(session_id, text)
        if edge.get("source") == names[0] and edge.get("relation") == field and edge.get("text")
    ]
    if not hits:
        return ""
    return "灯灯记得：" + hits[0]["text"]


def _rate_question(text: str) -> bool:
    """只认登场/出场/使用率类问；避免「威力更高」误召回出场率边。"""
    body = text or ""
    if not any(word in body for word in ("出场率", "登场率", "使用率")):
        return False
    return any(word in body for word in ("最高", "榜首", "第一", "谁", "哪只", "哪个"))


def _extract_rate_champion(answer: str) -> dict:
    from agents.web_read import _ground_sprite_name, _rate_champion_name

    body = answer or ""
    name = _rate_champion_name(body)
    if not name:
        matched = re.search(
            r"(?:出场率|登场率|使用率)?最高的(?:精灵)?是([\u4e00-\u9fff]{2,12})",
            body,
        )
        if matched:
            name = _ground_sprite_name(matched.group(1), allow_unknown=False)
    if not name:
        return {}
    return {
        "source": _RATE_SOURCE,
        "relation": _RATE_PRED,
        "value": name,
        "text": f"出场率最高的精灵是{name}",
    }


def _update(session_id: str, fact: dict, episode: str) -> str:
    source = fact.get("source") or ""
    relation = fact.get("relation") or ""
    value = fact.get("value") or ""
    if not source or not relation or not value:
        return ""
    from agents.chat_notebook import _LOCK, _save_locked

    with _LOCK:
        memory = _open(session_id)
        current = [
            edge for edge in memory["edges"]
            if not edge.get("invalid_at") and edge.get("source") == source and edge.get("relation") == relation
        ]
        if any(edge.get("value") == value for edge in current):
            return "NOOP"
        event = "UPDATE" if current else "ADD"
        now = time.time()
        for edge in current:
            edge["invalid_at"] = now
            if edge["id"] in memory["core"]:
                memory["core"] = [item for item in memory["core"] if item != edge["id"]]
        edge = {
            "id": f"e{len(memory['edges']) + 1}",
            "source": source,
            "relation": relation,
            "value": value,
            "text": fact.get("text") or "",
            "valid_at": now,
            "invalid_at": "",
            "episode": (episode or "")[:80],
        }
        memory["edges"].append(edge)
        memory["core"].append(edge["id"])
        _fit_core(memory)
        _save_locked()
        return event


def _valid(session_id: str) -> list:
    from agents.chat_notebook import _LOCK

    with _LOCK:
        return [dict(edge) for edge in _open(session_id)["edges"] if not edge.get("invalid_at")]


def _core_edges(session_id: str) -> list:
    from agents.chat_notebook import _LOCK

    with _LOCK:
        memory = _open(session_id)
        known = {edge["id"]: edge for edge in memory["edges"]}
        rows = []
        for edge_id in memory.get("core") or []:
            edge = known.get(edge_id)
            if edge and not edge.get("invalid_at"):
                rows.append(dict(edge))
        return rows


def _fit_core(memory: dict) -> None:
    known = {edge["id"]: edge for edge in memory["edges"]}
    while len(memory["core"]) > 1:
        total = sum(len((known.get(edge_id) or {}).get("text") or "") for edge_id in memory["core"])
        if total <= _CORE_BUDGET:
            return
        memory["core"] = memory["core"][1:]


def _open(session_id: str) -> dict:
    from agents.chat_notebook import _book

    book = _book((session_id or "").strip())
    memory = book.get("memory")
    if not isinstance(memory, dict):
        memory = {"edges": [], "core": []}
        book["memory"] = memory
    memory.setdefault("edges", [])
    memory.setdefault("core", [])
    return memory


def _fact(source: str, relation: str, value: str) -> dict:
    kept = re.sub(r"\s+", " ", value or "").strip(" ，,。;；")
    return {
        "source": source,
        "relation": relation,
        "value": kept,
        "text": f"{source}的{relation}是{kept}",
    }
