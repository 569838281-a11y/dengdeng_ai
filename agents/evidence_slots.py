"""证据槽与 CRAG 三态（对齐 Self-RAG / CRAG / IRCoT）。

槽类型与证据角色分离：
- rate_champion 只能由「最高/榜首是〔名录实体〕」的 Correct 证据填写
- lineup_members 只能由阵容/前十页填写，禁止升格为 rate_champion
- sprite_* 由名录实体化后的字段填写

CRAG：Correct → 可 Hit；Ambiguous → Bridge/Ask；Incorrect → Miss/Ask。
实体化：原始正则串不得进槽，须名录整名（或后续 Wiki 标题全等）。
"""
from __future__ import annotations

# CRAG 三态
CORRECT = "correct"
AMBIGUOUS = "ambiguous"
INCORRECT = "incorrect"

# 槽
SLOT_RATE_CHAMPION = "rate_champion"
SLOT_LINEUP_MEMBERS = "lineup_members"

# 证据角色
ROLE_RATE_RANK = "rate_rank"  # 含最高/榜首句
ROLE_LINEUP = "lineup_page"  # 阵容/前十/抄作业
ROLE_OTHER = "other"


def evidence_role(text: str, fill: str = "", bridge: str = "") -> str:
    """根据摘录与 fill 判定证据角色（IRCoT：证据决定下一跳槽，不能串槽）。"""
    body = f"{text or ''} {bridge or ''}"
    if (fill or "") == "hit":
        return ROLE_RATE_RANK
    if (fill or "") == "bridge" or bridge:
        return ROLE_LINEUP
    from agents.web_read import _lineup_chatter, _rate_champion_name

    if _rate_champion_name(body):
        return ROLE_RATE_RANK
    if _lineup_chatter(body) or any(word in body for word in ("阵容", "毒队", "出场精灵", "成员")):
        return ROLE_LINEUP
    return ROLE_OTHER


def crag_rate_champion(pool: str, fill: str = "", bridge: str = "", name: str = "") -> dict:
    """对「出场率冠军」槽做 CRAG 判定。只认名录实体化后的冠军句。"""
    from agents.web_read import _catalog_names, _ground_sprite_name, _rate_champion_name

    role = evidence_role(pool, fill=fill, bridge=bridge)
    champion = _rate_champion_name(pool or "")
    if not champion and name:
        champion = _ground_sprite_name(name, allow_unknown=False)
    members = _catalog_names(pool or "")

    if role == ROLE_LINEUP and not champion:
        # 阵容页有成员 ≠ 知道谁最高 → Ambiguous，只能填 lineup_members
        return {
            "status": AMBIGUOUS,
            "slot": SLOT_LINEUP_MEMBERS,
            "action": "bridge_or_ask",
            "champion": "",
            "members": members,
            "role": role,
            "detail": "阵容证据不能升格为出场率冠军",
        }
    if champion:
        return {
            "status": CORRECT,
            "slot": SLOT_RATE_CHAMPION,
            "action": "hit",
            "champion": champion,
            "members": members,
            "role": ROLE_RATE_RANK,
            "detail": "champion_sentence+catalog",
        }
    if members and role != ROLE_LINEUP:
        # 有名但无冠军句 → Ambiguous
        return {
            "status": AMBIGUOUS,
            "slot": SLOT_LINEUP_MEMBERS,
            "action": "ask",
            "champion": "",
            "members": members,
            "role": role,
            "detail": "有名录名但无最高/榜首句",
        }
    return {
        "status": INCORRECT,
        "slot": SLOT_RATE_CHAMPION,
        "action": "miss",
        "champion": "",
        "members": [],
        "role": role,
        "detail": "无可用出场率证据",
    }


def rate_ask_from_members(members: list, label: str = "出场率最高的精灵") -> str:
    shown = "、".join((members or [])[:3])
    if shown:
        return (
            f"灯灯在阵容里看到{shown}，按资料还不敢认定谁是{label}。"
            f"跟灯灯说一下这一处。"
        )
    return f"灯灯还不敢认定{label}。跟灯灯说一下这一处。"
