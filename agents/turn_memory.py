"""上一问的对象。只记精灵全名和栏目，下一句用来补「它」。

威力、克制和种族值不写在这里，仍当场查名录。
"""
import re

_NEW_TASK = re.compile(r"另外|顺便|再问|还有一个|换个问题|同时再|两项|两个问题|另起")
_LINEUP_HOLD = re.compile(r"该队伍|这套|这一套|上一套|刚才那套|不拘泥|不必拘泥|不局限|不用仓库")
_POINTER = re.compile(r"这只|那个|刚才|它")
_FIELDS = ("技能池", "种族值", "首领化", "特性", "克制", "血脉", "技能", "属性", "标签")


def _hold(question: str) -> bool:
    from agents.kv_blocks import is_disk_write

    return is_disk_write(question or "") or "仓库" in (question or "")


def field_of(question: str) -> str:
    text = question or ""
    for label in _FIELDS:
        if label in text:
            return label
    return ""


def carry_subject(question: str, session_id: str) -> dict:
    """没有点名、又在指上一问时，补上唯一的那只全名。两只以上不猜。"""
    text = (question or "").strip()
    kept = {"query": text, "anchor": "", "carried": False}
    if not text or not (session_id or "").strip() or _hold(text) or _NEW_TASK.search(text):
        return kept
    if _LINEUP_HOLD.search(text):
        return kept
    from agents.chat_notebook import turn_of

    card = turn_of(session_id)
    names = list((card or {}).get("names") or [])
    if len(names) != 1:
        return kept
    name = names[0]
    if name in text:
        return kept
    from pokemon_kb import _mentioned_names, load_pokemon

    if _mentioned_names(text, load_pokemon()):
        return kept
    if not (_POINTER.search(text) or "呢" in text):
        return kept
    if _POINTER.search(text):
        query = _POINTER.sub(name, text, count=1)
    else:
        label = field_of(text)
        query = text.replace(label, f"{name}的{label}", 1) if label else f"{name}，{text}"
    return {"query": query, "anchor": name, "carried": query != text}


def close_turn(session_id: str, question: str, intent: str = "") -> None:
    """这一问答完后盖过上一张卡片。写盘的句子不改卡片。"""
    text = (question or "").strip()
    if not (session_id or "").strip() or not text or _hold(text):
        return
    from agents.chat_notebook import remember_turn
    from pokemon_kb import _mentioned_names, load_pokemon

    remember_turn(session_id, _mentioned_names(text, load_pokemon()), field_of(text), intent)


def remember_exchange(session_id: str, question: str, answer: str, extend=None) -> None:
    """把这一问和这一答写入会话原文。不写长期摘要。"""
    if not (session_id or "").strip() or not (question or "").strip():
        return
    messages = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer or ""},
    ]
    if extend is not None:
        extend(session_id, messages)
        return
    from session_store import session_store

    session_store.extend(session_id, messages)
