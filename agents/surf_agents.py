"""Magentic-One 里的三类工人：上网、翻允许的目录、写一道能算的式子。

代码只跑四则运算，或名为 damage 的三参数调用。不执行别的语句。
"""
import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOTS = (
    Path(__file__).resolve().parents[1] / "knowledge",
    Path(__file__).resolve().parents[1] / "data" / "party",
)


def web_surfer(ledger: dict, web) -> None:
    from agents.supervisor import _web
    from agents.thoughts import note_thought

    note_thought("WebSurfer")
    _web(ledger, web, None)


def file_surfer(ledger: dict) -> None:
    from agents.supervisor import _add_fact, _asked, _say
    from agents.thoughts import note_read, note_thought

    note_thought("FileSurfer")
    question = _asked(ledger)
    path = _find(question)
    if path is None:
        _say(ledger, "灯灯在允许的目录里没找到这一份。", stop=True)
        return
    try:
        text = path.read_text(encoding="utf-8")[:500]
    except OSError as exc:
        logger.warning("文件没读成：%s", type(exc).__name__)
        _say(ledger, "灯灯这会儿没读成这一份。", stop=True)
        return
    note_read(path.name)
    _add_fact(ledger, "FileSurfer", "catalog", text, path.stem)
    ledger["pending_speech"] = text[:180]
    ledger["slots"]["local"] = "filled"
    ledger["progress"]["next"] = "speak"


def coder(ledger: dict) -> None:
    from agents.supervisor import _asked, _say
    from agents.thoughts import note_read, note_thought

    note_thought("Coder")
    question = _asked(ledger)
    line = _code_line(question)
    if not line:
        _say(ledger, "灯灯这会儿没有可算的式子。", stop=True)
        return
    try:
        value = safe_calc(line)
    except Exception as exc:
        logger.warning("算式没跑成：%s", type(exc).__name__)
        _say(ledger, "灯灯这会儿没把这道算出来。", stop=True)
        return
    shown = value if isinstance(value, str) else _number(value)
    note_read(f"{line} = {shown}")
    ledger["pending_speech"] = f"灯灯算得 {shown}。"
    ledger["progress"]["next"] = "speak"


def safe_calc(expr: str):
    """只接受数字四则运算，或 damage("攻击方","防守方","技能")。"""
    tree = ast.parse(str(expr or "").strip(), mode="eval")
    return _eval(tree.body)


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval(node.left)
        right = _eval(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "damage":
        args = []
        for item in node.args:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise ValueError("damage 只收三个名字")
            args.append(item.value)
        if len(args) != 3:
            raise ValueError("damage 只收三个名字")
        from agents.battle_agent import catalog_damage

        got = catalog_damage(args[0], args[1], args[2])
        if not got:
            raise ValueError("名录里算不出这一下")
        return got.get("amount_text") or got.get("amount")
    raise ValueError("这句不能算")


def _code_line(question: str) -> str:
    text = question or ""
    if "damage(" in text:
        start = text.find("damage(")
        end = text.find(")", start)
        if end > start:
            return text[start : end + 1]
    import re

    found = re.search(r"\d+(?:\.\d+)?(?:\s*[\+\-\*/]\s*\d+(?:\.\d+)?)+", text)
    return found.group(0).replace(" ", "") if found else ""


def _find(question: str):
    text = question or ""
    for root in _ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".txt", ".md", ".csv", ".json"}:
                continue
            if path.stem and path.stem in text:
                resolved = path.resolve()
                if _inside(resolved):
                    return resolved
    return None


def _inside(path: Path) -> bool:
    for root in _ROOTS:
        try:
            path.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
