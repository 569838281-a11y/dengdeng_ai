"""公网检索。只取标题、链接和摘要文本，不执行结果里的脚本。"""
import html
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_TIMEOUT = 10
_TAG = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_HTML = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _plain(text: str, limit: int = 400) -> str:
    body = _TAG.sub(" ", text or "")
    body = _HTML.sub(" ", body)
    body = html.unescape(body)
    body = _SPACE.sub(" ", body).strip()
    return body[:limit]


def _http_url(url: str) -> str:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return cleaned
    return ""


def _item(title: str, url: str, snippet: str) -> dict:
    safe = _http_url(url)
    if not safe:
        return {}
    return {
        "title": _plain(title, 120) or safe,
        "url": safe,
        "snippet": _plain(snippet),
    }


def _read_json(url: str, headers: dict, payload: dict = None) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=_TIMEOUT) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw or "{}")


def _tavily(query: str, key: str, endpoint: str, limit: int) -> list:
    url = endpoint or "https://api.tavily.com/search"
    data = _read_json(url, {}, {
        "api_key": key,
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
        "include_answer": False,
    })
    rows = []
    for item in data.get("results") or []:
        built = _item(item.get("title") or "", item.get("url") or "", item.get("content") or item.get("snippet") or "")
        if built:
            rows.append(built)
    return rows[:limit]


def _bing(query: str, key: str, endpoint: str, limit: int) -> list:
    url = endpoint or "https://api.bing.microsoft.com/v7.0/search"
    data = _read_json(
        f"{url}?{urlencode({'q': query, 'count': limit})}",
        {"Ocp-Apim-Subscription-Key": key},
    )
    rows = []
    for item in ((data.get("webPages") or {}).get("value") or []):
        built = _item(item.get("name") or "", item.get("url") or "", item.get("snippet") or "")
        if built:
            rows.append(built)
    return rows[:limit]


def _brave(query: str, key: str, endpoint: str, limit: int) -> list:
    url = endpoint or "https://api.search.brave.com/res/v1/web/search"
    data = _read_json(
        f"{url}?{urlencode({'q': query, 'count': limit})}",
        {"X-Subscription-Token": key, "Accept": "application/json"},
    )
    rows = []
    for item in ((data.get("web") or {}).get("results") or []):
        built = _item(item.get("title") or "", item.get("url") or "", item.get("description") or "")
        if built:
            rows.append(built)
    return rows[:limit]


def search_web(query: str, limit: int = 5) -> dict:
    """返回 {reason, results, detail}。reason 为 ok / no_key / empty / error。"""
    import config

    text = (query or "").strip()
    if not text:
        return {"reason": "empty", "results": [], "detail": "没有查询词"}
    key = (config.WEB_SEARCH_API_KEY or "").strip()
    if not key:
        return {"reason": "no_key", "results": [], "detail": "未配置密钥"}
    engine = (config.WEB_SEARCH_ENGINE or "tavily").strip().lower()
    endpoint = (config.WEB_SEARCH_ENDPOINT or "").strip()
    capped = max(1, min(5, int(limit or 5)))
    try:
        if engine in {"bing"}:
            rows = _bing(text, key, endpoint, capped)
        elif engine in {"brave", "bravesearch"}:
            rows = _brave(text, key, endpoint, capped)
        else:
            rows = _tavily(text, key, endpoint, capped)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"reason": "error", "results": [], "detail": exc.__class__.__name__}
    if not rows:
        return {"reason": "empty", "results": [], "detail": "没有查到网页"}
    return {"reason": "ok", "results": rows, "detail": ""}
