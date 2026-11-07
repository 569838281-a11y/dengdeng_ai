"""原型循环：原句数量不被改写，向量库缺失时中文分词仍能召回。"""
import knowledge_search
from agents.work_cycle import prepare_turn


def test_release_is_not_rewritten():
    def explode(_prompt):
        raise AssertionError("放生不该改写")

    prepared = prepare_turn(
        "放生海枝枝",
        [{"role": "user", "content": "仓库里有海枝枝"}],
        "",
        invoke=explode,
    )
    assert prepared["query"] == "放生海枝枝"
    assert "keep" in prepared["steps"]


def test_rewrite_keeps_sprite_and_bm25_hits():
    history = [
        {"role": "user", "content": "我们在看水灵"},
        {"role": "assistant", "content": "水灵在名录里"},
    ]

    def rewrite(_prompt):
        return "水灵的种族值"

    prepared = prepare_turn("那种族值呢", history, "", invoke=rewrite)
    assert prepared["query"] == "水灵的种族值"
    assert any("水灵" in (hit["title"] + hit["text"]) for hit in prepared["hits"])


def test_added_count_is_dropped():
    history = [{"role": "user", "content": "看看水灵"}]

    def rewrite(_prompt):
        return "放生一只水灵"

    prepared = prepare_turn("水灵怎么样", history, "", invoke=rewrite)
    assert prepared["query"] == "水灵怎么样"


def test_vector_gap_uses_bm25():
    original = knowledge_search.ensure_knowledge_index
    knowledge_search.ensure_knowledge_index = lambda: (None, "skip", "向量库未就绪")
    try:
        hits, status, detail, state = knowledge_search.retrieve_passages("水灵的属性")
    finally:
        knowledge_search.ensure_knowledge_index = original
    assert status == "done"
    assert state == "bm25"
    assert "正在看" in detail
    assert "水灵" in detail
    assert any("水灵" in (hit["title"] + hit["text"]) for hit in hits)


if __name__ == "__main__":
    test_release_is_not_rewritten()
    test_rewrite_keeps_sprite_and_bm25_hits()
    test_added_count_is_dropped()
    test_vector_gap_uses_bm25()
    print("ok")
