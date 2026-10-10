"""思考还没结束时，判断后一句是在加条件，还是另起一项任务。"""
import re

_NEW_TASK = re.compile(r"另外|顺便|再问|还有一个|换个问题|同时再|两项|两个问题|另起")
_CONDITION = re.compile(r"还要|并且|而且|再加上|加上|不要|改成|换成|改为|尽量|最好|更喜欢|习惯|优先|针对|以.{0,8}为|也能|同时要|顺便加上")
_FACET = re.compile(r"技能池|种族值|特性|技能|为什么|克制|配队|组建|出场|谁会赢|伤害|怎么配")


def _facets(text: str) -> set:
    return set(_FACET.findall(text or ""))


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
