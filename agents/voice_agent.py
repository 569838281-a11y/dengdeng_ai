"""成文员。只把已经写好的原文换成灯灯的说法。

数字、名字和名单仍由调用方的 accept 决定。没通过就交回程序原文。
本地微调的入口留在这里，现在不加载。
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


def speak(user_text: str, accept, fallback, task: str, teacher=None) -> dict:
    """返回 {text, via}。via 为 lora / teacher / fallback。"""
    from agents.dengdeng_persona import soften
    from agents.kv_blocks import voice_prefix
    from agents.thoughts import note_read

    note_read("成文员在换说法")
    model_text = voice_prefix() + (user_text or "")
    if _use_lora():
        try:
            drafted = soften(_lora(model_text))
            if accept(drafted):
                return {"text": drafted, "via": "lora"}
            logger.warning("灯灯成文回退：%s 的本地 LoRA 未通过资料校验，改走云端 teacher", task)
        except Exception as exc:
            logger.warning("灯灯成文回退：%s 的本地 LoRA 不可用（%s），改走云端 teacher", task, exc)
    caller = teacher or _cloud_teacher
    try:
        drafted = soften(caller(model_text))
        if accept(drafted):
            return {"text": drafted, "via": "teacher"}
        logger.warning("灯灯成文回退：%s 的云端 teacher 未通过资料校验，改用程序原文", task)
    except Exception as exc:
        logger.warning("灯灯成文回退：%s 的云端 teacher 失败（%s），改用程序原文", task, exc)
    return {"text": fallback(), "via": "fallback"}


def _use_lora() -> bool:
    """微调留到固定题基线之后。现在即使环境变量打开，也不加载本地口吻模型。"""
    return False


def _lora(user_text: str) -> str:
    from agents.dengdeng_persona import build_messages
    from agents.lora_replier import generate

    return generate(build_messages(user_text))


def _cloud_teacher(user_text: str) -> str:
    from agents.dengdeng_persona import SYSTEM
    from llm_provider import _voice_timeout, get_team_invoke

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
