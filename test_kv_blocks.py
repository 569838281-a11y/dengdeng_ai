"""块级记忆压缩的验收。不加载模型，不写仓库。"""
from agents.kv_blocks import (
    compress_fenced_context,
    dialogue_blocks,
    evidence_block,
    mean_observation_attention,
    pack_history,
    pack_memory_text,
    rewrite_keeps_anchors,
    select_blocks,
    state_block,
    tool_block,
)


def _turn(user: str, assistant: str) -> list:
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def test_keeps_recent_needle_and_drops_filler():
    history = []
    history += _turn("水灵会使用潮涌", "记下了水灵")
    for index in range(4):
        history += _turn(f"闲聊第{index}句不提名字", "好的继续说别的")
    history += _turn("最近在问别的事情", "这一轮先这样")
    history += _turn("再补一句近况", "收到近况")
    blocks = dialogue_blocks(history)
    kept, stats = select_blocks("水灵的技能是什么", blocks, budget=80)
    text = "\n".join(block["text"] for block in kept)
    assert "水灵" in text
    assert stats["entity_hit"] == 1.0
    assert stats["compression_ratio"] > 1
    assert stats["dropped_ids"]
    assert "dlg-1" in stats["kept_ids"]
    assert stats["scorer"] == "qk"


def test_sink_survives_tight_budget():
    blocks = [
        evidence_block("ret-1", "无关的长证据" * 40),
        state_block("state-1", "仓库里水灵2只，海枝枝1只。"),
        *dialogue_blocks(_turn("今天先看看别的", "好")),
    ]
    kept, stats = select_blocks("今天吃什么", blocks, budget=30)
    assert "state-1" in stats["kept_ids"]
    assert "ret-1" in stats["dropped_ids"]


def test_tool_state_is_sink():
    block = tool_block("tool-1", "第14套出场：水灵，血脉初始血脉，技能潮涌。")
    assert block["sink"] is True


def test_disk_write_skips_compression():
    history = _turn("水灵会潮涌这是很旧的一句", "旧答复")
    history += _turn("闲聊甲", "闲聊乙")
    history += _turn("闲聊丙", "闲聊丁")
    packed = pack_history("放生一只水灵", history, budget=20)
    assert "水灵会潮涌" in packed
    normal = pack_history("今天天气如何", history, budget=20)
    assert "水灵会潮涌" not in normal


def test_attention_overrides_lexical():
    blocks = [
        evidence_block("a", "完全无关的内容甲" * 5),
        evidence_block("b", "水灵的技能说明"),
    ]
    kept, stats = select_blocks(
        "水灵",
        blocks,
        budget=15,
        window_turns=0,
        attention=lambda _question, items: [5.0, 0.0],
    )
    assert stats["scorer"] == "attention"
    assert [block["id"] for block in kept] == ["a"]


def test_observation_attention_picks_looked_at_span():
    matrix = [
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0.7, 0.7, 0.05, 0],
    ]
    scores = mean_observation_attention(matrix, 3, 4, [(0, 2), (2, 3)])
    assert scores[0] > scores[1]


def test_memory_pack_keeps_named_page():
    memories = [
        {"id": 1, "summary": "用户问过水灵的技能", "key_entities": ["水灵"], "importance_score": 0.4},
        {"id": 2, "summary": "另一段无关政策说明", "key_entities": ["健身"], "importance_score": 0.9},
    ]
    history = _turn("近况一句", "近况答复")
    text, stats = pack_memory_text("水灵呢", memories, history, budget=40)
    assert "水灵" in text
    assert "mem-1" in stats["kept_ids"]


def test_fenced_context_drops_unrelated():
    user = "水灵的技能\n<context>\n水灵：潮涌，水系。\n\n" + ("无关段落。" * 30) + "\n</context>"
    updated, stats = compress_fenced_context(user, "水灵的技能", budget=30)
    assert "潮涌" in updated
    assert stats["dropped_ids"]


def test_voice_prefix_keeps_needle_and_skips_release():
    import json
    import tempfile
    from pathlib import Path

    from agents.kv_blocks import bind_model_context, blocks_from_traces, clear_model_context, voice_prefix

    history = []
    history += _turn("水灵会使用潮涌", "记下了水灵")
    for index in range(6):
        history += _turn(f"闲聊第{index}句不提名字", "好的继续说别的")
    stats = bind_model_context("水灵的技能是什么", history, budget=80)
    prefix = voice_prefix()
    assert "水灵" in prefix and "潮涌" in prefix
    assert stats["entity_hit"] == 1.0
    assert stats["compression_ratio"] > 1
    assert stats["bypassed"] is False
    clear_model_context()
    released = bind_model_context("放生一只水灵", history, budget=20)
    assert voice_prefix() == ""
    assert released["bypassed"] is True
    clear_model_context()

    folder = Path(tempfile.mkdtemp())
    (folder / "a.json").write_text(
        json.dumps({
            "session_id": "s1",
            "question": "水灵会潮涌",
            "answer": "记下了水灵",
            "skill_text": "x" * 4000,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (folder / "b.json").write_text(
        json.dumps({"session_id": "s2", "question": "别的会话", "answer": "别的"}, ensure_ascii=False),
        encoding="utf-8",
    )
    blocks = blocks_from_traces("s1", folder)
    assert len(blocks) == 1
    assert "潮涌" in blocks[0]["text"]
    assert "xxxx" not in blocks[0]["text"]


def test_rewrite_keeps_sprite_and_plate():
    assert rewrite_keeps_anchors("板块 M 里水灵怎么算伤害", "板块 M 水灵 伤害")
    assert not rewrite_keeps_anchors("板块 M 里水灵怎么算伤害", "伤害计算")
    assert not rewrite_keeps_anchors("水灵的种族值", "种族值")


if __name__ == "__main__":
    test_keeps_recent_needle_and_drops_filler()
    test_sink_survives_tight_budget()
    test_tool_state_is_sink()
    test_disk_write_skips_compression()
    test_attention_overrides_lexical()
    test_observation_attention_picks_looked_at_span()
    test_memory_pack_keeps_named_page()
    test_fenced_context_drops_unrelated()
    test_voice_prefix_keeps_needle_and_skips_release()
    test_rewrite_keeps_sprite_and_plate()
    print("ok")
