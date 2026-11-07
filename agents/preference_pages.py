"""跨会话偏好页。只给以后的上下文读，不代替选人。"""
import json
import os
import re
import threading
from pathlib import Path

from config import DATA_DIR

_LOCK = threading.Lock()
_TYPE = re.compile(r"常用\s*([\u4e00-\u9fff]{1,2})系|以\s*([\u4e00-\u9fff]{1,2})系为主")
_NO_CHARGE = re.compile(r"禁用蓄力|不要蓄力|别用蓄力|不用蓄力")
_TEAM = re.compile(r"第\s*(\d+)\s*套|第([一二三四五六七八九十]+)套")
_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _path() -> Path:
    override = os.getenv("PREFERENCE_PAGES", "")
    if override:
        return Path(override)
    return Path(DATA_DIR) / "preference_pages.json"


def learn_preference(user_id, text: str) -> list:
    key = str(user_id or "").strip()
    if not key or key == "0":
        return []
    added = []
    with _LOCK:
        book = _load()
        page = book.setdefault(key, {"types": [], "avoid": [], "teams": {}, "edits": {}})
        matched = _TYPE.search(text or "")
        if matched:
            kind = matched.group(1) or matched.group(2)
            if kind and kind not in page["types"]:
                page["types"].append(kind)
                added.append(f"常用{kind}系")
        if _NO_CHARGE.search(text or "") and "蓄力" not in page["avoid"]:
            page["avoid"].append("蓄力")
            added.append("不用蓄力")
        team_id = _team_id(text or "")
        dirty = bool(added)
        if team_id and re.search(r"换成|换为|改为|改成|修改", text or ""):
            edits = page["edits"]
            edits[str(team_id)] = int(edits.get(str(team_id)) or 0) + 1
            dirty = True
            if edits[str(team_id)] >= 2 and str(team_id) not in page["teams"]:
                page["teams"][str(team_id)] = True
                added.append(f"常改第{team_id}套")
        if dirty:
            _save(book)
    return added


def pages_for(user_id) -> list:
    key = str(user_id or "").strip()
    if not key:
        return []
    with _LOCK:
        page = _load().get(key) or {}
    lines = []
    if page.get("types"):
        lines.append("常用" + "、".join(f"{kind}系" for kind in page["types"]))
    if page.get("avoid"):
        lines.append("不用" + "、".join(page["avoid"]))
    teams = [f"第{team_id}套" for team_id in (page.get("teams") or {})]
    if teams:
        lines.append("常改" + "、".join(teams))
    if not lines:
        return []
    return [{
        "id": f"pref-{key}",
        "source": "长期记忆",
        "text": "。".join(lines) + "。",
        "sink": False,
    }]


def drop(user_id) -> None:
    key = str(user_id or "").strip()
    if not key:
        return
    with _LOCK:
        book = _load()
        book.pop(key, None)
        _save(book)


def _team_id(text: str):
    matched = _TEAM.search(text or "")
    if not matched:
        return None
    if matched.group(1):
        return int(matched.group(1))
    return _CN.get(matched.group(2))


def _load() -> dict:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save(book: dict) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return
