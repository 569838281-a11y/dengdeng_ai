"""调度图：不可行的工具不执行，两路结果归约成一份账本，能回到上一步。"""
from agents.cycle_graph import choose_tool, dispatch_brief, feasible, reduce_branches, restore_previous
from pokemon_kb import _split_entries


def test_infeasible_web_stays_on_the_program_word():
    ledger = {"constraints": {"intent": "order"}, "gap": {"kind": "meta", "label": "热门"}, "progress": {}, "facts": [{"id": "a"}]}

    def ask(_ledger, _word):
        return "need_web"

    assert choose_tool(ledger, "need_local", ask) == "need_local"
    assert ledger["progress"]["rejected_tool"] == "need_web"
    assert ledger["facts"] == [{"id": "a"}]
    assert feasible(ledger, "need_web") is False


def test_lineup_may_switch_to_both_slots():
    ledger = {"constraints": {"intent": "lineup"}, "gap": {"kind": "meta", "label": "热门"}, "progress": {}}
    assert choose_tool(ledger, "need_local", ask=lambda *_args: "need_both") == "need_both"


def test_chain_keeps_the_program_word():
    ledger = {
        "constraints": {"intent": "search"},
        "gap": {"kind": "identity", "label": "闪耀大赛登场率最高的精灵"},
        "progress": {"hop_kind": "chain", "hop_fact": "出场率最高的精灵", "hops": []},
        "slots": {"local": "empty", "web": "closed", "tried": ["local"]},
    }
    assert choose_tool(ledger, "need_web", ask=lambda *_args: "need_lineup") == "need_web"
    assert choose_tool(ledger, "need_web", ask=lambda *_args: "need_both") == "need_web"
    assert feasible(ledger, "need_lineup") is False
    assert feasible(ledger, "need_both") is False
    brief = dispatch_brief(ledger, "need_web")
    assert "当前只补" in brief
    assert "出场率最高的精灵" in brief
    assert "名单" not in brief


def test_check_is_not_asked():
    called = {"n": 0}

    def ask(_ledger, _word):
        called["n"] += 1
        return "need_web"

    ledger = {"constraints": {"intent": "lineup"}, "progress": {}}
    assert choose_tool(ledger, "check", ask) == "check"
    assert choose_tool(ledger, "speak", ask) == "speak"
    assert called["n"] == 0


def test_repeat_local_returns_to_the_program_word():
    ledger = {
        "constraints": {"intent": "lineup"},
        "gap": {"kind": "meta", "label": "热门"},
        "slots": {"local": "filled", "web": "closed", "tried": ["local"]},
        "facts": [{"covers": "warehouse", "text": "仓库里有6只"}],
        "progress": {"opened": [{"word": "need_local", "kind": "meta", "label": "热门"}]},
    }
    called = {"n": 0}

    def ask(_ledger, _word):
        called["n"] += 1
        return "need_local"

    assert choose_tool(ledger, "need_lineup", ask) == "need_lineup"
    assert called["n"] == 2
    assert ledger["progress"]["rejected_tool"] == "need_local"
    assert "已经试过" in ledger["progress"]["reject_reason"]


def test_second_ask_can_take_a_legal_word():
    ledger = {"constraints": {"intent": "order"}, "utterance": "放生海枝枝", "progress": {}}

    def ask(book, _word):
        if book["progress"].get("reject_reason"):
            return "need_ask"
        return "need_web"

    assert choose_tool(ledger, "need_write", ask) == "need_write"
    assert ledger["progress"]["rejected_tool"] == "need_ask"
    assert feasible(ledger, "need_ask") is False


def test_release_brief_says_the_count_is_open():
    ledger = {
        "utterance": "放生海枝枝",
        "constraints": {"intent": "order"},
        "progress": {},
        "slots": {"local": "closed", "web": "closed", "tried": []},
        "facts": [],
        "guesses": [],
        "roster": [],
        "check": {},
    }
    text = dispatch_brief(ledger, "need_write")
    assert "只数还空着" in text
    assert "做完了没有" in text
    assert "是不是在重复" in text
    assert "有没有新的事实或名单" in text
    assert "程序建议 need_write" in text


def test_reduce_keeps_one_roster_and_separate_evidence():
    base = {"roster": ["水灵"], "slots": {"local": "closed", "web": "closed", "tried": []}, "facts": [], "guesses": []}
    local = {
        "facts": [{"id": "fact-1", "authority": "catalog", "text": "仓库里有6只"}],
        "requests": [{"id": "req-1", "missing": "meta"}],
        "slots": {"local": "filled", "tried": ["local"]},
        "target_types": ["火"],
        "roster": ["不该出现"],
    }
    web = {
        "guesses": [{"id": "guess-1", "authority": "web", "discardable": True, "text": "热门是水灵"}],
        "slots": {"web": "filled", "tried": ["web:热门"]},
        "web_sources": [{"url": "https://example.com/hot"}],
        "roster": ["另一套"],
    }
    merged = reduce_branches(base, local, web, True)
    assert merged["roster"] == ["水灵"]
    assert merged["facts"][0]["authority"] == "catalog"
    assert merged["guesses"][0]["discardable"] is True
    assert merged["gap"]["kind"] == "meta"
    assert merged["target_types"] == ["火"]


def test_restore_previous_drops_the_failed_step():
    ledger = {
        "facts": [{"id": "kept"}],
        "roster": [],
        "progress": {"next": "need_lineup"},
        "reviewer": "stay",
        "prior": [],
    }
    ledger["prior"].append({
        "facts": [{"id": "kept"}],
        "roster": [],
        "progress": {"next": "need_local"},
    })
    ledger["roster"] = ["坏的一套", "坏的一套", "坏的一套", "坏的一套", "坏的一套", "坏的一套"]
    assert restore_previous(ledger) is True
    assert ledger["roster"] == []
    assert ledger["facts"] == [{"id": "kept"}]
    assert ledger["progress"]["next"] == "need_local"
    assert ledger["progress"]["reverted"] is True
    assert ledger["reviewer"] == "stay"


def test_split_entries_keep_a_parent_and_overlapping_header():
    header = "## 技能\n\n总表"
    entries = "\n".join(f"- 招{index}：水系" for index in range(10))
    chunks = _split_entries("技能", header + "\n" + entries)
    parent = [item for item in chunks if item["chunk_type"] == "parent"]
    children = [item for item in chunks if item["chunk_type"] == "child"]
    assert len(parent) == 1
    assert children
    assert {item["parent_id"] for item in chunks} == {"section:技能"}
    assert all(item["text"].startswith("## 技能") for item in children)


if __name__ == "__main__":
    test_infeasible_web_stays_on_the_program_word()
    test_lineup_may_switch_to_both_slots()
    test_chain_keeps_the_program_word()
    test_check_is_not_asked()
    test_repeat_local_returns_to_the_program_word()
    test_second_ask_can_take_a_legal_word()
    test_release_brief_says_the_count_is_open()
    test_reduce_keeps_one_roster_and_separate_evidence()
    test_restore_previous_drops_the_failed_step()
    test_split_entries_keep_a_parent_and_overlapping_header()
    print("ok")
