"""不检索的一类，以及记下的数字下次直接用。"""
from agents.adaptive_rag import route_adaptive
from agents.job_ledger import drop
from agents.lived_memory import absorb_exchange, archival_memory_search, core_block, recall_answer
from agents.supervisor import run_cycle


def _wipe(session_id: str) -> None:
    from agents.chat_notebook import _BOOKS, _LOCK, _load_locked, _save_locked

    drop(session_id)
    with _LOCK:
        _load_locked()
        _BOOKS.pop(session_id, None)
        _save_locked()


def test_simple_fields_skip_retrieval_and_chains_stay_multi_step():
    assert route_adaptive("水灵的种族值是多少？") == "A"
    assert route_adaptive("水灵有什么技能") == "A"
    assert route_adaptive("水灵克制什么") == "A"
    assert route_adaptive("水灵使用本系技能，哪个本系技能的威力更高？") == "C"
    assert route_adaptive("闪耀大赛出场率最高的精灵是谁") == "B"


def test_a_number_is_reused_and_an_old_number_expires():
    sid = "mem-number"
    try:
        first = absorb_exchange(sid, "水灵的种族值是多少", "水灵的种族值是攻击120、防御80。")
        assert first == ["ADD"]
        assert "120" in recall_answer(sid, "水灵的种族值是多少")
        again = absorb_exchange(sid, "水灵的种族值是多少", "水灵的种族值是攻击120、防御80。")
        assert again == ["NOOP"]
        changed = absorb_exchange(sid, "水灵的种族值是多少", "水灵的种族值是攻击99。")
        assert changed == ["UPDATE"]
        remembered = recall_answer(sid, "水灵的种族值是多少")
        assert "99" in remembered
        assert "120" not in remembered
        alive = archival_memory_search(sid, "水灵的种族值")
        assert all(edge.get("value") != "攻击120、防御80" for edge in alive)
        assert "99" in core_block(sid)
    finally:
        _wipe(sid)


def test_the_next_turn_uses_the_remembered_number():
    sid = "mem-turn"
    question = "水灵的种族值是多少"
    try:
        absorb_exchange(sid, question, "水灵的种族值是攻击120。")
        cycle = run_cycle(
            question,
            session_id=sid,
            judged={"intent": "search", "request": question},
            review=lambda _q, speech, _evidence=None: {"pass": True, "text": speech},
        )
    finally:
        _wipe(sid)
    assert "120" in cycle["order"]["answer"]
    assert cycle["ledger"]["progress"].get("adaptive") == "A"


if __name__ == "__main__":
    test_simple_fields_skip_retrieval_and_chains_stay_multi_step()
    test_a_number_is_reused_and_an_old_number_expires()
    test_the_next_turn_uses_the_remembered_number()
    print("ok")
