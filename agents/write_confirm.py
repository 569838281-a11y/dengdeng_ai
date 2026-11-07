"""仓库和出场先存成待确认单。这一轮停住，人点头后才改表。"""
import contextvars
import json
import uuid
from datetime import datetime
from pathlib import Path

from config import DATA_DIR

_ARM = contextvars.ContextVar("deng_write_arm", default=None)
_STAGED = contextvars.ContextVar("deng_write_staged", default=None)


def _dir() -> Path:
    folder = Path(DATA_DIR) / "pending_confirms"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def arm(session_id: str, job_id: str):
    """这一轮里的改表先寄存。调用方在结束时 disarm。"""
    _STAGED.set(None)
    return _ARM.set({"session_id": session_id or "", "job_id": job_id or ""})


def disarm(token) -> None:
    _STAGED.set(None)
    _ARM.reset(token)


def armed() -> bool:
    return bool(_ARM.get())


def current_session() -> str:
    state = _ARM.get() or {}
    return str(state.get("session_id") or "")


def stage_table(path: str, csv_text: str, preview: str, speech: str, label: str, roster: str = "") -> dict:
    state = _ARM.get() or {}
    token = uuid.uuid4().hex[:12]
    payload = {
        "token": token,
        "session_id": state.get("session_id") or "",
        "job_id": state.get("job_id") or "",
        "kind": "table",
        "path": Path(path or "note.csv").name,
        "csv_text": csv_text or "",
        "preview": preview or "",
        "speech": speech or "",
        "label": label or "仓库",
        "roster": roster or "",
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    (_dir() / f"{token}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    public = _public(payload)
    _STAGED.set(public)
    return public


def take() -> dict:
    value = _STAGED.get()
    _STAGED.set(None)
    return value or {}


def _public(payload: dict) -> dict:
    return {
        "token": payload.get("token") or "",
        "preview": payload.get("preview") or "",
        "label": payload.get("label") or "",
        "session_id": payload.get("session_id") or "",
        "roster": payload.get("roster") or "",
    }


def _load(token: str) -> tuple:
    path = _dir() / f"{Path(token or '').name}.json"
    if not path.is_file():
        return None, path
    return json.loads(path.read_text(encoding="utf-8")), path


def bind_thread(token: str, thread_id: str) -> None:
    """点头之后靠这个编号回到同一次计算。"""
    payload, path = _load(token)
    if not payload or not thread_id:
        return
    payload["thread_id"] = thread_id
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def commit(token: str) -> dict:
    payload, path = _load(token)
    if not payload:
        raise FileNotFoundError(token)
    from agents.battle_orders import _write_table

    _write_table(payload.get("path") or "note.csv", payload.get("csv_text") or "")
    path.unlink(missing_ok=True)
    return {
        "saved": payload.get("label") or "仓库",
        "text": payload.get("speech") or "灯灯记下了。",
        "roster": payload.get("roster") or "",
    }


def reject(token: str) -> dict:
    _payload, path = _load(token)
    if not path.is_file():
        raise FileNotFoundError(token)
    path.unlink(missing_ok=True)
    return {"text": "灯灯没有记下。"}


def list_pending(session_id: str) -> list:
    sid = (session_id or "").strip()
    if not sid:
        return []
    rows = []
    folder = _dir()
    if not folder.is_dir():
        return []
    for path in folder.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("session_id") != sid:
            continue
        rows.append(_public(payload))
    return rows
