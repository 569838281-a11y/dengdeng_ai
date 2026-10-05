"""立绘只读 photo/。精确文件名优先，否则用去掉形态括号后的主名。"""
import re
from pathlib import Path

from pokemon_kb import load_pokemon

ROOT = Path(__file__).resolve().parent
PHOTO_DIR = ROOT / "photo"
_PAREN = re.compile(r"（[^）]*）")


def _safe_png(filename: str):
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    path = (PHOTO_DIR / filename).resolve()
    root = PHOTO_DIR.resolve()
    if root not in path.parents and path != root:
        return None
    if path.is_file() and path.suffix.lower() == ".png":
        return path
    return None


def resolve_photo(name: str, form: str = "base"):
    """返回 (path or None, match)。

    base 先完整名再去括号主名。boss 先试「名字_首领化.png」，没有则回退基础图。
    """
    cleaned = (name or "").strip()
    if not cleaned or any(mark in cleaned for mark in ("/", "\\", "..")):
        return None, "missing"
    stem = _PAREN.sub("", cleaned).strip()
    if form == "boss":
        for filename, match in (
            (f"{cleaned}_首领化.png", "boss"),
            (f"{stem}_首领化.png", "boss-stem"),
        ):
            if not stem or stem == cleaned:
                if match == "boss-stem":
                    continue
            found = _safe_png(filename)
            if found:
                return found, match
    exact = _safe_png(f"{cleaned}.png")
    if exact:
        return exact, "fallback" if form == "boss" else "exact"
    if stem and stem != cleaned:
        found = _safe_png(f"{stem}.png")
        if found:
            return found, "fallback" if form == "boss" else "stem"
    return None, "missing"


def photo_inventory():
    rows = []
    for mon in load_pokemon():
        name = mon["name"]
        _path, match = resolve_photo(name)
        stem = _PAREN.sub("", name).strip()
        rows.append({
            "name": name,
            "match": match,
            "file": f"{name}.png" if match == "exact" else (f"{stem}.png" if match == "stem" else ""),
        })
    return rows
