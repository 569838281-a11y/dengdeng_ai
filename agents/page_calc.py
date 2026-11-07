"""在伤害计算页上打开页面、填入双方名字，并读回页面上的文字。"""
import logging
import re

from agents.external_mcp import get_host, tools_live

logger = logging.getLogger("policy_qa.page_calc")

CALC_URL = "https://lovepvp.top/"
_BOX = re.compile(r"(?:textbox|searchbox|combobox)[^\n]*\[ref=(e\d+)\]")


def operate_damage_page(attacker: str = "", defender: str = "", skill: str = "", host=None) -> str:
    """打开计算页。host 可注入，便于测试。正式运行使用 Playwright MCP。"""
    if host is None:
        if not tools_live():
            return ""
        host = get_host("playwright")
    if host is None:
        return ""
    from agents.thoughts import note_read

    note_read("正在伤害计算页上选精灵")
    try:
        host.call("browser_navigate", {"url": CALC_URL}, timeout=30)
        snap = host.call("browser_snapshot", {}, timeout=20) or ""
        snap = _type_names(host, snap, attacker, defender, skill)
    except Exception as exc:
        logger.warning("计算页未打开：%s", type(exc).__name__)
        return ""
    return (snap or "").strip()


def excerpt(text: str) -> str:
    """只留下带数字的伤害或威力行，避免把整页控件念出来。"""
    kept = []
    for line in (text or "").splitlines():
        body = line.strip()
        if not body or not re.search(r"\d", body):
            continue
        if "伤害" in body or "威力" in body:
            kept.append(body)
        if len(kept) >= 2:
            break
    if not kept:
        return ""
    return "伤害计算页读到：" + " ".join(kept)


def _type_names(host, snap: str, attacker: str, defender: str, skill: str) -> str:
    boxes = _BOX.findall(snap or "")
    names = [item for item in (attacker, defender, skill) if item]
    if not boxes or not names:
        return snap
    for ref, name in zip(boxes, names):
        try:
            host.call("browser_type", {"target": ref, "text": name}, timeout=15)
        except Exception:
            return snap
    try:
        host.call("browser_press_key", {"key": "Enter"}, timeout=10)
        return host.call("browser_snapshot", {}, timeout=15) or snap
    except Exception:
        return snap
