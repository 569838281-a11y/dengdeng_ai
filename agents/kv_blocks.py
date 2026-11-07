"""块级上下文压缩。

只决定这一轮模型读哪些旧块。六人名单、技能、血脉和仓库数量不在这里决定。
必留：权威状态（sink）、最近若干轮对话。其余按当前问句打分，超出预算则丢掉分数最低的旧块。
删套、放生、换招不经过压缩。
拿不到模型注意力时，用同一套哈希特征做 Q·K 点积。
"""
import hashlib
import json
import re
import threading
from pathlib import Path

_VOICE = threading.local()

DEFAULT_BUDGET = 480
_DIM = 128
_STOP = {
    "什么", "怎么", "为何", "为什么", "可以", "这个", "那个", "精灵", "配队",
    "队伍", "一下", "我们", "你们", "还是", "以及", "一个", "如何", "请问",
    "现在", "当前", "针对", "核心", "主力", "因为", "所以", "如果", "不是",
}


def estimate_tokens(text: str) -> int:
    body = text or ""
    if not body:
        return 0
    cjk = sum(1 for char in body if "\u4e00" <= char <= "\u9fff")
    other = len(body) - cjk
    return max(1, cjk + (other + 1) // 2)


def make_block(block_id: str, source: str, text: str, role: str = "", entities=None, sink: bool = False, importance: float = 0.0) -> dict:
    body = (text or "").strip()
    return {
        "id": str(block_id),
        "source": source,
        "role": role,
        "text": body,
        "entities": [item for item in (entities or []) if item],
        "sink": bool(sink),
        "importance": float(importance or 0),
        "tokens": estimate_tokens(body),
    }


def dialogue_blocks(history) -> list:
    blocks = []
    index = 0
    for msg in history or []:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        index += 1
        role = "user" if msg.get("role") == "user" else "assistant"
        blocks.append(make_block(
            f"dlg-{index}",
            "对话",
            content,
            role=role,
            entities=msg.get("entities"),
        ))
    return blocks


def memory_blocks(memories) -> list:
    blocks = []
    for mem in memories or []:
        entities = list(mem.get("key_entities") or [])
        summary = str(mem.get("summary") or "").strip()
        if entities:
            summary = f"{summary} 关键词: {', '.join(entities)}".strip()
        blocks.append(make_block(
            f"mem-{mem.get('id')}",
            "长期记忆",
            summary,
            entities=entities,
            importance=mem.get("importance_score") or 0,
        ))
    return blocks


def evidence_block(block_id: str, text: str, entities=None) -> dict:
    return make_block(block_id, "检索", text, entities=entities)


def is_authoritative_state(text: str) -> bool:
    body = text or ""
    if re.search(r"第\s*\d+\s*套", body) and re.search(r"出场|血脉|技能", body):
        return True
    return "仓库" in body and bool(re.search(r"\d+\s*只", body))


def tool_block(block_id: str, text: str, sink=None, entities=None) -> dict:
    flagged = is_authoritative_state(text) if sink is None else bool(sink)
    return make_block(block_id, "工具", text, sink=flagged, entities=entities)


def state_block(block_id: str, text: str) -> dict:
    return make_block(block_id, "状态", text, sink=True)


def is_disk_write(question: str) -> bool:
    """删套、放生、换招。这些写盘动作不读压缩后的旧上下文。"""
    from agents.battle_orders import (
        _changes_from_text,
        _wants_delete_team,
        _wants_patch,
        _wants_release,
    )

    text = question or ""
    if _wants_delete_team(text) or _wants_release(text):
        return True
    return bool(_wants_patch(text) and _changes_from_text(text))


def _vec(text: str) -> list:
    buckets = [0.0] * _DIM
    chars = [char for char in (text or "") if not char.isspace()]
    grams = list(chars)
    grams.extend(chars[index] + chars[index + 1] for index in range(len(chars) - 1))
    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        slot = int.from_bytes(digest[:2], "little") % _DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        buckets[slot] += sign
    norm = sum(value * value for value in buckets) ** 0.5
    if norm == 0:
        return buckets
    return [value / norm for value in buckets]


def _dot(left: list, right: list) -> float:
    return sum(a * b for a, b in zip(left, right))


def question_entities(question: str, blocks: list) -> list:
    chars = [char for char in (question or "") if "\u4e00" <= char <= "\u9fff"]
    candidates = []
    for size in range(6, 1, -1):
        for index in range(len(chars) - size + 1):
            span = "".join(chars[index:index + size])
            if span in _STOP:
                continue
            if any(span in block["text"] for block in blocks):
                candidates.append(span)
    chosen = []
    for span in candidates:
        if any(span != other and span in other for other in candidates):
            continue
        if span not in chosen:
            chosen.append(span)
    for block in blocks:
        for name in block.get("entities") or []:
            if name and name in (question or "") and name not in chosen:
                chosen.append(name)
    plates = re.findall(r"板块\s*[A-Za-z]", question or "")
    for plate in plates:
        compact = re.sub(r"\s+", "", plate)
        if any(compact in re.sub(r"\s+", "", block["text"]) for block in blocks) and compact not in chosen:
            chosen.append(compact)
    return chosen


def qk_scores(question: str, blocks: list, entities: list) -> list:
    query = _vec(question)
    scores = []
    for block in blocks:
        score = max(0.0, _dot(query, _vec(block["text"])))
        score += 0.25 * float(block.get("importance") or 0)
        if any(entity in block["text"] or entity in "".join(block.get("entities") or []) for entity in entities):
            score += 1.5
        scores.append(score)
    return scores


def mean_observation_attention(matrix, obs_start: int, obs_end: int, spans: list) -> list:
    """matrix[q][k] 为最后一层注意力。对观察窗里的 query 取均值，再对块内 key 取均值。"""
    scores = []
    queries = list(range(max(0, obs_start), max(obs_start, obs_end)))
    if not queries:
        return [0.0 for _ in spans]
    for start, end in spans:
        if end <= start:
            scores.append(0.0)
            continue
        total = 0.0
        for query in queries:
            row = matrix[query] if query < len(matrix) else []
            total += sum(row[start:end])
        scores.append(total / len(queries) / (end - start))
    return scores


def _recent_ids(blocks: list, window_turns: int) -> set:
    if window_turns <= 0:
        return set()
    chosen = set()
    users = 0
    for block in reversed(blocks):
        if block.get("source") != "对话":
            continue
        chosen.add(block["id"])
        if block.get("role") == "user":
            users += 1
        if users >= window_turns:
            break
    return chosen


def entity_hit(entities: list, blocks: list, kept: list) -> float:
    relevant = [entity for entity in entities if any(entity in block["text"] for block in blocks)]
    if not relevant:
        return 1.0
    found = sum(1 for entity in relevant if any(entity in block["text"] for block in kept))
    return found / len(relevant)


def select_blocks(question: str, blocks: list, budget: int = DEFAULT_BUDGET, window_turns: int = 2, attention=None) -> tuple:
    """返回 (保留块, 统计)。保留块按原顺序。"""
    items = [block for block in (blocks or []) if block.get("text")]
    total = sum(block["tokens"] for block in items)
    entities = question_entities(question, items)
    if attention is not None:
        scores = list(attention(question, items))
        scorer = "attention"
    else:
        scores = qk_scores(question, items, entities)
        scorer = "qk"
    if len(scores) != len(items):
        raise ValueError("注意力打分数量与块数量不一致")
    sink_ids = {block["id"] for block in items if block.get("sink")}
    newest_turn = _recent_ids(items, 1 if window_turns >= 1 else 0)
    recent = _recent_ids(items, window_turns)
    ranked = sorted(
        ((scores[index], -index, items[index]) for index in range(len(items))),
        reverse=True,
    )

    kept_ids = []
    used = 0

    def take(block, force: bool) -> None:
        nonlocal used
        if block["id"] in kept_ids:
            return
        if not force and used + block["tokens"] > budget and kept_ids:
            return
        kept_ids.append(block["id"])
        used += block["tokens"]

    for block in items:
        if block["id"] in sink_ids:
            take(block, force=True)
    for block in items:
        if block["id"] in newest_turn:
            take(block, force=True)
    for block in items:
        if block["id"] in recent and block["id"] not in newest_turn and block["id"] not in sink_ids:
            take(block, force=False)
    for _score, _order, block in ranked:
        if block["id"] in kept_ids:
            continue
        take(block, force=False)

    kept = [block for block in items if block["id"] in set(kept_ids)]
    dropped = [block["id"] for block in items if block["id"] not in set(kept_ids)]
    kept_tokens = sum(block["tokens"] for block in kept)
    stats = {
        "budget": budget,
        "input_tokens": total,
        "kept_tokens": kept_tokens,
        "compression_ratio": (total / kept_tokens) if kept_tokens else 1.0,
        "kept_ids": [block["id"] for block in kept],
        "dropped_ids": dropped,
        "entity_hit": entity_hit(entities, items, kept),
        "entities": entities,
        "scorer": scorer,
    }
    return kept, stats


def render(blocks: list) -> str:
    lines = []
    for block in blocks or []:
        if block.get("source") == "对话":
            role = "用户" if block.get("role") == "user" else "助手"
            lines.append(f"{role}：{block['text']}")
        else:
            lines.append(block["text"])
    return "\n".join(lines)


def render_layered(blocks: list) -> str:
    parts = []
    memories = [block for block in blocks or [] if block.get("source") == "长期记忆"]
    dialogue = [block for block in blocks or [] if block.get("source") == "对话"]
    others = [block for block in blocks or [] if block.get("source") not in {"长期记忆", "对话"}]
    if memories:
        parts.append("### 历史记忆（长期）")
        for index, block in enumerate(memories, 1):
            parts.append(f"{index}. {block['text']}")
    if dialogue:
        parts.append("\n### 当前会话（短期）")
        parts.append(render(dialogue))
    if others:
        parts.append("\n### 其他块")
        parts.append(render(others))
    return "\n".join(parts).strip()


def blocks_from_traces(session_id: str, directory, limit: int = 6) -> list:
    """把这一会话已经写过的轨迹收成工具块。不读技能全文。"""
    sid = (session_id or "").strip()
    folder = directory
    if not sid or folder is None or not Path(folder).exists():
        return []
    files = sorted(Path(folder).glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:40]
    found = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("session_id") or "") != sid:
            continue
        question = str(data.get("question") or "").strip()
        answer = str(data.get("answer") or "").strip()
        if not question and not answer:
            continue
        text = f"用户：{question}\n助手：{answer[:500]}"
        found.append(make_block(
            f"trace-{path.stem}",
            "工具",
            text,
            sink=is_authoritative_state(answer),
        ))
        if len(found) >= limit:
            break
    found.reverse()
    return found


def bind_model_context(question: str, history=None, traces=None, budget: int = DEFAULT_BUDGET, extra=None) -> dict:
    """这一线程里，成文前只带挑选后的旧块。写盘命令不带。"""
    if is_disk_write(question):
        stats = {
            "bypassed": True,
            "compression_ratio": 1.0,
            "entity_hit": 1.0,
            "kept_ids": [],
            "dropped_ids": [],
            "input_tokens": 0,
            "kept_tokens": 0,
        }
        _VOICE.text = ""
        _VOICE.stats = stats
        return stats
    from agents.fact_memory import soften_relations

    blocks = soften_relations(question, dialogue_blocks(history) + list(traces or []) + list(extra or []))
    kept, stats = select_blocks(question, blocks, budget=budget)
    stats["bypassed"] = False
    _VOICE.text = render(kept)
    _VOICE.stats = stats
    return stats


def voice_prefix() -> str:
    text = getattr(_VOICE, "text", "") or ""
    if not text.strip():
        return ""
    return "此前留下、且和这一问有关的旧话：\n" + text + "\n\n"


def context_stats() -> dict:
    return dict(getattr(_VOICE, "stats", {}) or {})


def clear_model_context() -> None:
    _VOICE.text = ""
    _VOICE.stats = {}


def pack_history(question: str, history, budget: int = DEFAULT_BUDGET) -> str:
    blocks = dialogue_blocks(history)
    if is_disk_write(question):
        return render(blocks)
    kept, _stats = select_blocks(question, blocks, budget=budget)
    return render(kept)


def pack_memory_text(question: str, memories, history, budget: int = DEFAULT_BUDGET) -> tuple:
    blocks = memory_blocks(memories) + dialogue_blocks(history)
    kept, stats = select_blocks(question, blocks, budget=budget)
    return render_layered(kept), stats


_FENCE = re.compile(r"<context>\n?(.*?)</context>", re.S)


def compress_fenced_context(user_text: str, question: str = "", budget: int = DEFAULT_BUDGET) -> tuple:
    """本地成文前压缩 <context> 里的旧块。没有这段标记则原样返回。"""
    matched = _FENCE.search(user_text or "")
    if not matched:
        return user_text, None
    parts = [part.strip() for part in re.split(r"\n\s*\n", matched.group(1)) if part.strip()]
    blocks = [evidence_block(f"ctx-{index}", part) for index, part in enumerate(parts, 1)]
    query = (question or "").strip() or (user_text[:matched.start()] + user_text[matched.end():]).strip()
    kept, stats = select_blocks(query, blocks, budget=budget, window_turns=0)
    rendered = "\n\n".join(block["text"] for block in kept)
    updated = user_text[:matched.start()] + "<context>\n" + rendered + "\n</context>" + user_text[matched.end():]
    return updated, stats


def rewrite_keeps_anchors(question: str, rewritten: str) -> bool:
    """改写后的查询必须仍含原句里的精灵全名和板块号。"""
    body = rewritten or ""
    for plate in re.findall(r"板块\s*[A-Za-z]", question or ""):
        compact = re.sub(r"\s+", "", plate)
        if compact not in re.sub(r"\s+", "", body):
            return False
    try:
        from pokemon_kb import load_pokemon
        catalog = load_pokemon()
    except Exception:
        catalog = []
    for mon in catalog:
        name = ""
        if isinstance(mon, dict):
            name = str(mon.get("name") or "")
        if name and name in (question or "") and name not in body:
            return False
    return True
