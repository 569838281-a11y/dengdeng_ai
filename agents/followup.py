"""没做完的那一单怎么接后一句。

后一句能单独查：把缺的那一格填回原问，写成一句不靠上文也能查的问法。
后一句是在填上一格：名字只从这句里抄，抄到一个才算填上。
填上之后继续同一单，不把这句当成新问题。
"""
import re

_NEW_TASK = re.compile(r"另外|顺便|再问|还有一个|换个问题|同时再|两项|两个问题|另起")
_CONDITION = re.compile(r"还要|并且|而且|再加上|加上|不要|改成|换成|改为|尽量|最好|更喜欢|习惯|优先|针对|以.{0,8}为|也能|同时要|顺便加上")
_FACET = re.compile(r"技能池|种族值|特性|技能|为什么|克制|配队|组建|出场|谁会赢|伤害|怎么配")


def _facets(text: str) -> set:
    return set(_FACET.findall(text or ""))


def resume_decision(previous: str, incoming: str) -> str:
    """账本还停在询问时：condition 接着补这一处，task 另起一件。"""
    return split_followup(previous, incoming)["kind"]


def same_task(previous: str, incoming: str) -> bool:
    """还停在询问时，后一句接着填这一格。另起一件才放开。"""
    if _NEW_TASK.search(incoming or ""):
        return False
    if copied_name(incoming):
        return True
    return split_followup(previous, incoming)["kind"] == "condition"


def copied_name(text: str) -> str:
    """从这句里抄出唯一的精灵名。问句、两个名字，都不抄。"""
    body = (text or "").strip()
    if not body:
        return ""
    from agents.fact_read import _mentioned

    if re.search(r"[？?]|(?:什么|多少|哪些|怎么|为什么)", body):
        return ""
    matched = re.search(r"(?:就是|叫做|是)\s*([^\s，。！？?]{2,16})", body)
    if matched:
        names = _mentioned(matched.group(1))
        if len(names) == 1:
            return names[0]
        return ""
    names = _mentioned(body)
    if len(names) == 1:
        return names[0]
    return ""


_RATE_PHRASES = (
    "闪耀大赛出场率最高的精灵",
    "闪耀大赛登场率最高的精灵",
    "出场率最高的精灵",
    "登场率最高的精灵",
    "使用率最高的精灵",
)


def standalone_question(previous: str, label: str, name: str) -> str:
    """把补上的名字写回原问，得到一句可以单独查的问法。"""
    text = (previous or "").strip()
    title = (name or "").strip()
    if not title:
        return text
    phrases = []
    for phrase in ((label or "").strip(), (label or "").replace("登场率", "出场率"), (label or "").replace("出场率", "登场率")):
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    for phrase in _RATE_PHRASES:
        if phrase not in phrases:
            phrases.append(phrase)
    replaced = False
    for phrase in phrases:
        if phrase and phrase in text:
            text = text.replace(phrase, title, 1)
            replaced = True
            break
    if replaced:
        text = text.replace("用它", "用", 1).replace("用这只", "用", 1)
        return text
    if not text:
        return title
    return f"{title}。{text}"


def split_followup(previous: str, incoming: str) -> dict:
    """kind 为 condition 时只有一条合并后的任务；为 task 时两条都要答。"""
    prev = (previous or "").strip()
    inc = (incoming or "").strip()
    if not prev:
        return {"kind": "task", "tasks": [inc] if inc else []}
    if not inc:
        return {"kind": "condition", "tasks": [prev]}
    if _NEW_TASK.search(inc):
        return {"kind": "task", "tasks": [prev, inc]}
    prev_facets = _facets(prev)
    inc_facets = _facets(inc)
    if inc_facets and prev_facets and inc_facets.isdisjoint(prev_facets) and not _CONDITION.search(inc):
        return {"kind": "task", "tasks": [prev, inc]}
    merged = prev.rstrip("。！？") + "。" + inc
    return {"kind": "condition", "tasks": [merged]}
