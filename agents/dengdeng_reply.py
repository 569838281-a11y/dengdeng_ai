"""最后一跳成文。换说法交给成文员，不过再回程序原文。

微调先不加载，留到固定题基线之后。
"""
from agents.dengdeng_persona import (
    battle_keeps_log,
    fallback_battle,
    fallback_team,
    pick_cry,
    team_keeps_roster,
    wrap_facts,
)


def _teacher(user_text: str) -> str:
    from agents.voice_agent import _cloud_teacher

    return _cloud_teacher(user_text)


def _lora(user_text: str) -> str:
    from agents.voice_agent import _lora as lora

    return lora(user_text)


def _use_lora() -> bool:
    from agents.voice_agent import _use_lora as use_lora

    return use_lora()


def compose(user_text: str, accept, fallback, task: str) -> dict:
    """返回 {text, via}。via 为 lora / teacher / fallback。旧话只进模型，不进回退原文。"""
    from agents.voice_agent import speak

    return speak(user_text, accept, fallback, task)


def reply_notice(sentence: str) -> dict:
    """询问和核对缺口直接说出这一句。不改名单，也不再加一句别的问题。"""
    from agents.dengdeng_persona import contains_banned

    body = (sentence or "").strip()
    if not body or contains_banned(body):
        return {"text": "灯灯这会儿没听清你要做哪一件事。再说一次。", "via": "fallback"}
    return {"text": body, "via": "program"}


def reply_search(user_text: str, accept, summary: str) -> dict:
    if not (summary or "").strip() or summary.strip() == "知识库没有这项资料。":
        return {"text": pick_cry(), "via": "cry"}
    return compose(user_text, accept, lambda: wrap_facts(summary), "检索")


def reply_team(user_text: str, team_text: str) -> dict:
    result = compose(
        user_text,
        lambda text: team_keeps_roster(text, team_text),
        lambda: fallback_team(team_text),
        "配队",
    )
    return result


def reply_battle(user_text: str, log_lines, winner: str = "") -> dict:
    return compose(
        user_text,
        lambda text: battle_keeps_log(text, log_lines),
        lambda: fallback_battle(log_lines, winner),
        "对战",
    )
