"""成文员只换说法，追问收束不改只数，也不改放生原句。"""
from agents.follow_agent import rewrite_followup
from agents.voice_agent import speak


def test_voice_keeps_wording_that_passes():
    result = speak(
        "超导合起来是180",
        lambda text: "180" in text and "超导" in text,
        lambda: "程序原文",
        "检索",
        teacher=lambda _text: "灯灯算过，超导合起来是180。",
    )
    assert result["via"] == "teacher"
    assert "180" in result["text"]


def test_voice_returns_the_program_line_when_wording_drops_the_number():
    result = speak(
        "超导合起来是180",
        lambda text: "180" in text,
        lambda: "超导合起来是180",
        "检索",
        teacher=lambda _text: "灯灯觉得超导更厉害。",
    )
    assert result == {"text": "超导合起来是180", "via": "fallback"}


def test_release_stays_the_original_sentence():
    def explode(_prompt):
        raise AssertionError("放生不该改写")

    result = rewrite_followup(
        "放生海枝枝",
        [{"role": "user", "content": "仓库里有海枝枝"}],
        invoke=explode,
    )
    assert result == {"query": "放生海枝枝", "kept": True}


def test_rewritten_count_is_dropped():
    result = rewrite_followup(
        "水灵怎么样",
        [{"role": "user", "content": "看看水灵"}],
        invoke=lambda _prompt: "放生一只水灵",
    )
    assert result == {"query": "水灵怎么样", "kept": True}


if __name__ == "__main__":
    test_voice_keeps_wording_that_passes()
    test_voice_returns_the_program_line_when_wording_drops_the_number()
    test_release_stays_the_original_sentence()
    test_rewritten_count_is_dropped()
    print("ok")
