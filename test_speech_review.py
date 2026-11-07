"""成文审查只看这句话。程序能判定的几条不依赖模型。"""
from agents.speech_review import parse_review, review_speech


def _quiet(_body):
    return '{"pass": true, "issues": [], "text": ""}'


def test_missing_core_is_caught_without_the_model():
    result = review_speech(
        "组建以雪灵为核心，针对冰钻布鲁斯",
        "灯灯记下了第 21 套出场。六只是加油蟹、卡瓦重、贝古斯、音速犬（本来的样子）、双灯鱼、古卷执政官。",
        {"names": ["加油蟹", "卡瓦重", "贝古斯", "音速犬（本来的样子）", "双灯鱼", "古卷执政官"]},
        ask=_quiet,
    )
    assert "core" in result["issues"]
    assert result["pass"] is False
    assert "雪灵" not in result["text"] or "没有" in result["text"] or result["text"].startswith("灯灯记下了")


def test_repeated_sentence_is_folded():
    result = review_speech(
        "水灵是什么系的",
        "灯灯记得水灵是水系。灯灯记得水灵是水系。",
        {"names": []},
        ask=_quiet,
    )
    assert result["text"].count("灯灯记得水灵是水系。") == 1
    assert result["repaired"] is True


def test_machine_words_are_rejected_and_a_dropped_name_is_not_adopted():
    from agents.dengdeng_persona import contains_banned

    parsed = parse_review('{"pass": false, "issues": ["voice", "extra"], "text": "灯灯重说一遍。"}')
    assert parsed["issues"] == ["voice", "extra"]
    assert parsed["pass"] is False
    result = review_speech(
        "以水灵为核心组一套",
        "灯灯记下了这一套。六只是水灵、贝古斯。",
        {"names": ["水灵", "贝古斯"]},
        ask=lambda _body: '{"pass": false, "issues": ["voice"], "text": "作为语言模型，六只是水灵。"}',
    )
    assert "作为语言模型" not in result["text"]
    assert "贝古斯" in result["text"]
    assert contains_banned("这里有接口") is True


def test_unfinished_sentence_is_fluency():
    result = review_speech(
        "水灵是什么系的",
        "灯灯记得水灵是水系",
        {"names": []},
        ask=_quiet,
    )
    assert "fluency" in result["issues"]
    assert result["pass"] is False


if __name__ == "__main__":
    test_missing_core_is_caught_without_the_model()
    test_repeated_sentence_is_folded()
    test_machine_words_are_rejected_and_a_dropped_name_is_not_adopted()
    test_unfinished_sentence_is_fluency()
    print("ok")
