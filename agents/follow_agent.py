"""追问收束。把带着上文的短句收成一句独立问句。

放生、删套、换招和查看仓库保持原句。改写后的只数必须和原句一样。
"""
import logging

logger = logging.getLogger(__name__)


def rewrite_followup(question: str, history=None, invoke=None) -> dict:
    """返回 {query, kept}。kept 为真时查询仍是原句。"""
    from agents.thoughts import note_read

    text = (question or "").strip()
    if _hold(text) or not history:
        return {"query": text, "kept": True}
    # 人设故事禁止用历史把「你的成长」改写成上一只精灵图鉴（防串台）。
    try:
        from agents.story_read import is_persona_story

        if is_persona_story(text):
            return {"query": text, "kept": True}
    except Exception:
        pass
    try:
        caller = invoke
        if caller is None:
            from llm_provider import get_team_invoke

            caller = get_team_invoke()
        from agents.pipeline import standalone_query
        from agents.work_cycle import _counts_match

        rewritten = standalone_query(text, history, caller)
        if rewritten and _counts_match(text, rewritten):
            query = rewritten.strip()
            if query != text:
                from agents.react_stream import stream_prompt

                heard = (
                    f"玩家接着问：{text}\n"
                    f"你把它收成了一句独立问法：{query}\n"
                    "你是灯灯。用一句说说你注意到玩家在接着问。"
                    "不要提文件、接口、代码、数据库。"
                )
                if not stream_prompt(heard):
                    note_read("追问收束成了一句独立问句")
            return {"query": query or text, "kept": query == text}
    except Exception as exc:
        logger.warning("问句改写未完成：%s", type(exc).__name__)
    return {"query": text, "kept": True}


def _hold(question: str) -> bool:
    from agents.kv_blocks import is_disk_write

    return is_disk_write(question or "") or "仓库" in (question or "")
