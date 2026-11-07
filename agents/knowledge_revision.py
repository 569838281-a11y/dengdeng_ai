"""知识库更新先给出差异，人确认后写盘，并留下快照和回滚。"""
import json
import uuid
from datetime import datetime
from pathlib import Path


def _root(root: Path) -> Path:
    return Path(root).resolve()


def _allowed(root: Path, relative: str) -> Path:
    text = (relative or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ":" in text or ".." in text.split("/"):
        raise ValueError("bad path")
    path = (_root(root) / text).resolve()
    knowledge = (_root(root) / "knowledge").resolve()
    try:
        path.relative_to(knowledge)
    except ValueError as exc:
        raise ValueError("bad path") from exc
    name = path.name.lower()
    if path == knowledge / "rules.md":
        return path
    if path.parent == knowledge / "pokemon" and path.suffix.lower() == ".json":
        return path
    if name.startswith("."):
        raise ValueError("bad path")
    raise ValueError("bad path")


def _store(root: Path) -> Path:
    folder = _root(root) / "data" / "knowledge_revisions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _log(root: Path, event: dict) -> None:
    handle = _store(root) / "log.jsonl"
    with handle.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")


def propose(root: Path, relative: str, new_text: str) -> dict:
    target = _allowed(root, relative)
    old = target.read_text(encoding="utf-8") if target.is_file() else ""
    token = uuid.uuid4().hex[:12]
    record = {
        "token": token,
        "path": str(target.relative_to(_root(root))).replace("\\", "/"),
        "old": old,
        "new": new_text or "",
        "created": datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
    }
    (_store(root) / f"{token}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "token": token,
        "path": record["path"],
        "changed": old != record["new"],
        "preview": record["new"][:800],
    }


def confirm(root: Path, token: str) -> dict:
    folder = _store(root)
    path = folder / f"{Path(token).name}.json"
    if not path.is_file():
        raise FileNotFoundError(token)
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("status") == "applied":
        return {"token": token, "status": "applied", "path": record["path"]}
    target = _allowed(root, record["path"])
    snap = folder / "snapshots" / token
    snap.mkdir(parents=True, exist_ok=True)
    (snap / target.name).write_text(record.get("old") or "", encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(record.get("new") or "", encoding="utf-8")
    record["status"] = "applied"
    record["applied"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(root, {"action": "confirm", "token": token, "path": record["path"], "at": record["applied"]})
    return {"token": token, "status": "applied", "path": record["path"]}


def rollback(root: Path, token: str) -> dict:
    folder = _store(root)
    path = folder / f"{Path(token).name}.json"
    if not path.is_file():
        raise FileNotFoundError(token)
    record = json.loads(path.read_text(encoding="utf-8"))
    target = _allowed(root, record["path"])
    snap = folder / "snapshots" / token / target.name
    if not snap.is_file():
        raise FileNotFoundError(token)
    target.write_text(snap.read_text(encoding="utf-8"), encoding="utf-8")
    record["status"] = "rolled_back"
    record["rolled_back"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(root, {
        "action": "rollback",
        "token": token,
        "path": record["path"],
        "at": record["rolled_back"],
    })
    return {"token": token, "status": "rolled_back", "path": record["path"]}
