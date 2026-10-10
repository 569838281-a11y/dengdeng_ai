"""最后一跳成文：同一份 SYSTEM+USER，先本地 LoRA，再云端 teacher，再安全回退。"""
import logging

import config
from langchain_core.messages import HumanMessage, SystemMessage

from agents.dengdeng_persona import (
    SYSTEM,
    battle_keeps_log,
    build_messages,
    fallback_battle,
    fallback_team,
    pick_cry,
    soften,
    team_keeps_roster,
    wrap_facts,
)
from llm_provider import get_team_invoke

logger = logging.getLogger(__name__)


def _teacher(user_text: str) -> str:
    from llm_provider import _voice_timeout

    invoke = get_team_invoke(_voice_timeout())
    result = invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=user_text),
    ])
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "").strip()


def _lora(user_text: str) -> str:
    from agents.lora_replier import generate

    return generate(build_messages(user_text))


def _use_lora() -> bool:
    return bool(config.USE_LORA_REPLIER)


def compose(user_text: str, accept, fallback, task: str) -> dict:
    """返回 {text, via}。via 为 lora / teacher / fallback。"""
    if _use_lora():
        try:
            drafted = soften(_lora(user_text))
            if accept(drafted):
                return {"text": drafted, "via": "lora"}
            logger.warning("灯灯成文回退：%s 的本地 LoRA 未通过资料校验，改走云端 teacher", task)
        except Exception as exc:
            logger.warning("灯灯成文回退：%s 的本地 LoRA 不可用（%s），改走云端 teacher", task, exc)
    try:
        drafted = soften(_teacher(user_text))
        if accept(drafted):
            return {"text": drafted, "via": "teacher"}
        logger.warning("灯灯成文回退：%s 的云端 teacher 未通过资料校验，改用程序原文", task)
    except Exception as exc:
        logger.warning("灯灯成文回退：%s 的云端 teacher 失败（%s），改用程序原文", task, exc)
    return {"text": fallback(), "via": "fallback"}


def reply_search(user_text: str, accept, summary: str) -> dict:
    if not (summary or "").strip() or summary.strip() == "知识库没有这项资料。":
        return {"text": pick_cry(), "via": "cry"}
    return compose(user_text, accept, lambda: wrap_facts(summary), "检索")


def reply_team(user_text: str, team_text: str) -> dict:
    return compose(
        user_text,
        lambda text: team_keeps_roster(text, team_text),
        lambda: fallback_team(team_text),
        "配队",
    )


def reply_battle(user_text: str, log_lines, winner: str = "") -> dict:
    return compose(
        user_text,
        lambda text: battle_keeps_log(text, log_lines),
        lambda: fallback_battle(log_lines, winner),
        "对战",
    )
