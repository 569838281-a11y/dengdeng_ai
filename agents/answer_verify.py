"""三种核对盯同一句草稿。

Chain-of-Verification 核最终那一句，回答核查问题时不看草稿。
Verify-and-Edit 改比较这一步，再用改过的倍率重写答案。
Self-RAG 只判断这句能不能说，不把威力乘上克制，也不再开一轮检索。
"""
import re


def review_draft(question: str, steps: list, skill: dict, draft: str) -> dict:
    """三种核对共用草稿里的那句错结论。开口只采用两处修订一致的句子。"""
    verdict = _verdict_sentence(draft)
    cove = chain_of_verification(question, steps, skill, verdict)
    edited = verify_and_edit(question, steps, skill, verdict)
    rag = self_rag(question, steps, skill, verdict)
    spoken = ""
    if (
        cove.get("skill")
        and cove.get("skill") == edited.get("skill")
        and cove.get("score") == edited.get("score")
    ):
        spoken = edited.get("revised") or ""
    elif rag.get("adopt"):
        spoken = verdict
    note = ""
    claimed = _claimed_winner(verdict)
    if spoken and claimed and claimed != cove.get("skill"):
        note = f"对战员核对过「{verdict}」这句没有用上克制，开口改成{cove.get('skill')}。"
    return {
        "draft": verdict,
        "cove": cove,
        "verify_edit": edited,
        "self_rag": rag,
        "spoken": spoken,
        "note": note,
    }


def chain_of_verification(question: str, steps: list, skill: dict, verdict: str) -> dict:
    """先计划核查问题，再单独回答。回答函数拿不到草稿。"""
    facts = _catalog_facts(question, steps, skill)
    answers = _answer_without_draft(facts)
    revised = _revised_sentence(facts)
    power_name, power_value = _highest_written_power(skill)
    power_answer = f"{power_name}，{power_value}" if power_name else ""
    return {
        "name": "Chain-of-Verification",
        "sees": "最终那一句",
        "draft_given_to_answers": False,
        "questions": [item["question"] for item in answers],
        "answers": answers,
        "revised": revised,
        "skill": facts.get("skill") or "",
        "score": facts.get("score") or "",
        "power_only_question": "哪个威力数字大",
        "power_only_answer": power_answer,
        "power_only_revised": verdict,
    }


def verify_and_edit(question: str, steps: list, skill: dict, verdict: str) -> dict:
    """比较步骤没写克制，就另查倍率，改写这一步，再重写答案。"""
    facts = _catalog_facts(question, steps, skill)
    pairs = [f"{item['attack']}打{item['defend']}" for item in facts.get("rates") or []]
    question_text = ("和".join(pairs) + "各是几倍") if pairs else ""
    edited = "。".join(
        f"{item['attack']}打{item['defend']}的倍率是{item['rate']}" for item in facts.get("rates") or []
    )
    if edited:
        edited += "。比较改为威力乘这些倍率。"
    return {
        "name": "Verify-and-Edit",
        "sees": "比较这一步",
        "uncertain": "克制" not in (verdict or "") and "更高" in (verdict or ""),
        "question": question_text,
        "edited_step": edited,
        "revised": _revised_sentence(facts),
        "skill": facts.get("skill") or "",
        "score": facts.get("score") or "",
    }


def self_rag(question: str, steps: list, skill: dict, verdict: str) -> dict:
    """威力原句可以有支撑。没写克制的「更高」不能说。这里不算出新的数字。"""
    from agents.battle_agent import _defender_types

    defender, _types = _defender_types(question, steps)
    name, power = _claimed_power(verdict)
    lines = _skill_lines(skill)
    power_grade = "对得上" if name and power and _line_has_power(lines, name, power) else "对不上"
    needs_matchup = "攻击" in (question or "") or "打" in (question or "")
    if needs_matchup and "克制" not in (verdict or ""):
        higher_grade = "对不上"
    elif needs_matchup and not _rate_matches(verdict, name, steps, skill):
        higher_grade = "对不上"
    else:
        higher_grade = "对得上"
    adopt = power_grade == "对得上" and higher_grade == "对得上"
    higher = f"打{defender}时它更高" if defender else "它更高"
    note = ""
    if not adopt:
        note = "不采用这句。有没有用上克制交给另外两处核对，这里不再开一轮检索。"
    return {
        "name": "Self-RAG",
        "sees": "这句能不能说",
        "claims": [
            {"text": f"{name}的威力是{power}" if name else "威力", "grade": power_grade},
            {"text": higher, "grade": higher_grade},
        ],
        "adopt": adopt,
        "revised": "",
        "search_again": False,
        "note": note,
    }


def format_report(report: dict) -> str:
    """把三种核对的结果排成同一份对照。"""
    cove = report.get("cove") or {}
    edited = report.get("verify_edit") or {}
    rag = report.get("self_rag") or {}
    lines = [f"草稿：{report.get('draft') or ''}"]
    lines.append("Chain-of-Verification 看最终那一句。核查问题单独回答：")
    for item in cove.get("answers") or []:
        lines.append(f"  {item.get('question')} → {item.get('answer')}")
    lines.append(f"  修订：{cove.get('revised') or ''}")
    lines.append(
        f"  若核查问题是「{cove.get('power_only_question')}」，回答是{cove.get('power_only_answer')}，修订仍是{cove.get('power_only_revised')}"
    )
    lines.append("Verify-and-Edit 看比较这一步。")
    lines.append(f"  核查问题：{edited.get('question') or ''}")
    lines.append(f"  改写的步骤：{edited.get('edited_step') or ''}")
    lines.append(f"  修订：{edited.get('revised') or ''}")
    lines.append("Self-RAG 看这句能不能说。")
    for claim in rag.get("claims") or []:
        lines.append(f"  {claim.get('text')}：{claim.get('grade')}")
    lines.append(f"  {rag.get('note') or ''}")
    lines.append(f"开口采用：{report.get('spoken') or ''}")
    return "\n".join(lines)


def _verdict_sentence(draft: str) -> str:
    matched = re.search(r"本系攻击技能里，.+?。", draft or "")
    if matched:
        return matched.group(0)
    return (draft or "").strip()


def _claimed_winner(verdict: str) -> str:
    name, _power = _claimed_power(verdict)
    return name


def _claimed_power(verdict: str):
    matched = re.search(r"本系攻击技能里，(.+?)的威力更高，是\s*(\d+)", verdict or "")
    if not matched:
        return "", ""
    return matched.group(1), matched.group(2)


def _catalog_facts(question: str, steps: list, skill: dict) -> dict:
    """只读图鉴和已经对上的原文。没有草稿这个参数。"""
    from agents.battle_agent import _defender_types, _rank_skills, _skills, type_multiplier, _rate_text

    defender, defend_types = _defender_types(question, steps)
    ranked = _rank_skills(skill, defend_types) if defender and defend_types else []
    cards = _skills()
    attack_types = []
    detailed = []
    for item in ranked:
        card = cards.get(item["name"]) or {}
        attack = card.get("type") or ""
        if attack and attack not in attack_types:
            attack_types.append(attack)
        detailed.append({
            "name": item["name"],
            "power": item["power"],
            "attack": attack,
            "rate": item["rate"],
            "score": item["score"],
            "score_text": item["score_text"],
        })
    rates = []
    for attack in attack_types:
        for defend in defend_types:
            rates.append({
                "attack": attack,
                "defend": defend,
                "rate": _rate_text(type_multiplier(attack, [defend])),
            })
    winner = {}
    if detailed:
        winner = max(detailed, key=lambda item: item["score"])
    return {
        "defender": defender,
        "rates": rates,
        "skills": detailed,
        "skill": winner.get("name") or "",
        "score": winner.get("score_text") or "",
        "power": winner.get("power") or "",
        "rate": winner.get("rate") or "",
    }


def _answer_without_draft(facts: dict) -> list:
    answers = []
    for item in facts.get("rates") or []:
        answers.append({
            "question": f"{item['attack']}打{item['defend']}的倍率",
            "answer": item["rate"],
        })
    powers = "。".join(f"{item['name']}的威力是{item['power']}" for item in facts.get("skills") or [])
    answers.append({"question": "这些本系攻击技能的威力", "answer": powers})
    return answers


def _revised_sentence(facts: dict) -> str:
    if not facts.get("skill"):
        return ""
    return (
        f"本系攻击技能打{facts['defender']}时，{facts['skill']}算上克制后更高，"
        f"威力{facts['power']}，克制倍率{facts['rate']}，合起来是{facts['score']}。"
    )


def _highest_written_power(skill: dict):
    best = ("", -1)
    for line in _skill_lines(skill):
        matched = re.search(r"威力\s*(\d+)", line)
        if not matched:
            continue
        power = int(matched.group(1))
        name = line.split("｜", 1)[0].strip()
        if power > best[1]:
            best = (name, power)
    if best[1] < 0:
        return "", ""
    return best[0], str(best[1])


def _skill_lines(skill: dict) -> list:
    lines = list(skill.get("lines") or [])
    if not lines and skill.get("text"):
        lines = [skill["text"]]
    return [line.strip() for line in lines if (line or "").strip()]


def _line_has_power(lines: list, name: str, power: str) -> bool:
    for line in lines:
        if name in line and re.search(rf"威力\s*{power}(?!\d)", line):
            return True
    return False


def _rate_matches(verdict: str, name: str, steps: list, skill: dict) -> bool:
    facts = _catalog_facts("", steps, skill)
    matched = re.search(r"克制倍率\s*([0-9.]+)", verdict or "")
    if not matched or not name:
        return False
    for item in facts.get("skills") or []:
        if item["name"] == name:
            return item["rate"] == matched.group(1)
    return False
