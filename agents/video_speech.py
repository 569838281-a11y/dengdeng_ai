"""B 站视频先取字幕，没有字幕再转写。评论区不读。"""
import json
import logging

from agents.external_mcp import call_tool, tools_live

logger = logging.getLogger("policy_qa.video")

_EMPTY = ("Info:", "Error", "No subtitles", "ASR_NOT_READY", "没有字幕")


def speech_of(url: str, runner=None) -> str:
    """返回视频里说出的文字。不是 B 站地址时为空。"""
    link = (url or "").strip()
    if "bilibili.com" not in link and "b23.tv" not in link:
        return ""
    if runner is not None:
        return _usable(runner(link))
    if not tools_live():
        return ""
    from agents.thoughts import note_read

    text = _usable(_from_subtitle(link))
    if not text:
        text = _usable(_from_bilibili_mcp(link, asr=False))
    if not text:
        text = _usable(_from_transcript(link))
    if not text:
        text = _usable(_from_bilibili_mcp(link, asr=True))
    if text:
        note_read("正在听这条视频里的讲解")
    return text[:4000]


def _from_subtitle(url: str) -> str:
    return call_tool(
        "bilibili_subtitle",
        "get_bilibili_subtitle",
        {"url": url, "output_format": "text"},
        timeout=40,
    )


def _from_transcript(url: str) -> str:
    return call_tool(
        "video_transcript",
        "transcribe_url",
        {"url": url, "language": "zh", "async_mode": False},
        timeout=50,
    )


def _from_bilibili_mcp(url: str, asr: bool) -> str:
    arguments = {"url": url}
    if asr:
        arguments["fallback_to_asr"] = True
    return call_tool("bilibili", "get_video_transcript", arguments, timeout=50 if asr else 30)


def _usable(raw: str) -> str:
    text = (raw or "").strip()
    if not text or any(text.startswith(prefix) for prefix in _EMPTY):
        return ""
    if text[:1] in "[{":
        dug = _dig(text)
        if dug:
            return dug
    return text


def _dig(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    found = []
    _walk(data, found)
    return "\n".join(found).strip()


def _walk(node, found: list) -> None:
    if isinstance(node, dict):
        for key in ("content", "text", "transcript", "subtitle", "body"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                found.append(value.strip())
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, found)
