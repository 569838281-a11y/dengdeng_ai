"""边想边说。模型先写下这一步的想法，字到了就推给页面，再去做。

调度词和玩家不该看见的词会从句子里拿掉。模型没写出字时，调用方仍用原来的那句。
"""
import contextvars
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

_thinker = contextvars.ContextVar("dengdeng_thinker", default=None)
_LIMIT = 80
_BANNED = (
    "need_local",
    "need_web",
    "need_both",
    "need_write",
    "need_ask",
    "need_lineup",
    "replan",
    "文件",
    "写入",
    "配置",
    "调用",
    "接口",
    "函数",
    "代码",
    "数据库",
    "调度",
)


class _Enough(Exception):
    pass


def bind_thinker(thinker):
    return _thinker.set(thinker)


def reset_thinker(token) -> None:
    _thinker.reset(token)


def streaming() -> bool:
    return callable(_thinker.get())


def _scrub(text: str) -> str:
    raw = " ".join(str(text or "").split())
    for word in _BANNED:
        raw = raw.replace(word, "")
    raw = raw.replace("json", "").replace("JSON", "").replace("mcp", "").replace("MCP", "")
    raw = raw.replace("api", "").replace("API", "")
    return " ".join(raw.split()).strip(" ，。；")


def stream_prompt(prompt: str) -> bool:
    """把模型这一句推出去。一个字都没有时返回假，调用方再用准备好的句子。"""
    thinker = _thinker.get()
    if not callable(thinker) or not str(prompt or "").strip():
        return False
    from agents.thoughts import note_close, note_delta

    buf = []
    emitted = False

    def on_piece(piece: str) -> None:
        nonlocal emitted
        buf.append(str(piece or ""))
        shown = _scrub("".join(buf))[:_LIMIT]
        if not shown:
            return
        emitted = True
        note_delta(shown)
        if len(shown) >= _LIMIT:
            raise _Enough()

    try:
        thinker(prompt, on_piece)
    except _Enough:
        pass
    except Exception as exc:
        logger.warning("这一步的想法没写完：%s", type(exc).__name__)
    if not emitted:
        return False
    note_close()
    return True


def model_thinker(timeout: int = 12):
    """生产环境用的写法。模型先在内部想，写出来的句子到一个字就交出去。"""
    from llm_provider import get_team_chat

    chat = get_team_chat()

    def thinker(prompt: str, on_piece) -> None:
        box = queue.Queue()

        def run() -> None:
            try:
                messages = [{"role": "user", "content": prompt}]
                for response in chat._ask_remote_sse(messages, reasoning_effort="low"):
                    choice = (response.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        box.put(str(piece))
            except Exception as exc:
                box.put(exc)
            finally:
                box.put(None)

        threading.Thread(target=run, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                item = box.get(timeout=0.3)
            except queue.Empty:
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            on_piece(item)

    return thinker


def opening_prompt(question: str) -> str:
    return (
        f"玩家问：{question}\n"
        "你是灯灯，面前是洛克王国世界的精灵。"
        "用一两句口语说说你准备先核对哪一处。"
        "不要编造种族值、技能名和伤害数字，也不要提别的游戏。"
        "不要提文件、接口、代码、数据库。"
    )


def step_prompt(question: str, seen: str, doing: str) -> str:
    return (
        f"玩家问：{question}\n"
        f"已经看到：{seen or '还没有'}\n"
        f"你正要：{doing}\n"
        "你是灯灯，面前是洛克王国世界的精灵。根据已经看到的，用一两句口语写下你此刻的想法。"
        "看完上一步再决定下一句，不要提前宣布还没看到的结果。"
        "不要编造种族值、技能名和伤害数字，也不要提别的游戏。"
        "不要提文件、接口、代码、数据库。"
    )


_ACTIONS = (
    "need_local",
    "need_web",
    "need_both",
    "need_write",
    "need_ask",
    "need_lineup",
    "surf_web",
    "surf_files",
    "coder",
)
_FACT = __import__("re").compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{1,12}的(?:属性|技能|种族值|特性|克制|本系技能和威力))"
)


def _collect(prompt: str) -> str:
    """把这一步的全文收齐。不往玩家屏幕上推。"""
    thinker = _thinker.get()
    if not callable(thinker):
        return ""
    buf = []

    def on_piece(piece: str) -> None:
        buf.append(str(piece or ""))
        if len("".join(buf)) >= 240:
            raise _Enough()

    try:
        thinker(prompt, on_piece)
    except _Enough:
        pass
    except Exception as exc:
        logger.warning("这一步的想法没写完：%s", type(exc).__name__)
    return "".join(buf).strip()


def _thought_only(text: str) -> str:
    raw = str(text or "")
    for marker in ("Action", "动作", "行动"):
        at = raw.find(marker)
        if at >= 0:
            raw = raw[:at]
    raw = raw.replace("Thought", "").replace("想法", "")
    return _scrub(raw)


def _parse_action(text: str) -> str:
    raw = str(text or "")
    at = raw.lower().rfind("action")
    window = raw[at:] if at >= 0 else raw
    found = []
    for name in _ACTIONS:
        index = window.find(name)
        if index >= 0:
            found.append((index, name))
    if not found:
        return ""
    found.sort()
    return found[0][1]


def react_turn(question: str, seen: str, program_word: str, hop_fact: str = "") -> tuple:
    """ReAct 的一步：先写 Thought，再写 Action。Action 不给玩家看。"""
    thinker = _thinker.get()
    if not callable(thinker):
        return False, ""
    from agents.thoughts import note_close, note_delta

    if (hop_fact or "").strip():
        prompt = (
            "按 ReAct 只写一步，先 Thought 再 Action。\n"
            "Thought 用灯灯的口语，一两句，只谈当前子问题有没有补齐，不要编造种族值、技能名和伤害数字，不要提别的游戏。\n"
            "Action 只能是其中一个词：need_local、need_web、need_ask。\n"
            "不要因为网页上还有阵容、热门、配队闲话就改航道。\n"
            "例子：\n"
            "Thought: 这一处名录没有，我到外面只查它。\n"
            "Action: need_web\n"
            f"当前子问题: {hop_fact.strip()}\n"
            f"Question: {question}\n"
            f"Observation: {seen or '还没有'}\n"
            f"程序建议: {program_word}\n"
        )
    else:
        prompt = (
            "按 ReAct 只写一步，先 Thought 再 Action。\n"
            "Thought 用灯灯的口语，一两句，不要编造种族值、技能名和伤害数字，不要提别的游戏。\n"
            "Action 只能是其中一个词：need_local、need_web、need_both、need_write、need_ask、need_lineup、surf_web、surf_files、coder。\n"
            "例子：\n"
            "Thought: 名录里还没有这一处，我先去核对。\n"
            "Action: need_local\n"
            f"Question: {question}\n"
            f"Observation: {seen or '还没有'}\n"
            f"程序建议: {program_word}\n"
        )
    buf = []
    last = ""

    def on_piece(piece: str) -> None:
        nonlocal last
        buf.append(str(piece or ""))
        full = "".join(buf)
        shown = _thought_only(full)[:_LIMIT]
        if shown and shown != last:
            note_delta(shown)
            last = shown
        if _parse_action(full):
            raise _Enough()

    try:
        thinker(prompt, on_piece)
    except _Enough:
        pass
    except Exception as exc:
        logger.warning("这一步的想法没写完：%s", type(exc).__name__)
    if last:
        note_close()
    action = _parse_action("".join(buf))
    if action:
        from agents.thoughts import note_thought

        note_thought(f"Action: {action}")
    return bool(last) or bool(action), action


def ircot_fact(question: str, retrieved: str) -> str:
    """IRCoT 的下一句。只收下能落在已出现名字上的栏目，对不上就当这一步结束。"""
    if not streaming():
        return ""
    text = _collect(
        "按 IRCoT，看已经检索到的原文，决定还要不要再查一条。\n"
        f"Question: {question}\n"
        f"Retrieved: {(retrieved or '')[:180]}\n"
        "原文已经能回答就只写：完成\n"
        "还要查就只写一条栏目，例如「水灵的技能」。不要写「某队的属性」。不要解释。\n"
    )
    if not text or "完成" in text:
        return ""
    found = _FACT.search(text)
    if not found:
        return ""
    fact = found.group(1)
    head = fact.split("的", 1)[0]
    if head and head not in f"{question}{retrieved}":
        return ""
    try:
        from agents.fact_read import _column_head, _known_column, _team_like

        owner = _column_head(fact) or head
        if owner and _team_like(owner):
            return ""
        if not _known_column(fact):
            return ""
    except Exception:
        pass
    return fact


def review_prompt(question: str) -> str:
    return (
        f"玩家问：{question}\n"
        "你是灯灯，面前是洛克王国世界的精灵。要说的话已经写好了。用一句说说你在看这句话能不能告诉玩家。"
        "不要写出新的结论、数字或技能名。"
        "不要提文件、接口、代码、数据库。"
    )
