"""一单配队或资料的工作账本。工人只往这里回传，不互相聊天。"""
import threading

_LOCK = threading.Lock()
_OPEN = {}
_PARKED = {}


def blank(session_id: str, utterance: str) -> dict:
    return {
        "job_id": "",
        "session_id": session_id or "",
        "utterance": utterance or "",
        "constraints": {
            "intent": "",
            "mode": "",
            "focus": "",
            "target": "",
            "warehouse_only": True,
            "replace_slot": "",
        },
        "plan_version": 1,
        "plan": [],
        "slots": {"local": "closed", "web": "closed", "tried": []},
        "facts": [],
        "guesses": [],
        "requests": [],
        "roster": [],
        "write": {"tool": "", "arguments": {}, "complete": False, "pending_question": ""},
        "check": {
            "pass": False,
            "issues": [],
            "stall_count": 0,
            "satisfied": "",
            "facets": {},
        },
        "progress": {
            "next": "",
            "next_assignee": "",
            "instruction": "",
            "hot_done": False,
            "revision_reason": "",
            "satisfied": False,
            "stall_count": 0,
        },
        "speech": "",
        "pending_speech": "",
        "gap": None,
        "admitted": [],
        "interrupt": "",
        "trial": None,
        "target_types": [],
    }


def waiting(session_id: str):
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        book = _OPEN.get(sid)
        if not book or (book.get("progress") or {}).get("next") != "need_ask":
            return None
        return book


def store(session_id: str, ledger: dict) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        _OPEN[sid] = ledger


def unwait(session_id: str) -> None:
    """这一问已经说完。留下配队账本，但不再把它当成还在等回答。"""
    sid = (session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        _OPEN.pop(sid, None)


def drop(session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        _OPEN.pop(sid, None)
        _PARKED.pop(sid, None)


def park(session_id: str, ledger: dict) -> None:
    """配队已经停下时留着这一单，方便玩家说「不对，换一种删法」。"""
    sid = (session_id or "").strip()
    if not sid or (ledger.get("constraints") or {}).get("intent") != "lineup":
        return
    with _LOCK:
        _PARKED[sid] = ledger


def parked(session_id: str):
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        book = _PARKED.get(sid)
        return book if book else None


def mark_tried(ledger: dict, slot: str) -> None:
    tried = list((ledger.get("slots") or {}).get("tried") or [])
    if slot not in tried:
        tried.append(slot)
    ledger["slots"]["tried"] = tried


def already_tried(ledger: dict, slot: str) -> bool:
    return slot in ((ledger.get("slots") or {}).get("tried") or [])
