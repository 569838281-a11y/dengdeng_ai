"""边想边说：模型写下的句子替换事先准备的进度句。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _empty_web(_query):
    return {"results": []}


def test_stream_writes_the_thought_and_skips_the_prepared_line():
    from agents.job_ledger import drop
    from agents.react_stream import bind_thinker, reset_thinker
    from agents.supervisor import run_cycle
    from agents.thoughts import bind, reset

    seen = []

    def thinker(_prompt, on_piece):
        on_piece("我想先核对水灵这一处")

    def lookup(*_args):
        return {"found": True, "answer": "水灵是水系。"}

    def review(_question, speech, evidence=None, ask=None):
        return {"pass": True, "text": speech, "issues": []}

    token = bind(lambda kind, text: seen.append((kind, text)))
    thinker_token = bind_thinker(thinker)
    try:
        run_cycle(
            "水灵是什么系的",
            session_id="react-stream",
            judged={"intent": "search", "request": "水灵是什么系的"},
            lookup=lookup,
            web=_empty_web,
            review=review,
        )
    finally:
        reset_thinker(thinker_token)
        reset(token)
        drop("react-stream")
    texts = [text for _kind, text in seen]
    assert any("我想先核对水灵这一处" in text for text in texts)
    assert any(kind == "delta" for kind, _text in seen)
    assert any(kind == "close" for kind, _text in seen)
    assert not any("灯灯去名录里查" in text for text in texts)
    assert not any(text.startswith("正在看") or text.startswith("正在查") for text in texts)
    assert not any("拆成查" in text for text in texts)


def test_banned_words_do_not_reach_the_player():
    from agents.react_stream import bind_thinker, reset_thinker, stream_prompt
    from agents.thoughts import bind, reset

    seen = []

    def thinker(_prompt, on_piece):
        on_piece("先看接口里的")
        on_piece("水灵")

    token = bind(lambda kind, text: seen.append((kind, text)))
    thinker_token = bind_thinker(thinker)
    try:
        assert stream_prompt("看这一处")
    finally:
        reset_thinker(thinker_token)
        reset(token)
    shown = "".join(text for kind, text in seen if kind == "delta")
    assert "接口" not in shown
    assert "水灵" in shown


def test_a_failed_thought_keeps_the_prepared_line():
    from agents.job_ledger import drop
    from agents.react_stream import bind_thinker, reset_thinker
    from agents.supervisor import run_cycle
    from agents.thoughts import bind, reset

    seen = []

    def thinker(_prompt, _on_piece):
        raise TimeoutError("慢")

    token = bind(lambda _kind, text: seen.append(text))
    thinker_token = bind_thinker(thinker)
    try:
        run_cycle(
            "水灵是什么系的",
            session_id="react-fallback",
            judged={"intent": "search", "request": "水灵是什么系的"},
            lookup=lambda *_args: {"found": True, "answer": "水灵是水系。"},
            web=_empty_web,
            review=lambda *_args, **_kwargs: {"pass": True, "text": "水灵是水系。", "issues": []},
        )
    finally:
        reset_thinker(thinker_token)
        reset(token)
        drop("react-fallback")
    joined = "\n".join(seen)
    assert "拆成查水灵" in joined or "灯灯去名录里查" in joined


def test_react_step_hides_the_action_word():
    from agents.react_stream import bind_thinker, react_turn, reset_thinker
    from agents.thoughts import bind, reset

    seen = []

    def thinker(_prompt, on_piece):
        on_piece("Thought: 我先核对水灵的属性\nAction: need_ask")

    token = bind(lambda kind, text: seen.append((kind, text)))
    thinker_token = bind_thinker(thinker)
    try:
        spoke, action = react_turn("水灵是什么系的", "", "need_local")
    finally:
        reset_thinker(thinker_token)
        reset(token)
    assert spoke
    assert action == "need_ask"
    shown = " ".join(text for kind, text in seen if kind == "delta")
    assert "水灵" in shown
    assert "need_ask" not in shown
    assert any(text == "Action: need_ask" for kind, text in seen if kind == "thought")


def test_an_empty_ask_does_not_replace_the_program_word():
    from agents.cycle_graph import choose_tool
    from agents.job_ledger import blank

    ledger = blank("react-ask", "水灵是什么系的")
    ledger["constraints"]["intent"] = "search"
    word = choose_tool(ledger, "need_local", lambda _ledger, _program: "need_ask")
    assert word == "need_local"
    assert ledger["progress"]["rejected_tool"] == "need_ask"


def test_ircot_keeps_only_a_grounded_column():
    from agents.react_stream import bind_thinker, ircot_fact, reset_thinker

    def finish(_prompt, on_piece):
        on_piece("完成")

    token = bind_thinker(finish)
    try:
        assert ircot_fact("水灵是什么系的", "属性：水") == ""
    finally:
        reset_thinker(token)

    def skill(prompt, on_piece):
        if "IRCoT" in prompt:
            on_piece("水灵的技能")
        else:
            on_piece("别的精灵的技能")

    token = bind_thinker(skill)
    try:
        assert ircot_fact("水灵是什么系的", "属性：水") == "水灵的技能"
        assert ircot_fact("这是什么系的", "属性：水") == ""
    finally:
        reset_thinker(token)


if __name__ == "__main__":
    test_stream_writes_the_thought_and_skips_the_prepared_line()
    test_banned_words_do_not_reach_the_player()
    test_a_failed_thought_keeps_the_prepared_line()
    print("ok")
