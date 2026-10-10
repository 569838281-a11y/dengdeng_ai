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


_SKIP_HOSTS = ("4399.com", "7k7k.com", "51wan.com", "bilibili.com", "youtube.com", "youtu.be")


def _tavily(query: str, key: str, endpoint: str, limit: int) -> list:
    url = endpoint or "https://api.tavily.com/search"
    data = _read_json(url, {}, {
        "api_key": key,
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
        "include_answer": False,
        "exclude_domains": list(_SKIP_HOSTS),
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


def extract_pages(urls: list) -> dict:
    """用已配置的搜寻密钥读取页面正文。失败时返回空表。"""
    import config

    key = (config.WEB_SEARCH_API_KEY or "").strip()
    wanted = []
    for url in urls or []:
        safe = _http_url(url)
        if safe and safe not in wanted:
            wanted.append(safe)
    if not key or not wanted:
        return {}
    try:
        data = _read_json("https://api.tavily.com/extract", {}, {
            "api_key": key,
            "urls": wanted[:3],
            "extract_depth": "basic",
            "include_images": False,
        })
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}
    found = {}
    for item in data.get("results") or []:
        url = _http_url(item.get("url") or "")
        text = _plain(item.get("raw_content") or "", 4000)
        if url and text:
            found[url] = text
    return found


def fetch_html(url: str, limit: int = 1200000) -> str:
    """打开一页，留下原始正文，供图鉴栏目解析。打不开就返回空字符串。"""
    safe = _http_url(url)
    if not safe:
        return ""
    request = Request(safe, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=12) as response:
            return response.read(limit).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError):
        return ""


def read_page(url: str, limit: int = 1600) -> str:
    """打开一页，只留下纯文本。打不开就返回空字符串。"""
    safe = _http_url(url)
    if not safe or any(host in safe for host in ("youtube.com", "youtu.be")):
        return ""
    request = Request(safe, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(80000).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError):
        return ""
    return _plain(raw, limit)


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
