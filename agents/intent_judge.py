"""先听要求，再进入下一步。

模型只判断这句是在查资料、配队、改仓库、问输赢，还是在下结论，
并把原话收成一句仍带着精灵全名的要求。选人、改数量和结算仍交给后面的程序。
模型没有答上时，调用方继续用原来的规则。
"""
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agents.prompt_function_calling import first_json

logger = logging.getLogger(__name__)

INTENTS = {"search", "lineup", "order", "battle", "remember", "persona_story"}

_SYSTEM = """你负责听小洛克这句在提什么要求。只输出一个 JSON，不要解释。
格式：{"intent":"search|lineup|order|battle|remember|persona_story","request":"一句话"}
search：想了解某只精灵、技能、特性、规则；或问出场率/登场率/使用率后再算伤害、威力。
lineup：想配一套出场（组队、阵容、六人）。
order：想查看或改动仓库、出场、放生、换人、换招。
battle：想问谁赢、打得过、对战结果（不是「打出多少伤害」这类算式）。
remember：在告知事实、外号或偏好，不是在提问。
persona_story：问灯灯自己的成长、故事、经历或「你是谁」（不是某只精灵的图鉴故事）。
「打出多少伤害」「威力最大的技能打…」一律 search，不要判成 lineup 或 battle。
request 保留原句里的精灵全名，不要新造名字。
order 和 remember 的 request 照抄原句，不要补上原句没有的数量。"""


def parse_intent(raw: str) -> dict:
    data = first_json(raw or "")
    if not isinstance(data, dict):
        return {"intent": "", "request": ""}
    intent = str(data.get("intent") or "").strip()
    request = str(data.get("request") or "").strip()
    if intent not in INTENTS:
        return {"intent": "", "request": ""}
    return {"intent": intent, "request": request}


def _force_search(text: str) -> bool:
    """多跳查资料算伤害，不能被听成配队或对战。"""
    body = text or ""
    if not body:
        return False
    try:
        from agents.fact_read import _chain_question

        if _chain_question(body):
            return True
    except Exception:
        pass
    rate = any(word in body for word in ("出场率", "登场率", "使用率"))
    damage = any(word in body for word in ("多少伤害", "打出多少", "能打出", "伤害是多少"))
    power = "威力" in body and any(word in body for word in ("最大", "最高", "本系"))
    return rate and (damage or power)


def _ask_teacher(question: str) -> str:
    from llm_provider import _voice_timeout, get_team_invoke

    invoke = get_team_invoke(_voice_timeout())
    result = invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=question),
    ])
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "").strip()


def judge_intent(question: str, ask=None) -> dict:
    """返回 {intent, request}。失败时 intent 为空，表示改走原有规则。"""
    text = (question or "").strip()
    if not text:
        return {"intent": "", "request": ""}
    if _force_search(text):
        return {"intent": "search", "request": text}
    try:
        from agents.story_read import is_persona_story

        if is_persona_story(text):
            return {"intent": "persona_story", "request": text}
    except Exception:
        pass
    try:
        raw = (ask or _ask_teacher)(text)
    except Exception as exc:
        logger.warning("意图判断未完成：%s", type(exc).__name__)
        return {"intent": "", "request": ""}
    parsed = parse_intent(raw)
    if parsed["intent"] in {"order", "remember", "persona_story"}:
        parsed["request"] = text
    if _force_search(text) and parsed["intent"] not in {"order", "remember", "persona_story"}:
        parsed["intent"] = "search"
        parsed["request"] = parsed["request"] or text
    return parsed


def first_dispatch(intent: str) -> str:
    """听完要求后的第一步调度词。后面的改派由监督者写，不在这里把整句交出去。"""
    return {
        "order": "need_write",
        "lineup": "need_local",
        "search": "need_local",
        "battle": "need_local",
        "remember": "need_ask",
        "persona_story": "need_local",
    }.get(intent or "", "")


def next_question(question: str, judged: dict) -> str:
    """把听出来的要求变成下一步用的句子。改仓库和下结论仍用原句。"""
    text = (question or "").strip()
    intent = (judged or {}).get("intent") or ""
    request = str((judged or {}).get("request") or "").strip()
    if intent in {"order", "remember", ""}:
        return text
    if intent == "battle":
        body = request or text
        if not re.search(r"对战|谁会赢|谁赢|打得过", body):
            return body + "，谁会赢"
        return body
    return request or text
