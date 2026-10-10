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
    if not body:
        return
    try:
        callback(kind, body)
    except Exception:
        return


def note_thought(text: str) -> None:
    _emit("thought", text)


def note_read(text: str) -> None:
    _emit("read", text)


def note_edit(text: str) -> None:
    _emit("edit", text)
