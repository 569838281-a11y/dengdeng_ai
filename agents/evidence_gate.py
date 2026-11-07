"""证据充足性闸门（对齐 Self-RAG / SURE-RAG / HALT / Q-CARE）。

相关命中不等于证据充足。每种 hop 有契约；读完后判 support / partial / insufficient；
开口前按原问 claims 做覆盖检查，不够则升格、再检或问人，禁止半证据收束结论。
"""
from __future__ import annotations

import re

# SURE-RAG 三态
SUPPORT = "support"
PARTIAL = "partial"
INSUFFICIENT = "insufficient"

_POWER = re.compile(r"威力\s*(\d+)")
_MIN_COMPARE_SKILLS = 2


def contract_for(fact: str) -> dict:
    """这一跳「齐全」要什么。供验收与审计，不依赖模型临场发挥。"""
    body = fact or ""
    if _rate_like(body):
        return {
            "kind": "rate_champion",
            "need": "冠军句或名录精灵名（最高/榜首是谁）",
            "min_power_rows": 0,
            "escalate": "bridge_or_ask",
        }
    if body.endswith("的技能和威力") or body.endswith("的本系技能和威力"):
        return {
            "kind": "skill_compare",
            "need": f"至少 {_MIN_COMPARE_SKILLS} 条带威力数字的招式行，且池尽量读全",
            "min_power_rows": _MIN_COMPARE_SKILLS,
            "escalate": "full_pool",
        }
    if body.endswith("的技能"):
        return {
            "kind": "skill_list",
            "need": "技能池至少一类非空（自带/血脉/技能石）",
            "min_power_rows": 0,
            "escalate": "full_card",
        }
    if body.endswith("的属性"):
        return {
            "kind": "type_field",
            "need": "属性行含系别",
            "min_power_rows": 0,
            "escalate": "card_record",
        }
    if body.endswith(("的种族值", "的特性", "的能耗")):
        return {
            "kind": "card_field",
            "need": "对应字段至少一行",
            "min_power_rows": 0,
            "escalate": "card_record",
        }
    if "倍率" in body or body in {"伤害公式", "这一下的最终伤害数字"}:
        return {
            "kind": "rules",
            "need": "规则原文行",
            "min_power_rows": 0,
            "escalate": "rules_parent",
        }
    return {
        "kind": "generic",
        "need": "非空原文",
        "min_power_rows": 0,
        "escalate": "ask",
    }


def judge_sufficiency(fact: str, lines: list, meta: dict = None) -> dict:
    """Self-RAG/SURE-RAG：对当前 hop 证据打三态，并给出动作。"""
    meta = meta or {}
    contract = contract_for(fact)
    rows = [str(item or "").strip() for item in (lines or []) if str(item or "").strip()]
    kind = contract["kind"]
    if kind == "rate_champion":
        return _rate_gate(fact, rows, meta, contract)
    if kind == "skill_compare":
        return _skill_compare_gate(fact, rows, meta, contract)
    if kind == "skill_list":
        return _skill_list_gate(fact, rows, meta, contract)
    if kind == "type_field":
        if any("属性" in row or "系" in row for row in rows):
            return _ok(contract, rows)
        return _bad(INSUFFICIENT, contract, "没有属性行", "card_record")
    if kind == "card_field":
        if rows:
            return _ok(contract, rows)
        return _bad(INSUFFICIENT, contract, "字段为空", "card_record")
    if kind == "rules":
        if rows:
            return _ok(contract, rows)
        return _bad(INSUFFICIENT, contract, "规则未命中", "rules_parent")
    if rows:
        return _ok(contract, rows)
    return _bad(INSUFFICIENT, contract, "没有原文", "ask")


def halt_claims(question: str, hops: list = None, speech: str = "") -> list:
    """HALT：原问拆成必答 claims。每项含 id、label、covered。"""
    from agents.fact_read import _APPEAR, _chain_question, _power_tail, _strongest_hit, _targets

    text = question or ""
    hops = hops or []
    spoken = speech or ""
    done = {str(item.get("fact") or "") for item in hops if item.get("text")}
    blob = "\n".join(str(item.get("text") or "") for item in hops) + "\n" + spoken
    claims = []

    def add(cid: str, label: str, covered: bool):
        claims.append({"id": cid, "label": label, "covered": covered})

    if _APPEAR.search(text) and "精灵" in text:
        rate_done = any(_rate_like(fact) for fact in done) or bool(
            re.search(r"(最高|榜首|第一).{0,8}是[\u4e00-\u9fff]{2,8}|是[\u4e00-\u9fff]{2,8}", blob)
        )
        add("rate", "出场率/登场率最高的精灵", rate_done)
    skill_done = False
    if _strongest_hit(text) or ("本系" in text and "威力" in text):
        skill_done = any(_power_tail(fact) for fact in done) and bool(_POWER.search(blob))
        # 半池拒答也算「处理过」这一 claim，避免死循环；但 critique 仍可标 partial
        skill_handled = skill_done or ("不敢比威力" in blob)
        add("max_skill", "威力最大的技能", skill_handled)
    if any(word in text for word in ("多少伤害", "打出多少", "伤害量", "能打出")):
        dmg_num = bool(re.search(r"伤害量是\s*\d+", blob))
        # 半池拒答 / 明确算不出也算 claim 已处理，避免 HALT 死循环。
        dmg_settled = dmg_num or any(
            word in blob for word in ("不敢比威力", "算不出", "还缺：")
        ) or (
            skill_done and "性格没有写在威力规则里" in blob
        )
        add("damage", "这一下的伤害数字或已说明算不出", dmg_settled)
    if "打" in text or "攻击" in text:
        for name in _targets(text):
            covered = any(
                str(item.get("fact") or "") == f"{name}的属性" and item.get("text")
                for item in hops
            ) or bool(re.search(r"伤害量是\s*\d+", blob)) or ("性格没有写在威力规则里" in blob)
            add(f"def_{name}", f"{name}的属性或伤害结算", covered)
    if not claims and _chain_question(text):
        add("chain", "多跳证据链", bool(hops))
    return claims


def halt_ready(question: str, hops: list, speech: str = "") -> dict:
    """开口前覆盖检查。未齐 → missing claims；齐了才允许 speak。"""
    claims = halt_claims(question, hops, speech)
    missing = [item for item in claims if not item.get("covered")]
    return {
        "ok": not missing,
        "claims": claims,
        "missing": missing,
        "ask": _halt_ask(missing),
    }


def critique_answer(question: str, speech: str, hops: list = None) -> dict:
    """Self-RAG 式轻量 critique：答案是否被 hop 证据支持、是否越权收束。"""
    text = (speech or "").strip()
    hops = hops or []
    issues = []
    if not text:
        return {"pass": False, "issues": ["empty"], "relation": INSUFFICIENT}
    halt = halt_ready(question, hops, text)
    # 主动承认不齐是合法 abstain，不算 critique 失败。
    if any(word in text for word in ("不敢比威力", "还缺：", "还不敢认定", "跟灯灯说一下")):
        return {
            "pass": True,
            "issues": ["abstain"],
            "relation": PARTIAL,
            "halt": halt,
        }
    if not halt["ok"]:
        issues.append("coverage")
    skill_hop = any(
        str(item.get("fact") or "").endswith(("的技能和威力", "的本系技能和威力"))
        for item in hops
    )
    if re.search(r"威力最大|同为\d+", text) and not skill_hop:
        issues.append("unsupported_max")
    power_rows = sum(
        1
        for item in hops
        for line in (item.get("lines") or [item.get("text") or ""])
        if _POWER.search(str(line or ""))
    )
    if "威力最大" in text and power_rows < _MIN_COMPARE_SKILLS:
        issues.append("partial_compare")
    if issues:
        relation = PARTIAL if "partial_compare" in issues else INSUFFICIENT
        return {"pass": False, "issues": issues, "relation": relation, "halt": halt}
    return {"pass": True, "issues": [], "relation": SUPPORT, "halt": halt}


def _rate_like(fact: str) -> bool:
    return any(word in (fact or "") for word in ("出场率", "登场率", "使用率"))


def _rate_gate(fact: str, rows: list, meta: dict, contract: dict) -> dict:
    blob = " ".join(rows) + " " + str(meta.get("text") or "")
    from agents.evidence_slots import AMBIGUOUS, CORRECT, INCORRECT, crag_rate_champion

    judged = crag_rate_champion(
        blob,
        fill=str(meta.get("fill") or ""),
        bridge=str(meta.get("bridge") or ""),
        name=str(meta.get("name") or ""),
    )
    if judged.get("status") == CORRECT and judged.get("champion"):
        return _ok(contract, rows, note=f"champion={judged['champion']}")
    if judged.get("status") == AMBIGUOUS or meta.get("fill") == "bridge" or meta.get("bridge"):
        return _bad(PARTIAL, contract, judged.get("detail") or "阵容证据不能升格为冠军", "bridge")
    if judged.get("status") == INCORRECT and rows:
        return _bad(PARTIAL, contract, judged.get("detail") or "无可靠冠军名", "bridge_or_ask")
    return _bad(INSUFFICIENT, contract, judged.get("detail") or "没有出场率证据", "ask")


def _skill_compare_gate(fact: str, rows: list, meta: dict, contract: dict) -> dict:
    powered = [row for row in rows if _POWER.search(row)]
    pool_complete = bool(meta.get("pool_complete"))
    if len(powered) >= contract["min_power_rows"] and (pool_complete or len(powered) >= 3):
        return _ok(contract, powered, note=f"power_rows={len(powered)}")
    if powered:
        return _bad(
            PARTIAL,
            contract,
            f"只有 {len(powered)} 条带威力的招，比较会读窄",
            "full_pool",
            powered=powered,
        )
    if rows:
        return _bad(PARTIAL, contract, "有技能行但无威力数字", "full_pool")
    return _bad(INSUFFICIENT, contract, "技能池为空", "ask")


def _skill_list_gate(fact: str, rows: list, meta: dict, contract: dict) -> dict:
    blob = " ".join(rows)
    if "技能池是空的" in blob:
        return _bad(INSUFFICIENT, contract, "技能池空", "ask")
    if any(word in blob for word in ("自带", "血脉", "技能石")) and "未提供" not in blob.replace("自带：未提供", "").replace("血脉：未提供", ""):
        # 至少一类有名
        if re.search(r"(自带|血脉|技能石)：(?!未提供).+", blob):
            return _ok(contract, rows)
    if rows:
        return _bad(PARTIAL, contract, "技能列表不完整", "full_card")
    return _bad(INSUFFICIENT, contract, "没有技能列表", "ask")


def _ok(contract: dict, rows: list, note: str = "") -> dict:
    return {
        "status": SUPPORT,
        "contract": contract,
        "action": "accept",
        "rows": list(rows),
        "detail": note or "support",
    }


def _bad(status: str, contract: dict, detail: str, action: str, powered: list = None) -> dict:
    return {
        "status": status,
        "contract": contract,
        "action": action,
        "rows": list(powered or []),
        "detail": detail,
    }


def _halt_ask(missing: list) -> str:
    if not missing:
        return ""
    labels = "、".join(item.get("label") or item.get("id") or "这一处" for item in missing[:3])
    return f"灯灯还缺：{labels}。跟灯灯说一下，或等灯灯再翻一整段资料。"
