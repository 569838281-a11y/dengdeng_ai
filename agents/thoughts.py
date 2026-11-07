"""灯灯做事时往外递一句。界面把 thought / read / edit 收成思考链。"""
import contextvars

_sink = contextvars.ContextVar("dengdeng_thoughts", default=None)


def bind(callback):
    return _sink.set(callback)


def reset(token) -> None:
    _sink.reset(token)


def _emit(kind: str, text: str) -> None:
    callback = _sink.get()
    if callback is None:
        return
    body = str(text or "").strip()
    if kind != "close" and not body:
        return
    try:
        callback(kind, body)
    except Exception:
        return


_DISPATCH = {
    "need_local": "灯灯先查已经有的资料",
    "need_web": "灯灯到外面看这一处",
    "need_both": "灯灯两处一起查",
    "need_write": "灯灯按吩咐看仓库",
    "need_ask": "灯灯要先问清一件事",
    "need_lineup": "灯灯开始排这一套",
    "check": "灯灯在核对这一套",
    "replan": "灯灯换一种删法",
    "speak": "灯灯准备告诉你",
}


def note_dispatch(word: str) -> None:
    """监督者每派一步，给玩家一句过程。调度词本身不说出来。"""
    text = _DISPATCH.get(word or "")
    if text:
        note_thought(text)


def note_delta(text: str) -> None:
    """模型正在写的这一句。界面把它接到当前想法末尾。"""
    _emit("delta", text)


def note_close() -> None:
    _emit("close", "")


def note_thought(text: str) -> None:
    _emit("thought", text)


def note_read(text: str) -> None:
    _emit("read", text)


def note_edit(text: str) -> None:
    _emit("edit", text)
