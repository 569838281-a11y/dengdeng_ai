"""计算页和视频字幕的接入。测试不拉起真实浏览器。"""
from agents.external_mcp import tools_live
from agents.page_calc import excerpt, operate_damage_page
from agents.video_speech import speech_of
from agents.web_read import read_web


def _rank(_fact, texts):
    return [1.0 for _item in texts]


def test_tools_stay_off_while_testing():
    assert tools_live() is False


def test_video_speech_uses_the_injected_reader():
    seen = []

    def runner(url):
        seen.append(url)
        return "出场率最高的精灵是水灵"

    assert speech_of("https://www.bilibili.com/video/BV1test", runner=runner) == "出场率最高的精灵是水灵"
    assert seen == ["https://www.bilibili.com/video/BV1test"]
    assert speech_of("https://rocom.qq.com/a", runner=runner) == ""


def test_bilibili_page_keeps_the_spoken_line():
    seen = []

    def video(url):
        seen.append(url)
        return "出场率最高的精灵是水灵，视频里这样讲。"

    def search(_query, limit=10):
        return {"results": [{
            "title": "出场率",
            "url": "https://www.bilibili.com/video/BV1test",
            "snippet": "播放量 5000",
            "plays": 5000,
        }]}

    outcome = read_web("出场率最高的精灵", search=search, rank=_rank, video_text=video)
    assert seen == ["https://www.bilibili.com/video/BV1test"]
    assert "视频里这样讲" in outcome["text"]


def test_low_plays_do_not_open_the_video():
    def video(_url):
        raise AssertionError("播放量不够不应听视频")

    def search(_query, limit=10):
        return {"results": [{
            "title": "出场率",
            "url": "https://www.bilibili.com/video/BV1low",
            "snippet": "播放量 200 出场率最高的精灵是水灵",
            "plays": 200,
        }]}

    outcome = read_web("出场率最高的精灵", search=search, rank=_rank, video_text=video)
    assert "水灵" not in (outcome.get("text") or "")


def test_calculator_types_the_names_and_keeps_damage_lines():
    class Host:
        def __init__(self):
            self.calls = []

        def call(self, tool, arguments, timeout=20):
            self.calls.append(tool)
            if tool == "browser_snapshot" and len(self.calls) == 2:
                return 'searchbox "防御方" [ref=e3]\ntextbox "攻击方" [ref=e4]'
            if tool == "browser_snapshot":
                return "伤害 180\n威力 90"
            return "ok"

    host = Host()
    text = operate_damage_page("霹雳迪迪", "水灵", "", host=host)
    assert host.calls[0] == "browser_navigate"
    assert "browser_type" in host.calls
    assert excerpt(text) == "伤害计算页读到：伤害 180 威力 90"


if __name__ == "__main__":
    test_tools_stay_off_while_testing()
    test_video_speech_uses_the_injected_reader()
    test_bilibili_page_keeps_the_spoken_line()
    test_low_plays_do_not_open_the_video()
    test_calculator_types_the_names_and_keeps_damage_lines()
    print("ok")
