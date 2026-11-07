"""事实记忆：同一栏目后写覆盖前写，问到的精灵强制留下。不写名录。"""
import tempfile
from pathlib import Path

import agents.chat_notebook as nb
from agents.fact_memory import fact_blocks, list_facts, rank_facts
from agents.kv_blocks import bind_model_context, clear_model_context, voice_prefix


def test_entity_fact_survives_tight_budget():
    original_path = nb._PATH
    original_books = dict(nb._BOOKS)
    nb._BOOKS.clear()
    nb._PATH = Path(tempfile.mkdtemp()) / "chat_notebooks.json"
    try:
        nb.learn("case", "水灵是水系的")
        nb.learn("case", "火神的标签是【输出】")
        nb.learn("case", "水灵是草系的")
        facts = list_facts("case")
        water = [fact for fact in facts if fact["entity"] == "水灵" and fact["field"] == "属性"]
        assert water and water[0]["value"] == "草"
        ranked = rank_facts("水灵的全部信息", facts)
        assert ranked[0]["entity"] == "水灵"
        assert ranked[0]["entity_hit"] == 1.0
        blocks = fact_blocks("case", "水灵的全部信息")
        assert blocks[0]["sink"] is True
        assert any(not block["sink"] for block in blocks)
        filler = []
        for index in range(6):
            filler.append({"role": "user", "content": f"闲聊第{index}轮。" + "今天天气不错我们随便聊聊" * 8})
            filler.append({"role": "assistant", "content": "好的，继续说别的。" + "今天天气不错我们随便聊聊" * 8})
        stats = bind_model_context("水灵的全部信息", filler, extra=blocks, budget=40)
        prefix = voice_prefix()
        assert "水灵的属性是草" in prefix
        assert "fact-水灵-属性" in stats["kept_ids"]
        clear_model_context()
    finally:
        clear_model_context()
        nb._PATH = original_path
        nb._BOOKS.clear()
        nb._BOOKS.update(original_books)


if __name__ == "__main__":
    test_entity_fact_survives_tight_budget()
    print("ok")
