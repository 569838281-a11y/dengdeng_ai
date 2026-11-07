"""文档先预览，人确认之后才落盘。"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from config import DATA_DIR


def _pending_dir() -> Path:
    folder = Path(DATA_DIR) / "pending_writes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def stage(filename: str, text: str, kind: str, session_id: str = "") -> str:
    token = uuid.uuid4().hex[:12]
    payload = {
        "token": token,
        "filename": Path(filename).name,
        "text": text or "",
        "kind": kind if kind in {"docx", "pdf"} else "docx",
        "session_id": session_id or "",
        "preview": f"灯灯准备记下{Path(filename).stem}。确认后才记下。",
        "label": Path(filename).name,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    (_pending_dir() / f"{token}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return token


def load_pending(token: str) -> dict:
    path = _pending_dir() / f"{Path(token).name}.json"
    if not path.is_file():
        raise FileNotFoundError(token)
    return json.loads(path.read_text(encoding="utf-8"))


def list_pending(session_id: str) -> list:
    sid = (session_id or "").strip()
    if not sid:
        return []
    rows = []
    folder = _pending_dir()
    if not folder.is_dir():
        return []
    for path in folder.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("session_id") != sid:
            continue
        rows.append({
            "token": payload.get("token") or "",
            "preview": payload.get("preview") or "",
            "label": payload.get("label") or payload.get("filename") or "",
            "session_id": sid,
        })
    return rows


def reject(token: str) -> None:
    payload = load_pending(token)
    (_pending_dir() / f"{payload['token']}.json").unlink(missing_ok=True)


def commit(token: str) -> str:
    payload = load_pending(token)
    target = _write_payload(payload)
    (_pending_dir() / f"{payload['token']}.json").unlink(missing_ok=True)
    return target.name


def _write_payload(payload: dict) -> Path:
    folder = Path(DATA_DIR) / "party"
    folder.mkdir(parents=True, exist_ok=True)
    kind = payload.get("kind") or "docx"
    filename = Path(payload.get("filename") or "note").name
    if not filename.lower().endswith("." + kind):
        filename = f"{Path(filename).stem}.{kind}"
    target = (folder / filename).resolve()
    if target.parent != folder.resolve():
        raise ValueError("bad path")
    text = (payload.get("text") or "").strip() or "灯灯记下了这些伙伴。"
    if kind == "docx":
        from docx import Document

        document = Document()
        for line in text.splitlines() or [text]:
            document.add_paragraph(line)
        document.save(str(target))
    else:
        import pymupdf

        opened = pymupdf.open()
        try:
            page = opened.new_page()
            page.insert_text((72, 72), text[:4000], fontname="china-s", fontsize=12)
            opened.save(str(target))
        finally:
            opened.close()
    return target
