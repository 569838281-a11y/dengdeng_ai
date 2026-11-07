"""Adaptive-RAG 的三类。

A：不检索，靠模型自己记得的答案。
B：检索一次。
C：拆开一步一步查。
种族值、技能、克制落在 A 时不再回名录。
"""
import logging

logger = logging.getLogger(__name__)

_A_FIELDS = ("种族值", "技能", "克制")
_HEAVY = ("多少伤害", "谁会赢", "谁赢", "打得过", "配队", "组建", "仓库", "放生", "出场率", "登场率", "使用率")


def route_adaptive(question: str) -> str:
    """A 不查，B 查一次，C 多步。"""
    from agents.fact_read import _chain_question

    text = (question or "").strip()
    if not text:
        return "B"
    if _chain_question(text):
        return "C"
    if any(word in text for word in _HEAVY):
        return "B"
    if any(word in text for word in ("哪个更高", "哪个更大", "相比", "差别", "区别")):
        return "B"
    fields = [label for label in _A_FIELDS if label in text]
    if len(fields) != 1:
        return "B"
    from pokemon_kb import _mentioned_names, load_pokemon

    if len(_mentioned_names(text, load_pokemon())) > 1:
        return "B"
    return "A"


def parametric_answer(question: str, session_id: str = "", ask=None) -> str:
    """不查名录。只请模型按记得的内容答这一问。"""
    from agents.lived_memory import core_block
    from agents.react_stream import streaming

    prompt = (
        "这一问不查资料，只按你记得的回答。"
        "面前是洛克王国世界的精灵。"
        "只答这一问。想不起来就只写：灯灯没想起。\n"
        f"问题：{question}"
    )
    block = core_block(session_id)
    if block:
        prompt = "你已经记得这些：\n" + block + "\n" + prompt
    caller = ask
    if caller is None and streaming():
        try:
            from llm_provider import get_team_invoke

            caller = get_team_invoke(12)
        except Exception as exc:
            logger.warning("不检索的答案没请到：%s", type(exc).__name__)
            caller = None
    if caller is None:
        return "灯灯没想起这一处。"
    try:
        raw = caller(prompt)
    except Exception as exc:
        logger.warning("不检索的答案没写成：%s", type(exc).__name__)
        return "灯灯没想起这一处。"
    text = str(getattr(raw, "content", None) or raw or "").strip()
    line = text.splitlines()[0].strip() if text else ""
    if not line or "没想起" in line:
        return "灯灯没想起这一处。"
    return line[:180]
