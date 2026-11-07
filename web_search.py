"""公网检索。只取标题、链接和摘要文本，不执行结果里的脚本。"""
import html
import json
import re
import threading
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


def _read_json(url: str, headers: dict, payload: dict = None, timeout: int = _TIMEOUT) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw or "{}")


_EXCLUDE_DOMAINS = (
    "4399.com", "7k7k.com", "51wan.com", "youtube.com", "youtu.be",
    "wikipedia.org", "rebang.today", "tophub.today", "wandoujia.com",
)


def tavily_payload(query: str, key: str, limit: int, depth: str = "basic", include_domains=None, domains_mode: str = "") -> dict:
    """搜寻请求。日期窗口和总答案保持关闭，站点限制只在给出名单时附上。"""
    body = {
        "api_key": key,
        "query": query,
        "search_depth": depth or "basic",
        "chunks_per_source": 3,
        "max_results": limit,
        "topic": "general",
        "include_published_date": True,
        "filter_by_published_date": False,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_image_descriptions": False,
        "include_favicon": False,
        "exclude_domains": list(_EXCLUDE_DOMAINS),
        "country": "china",
        "language": "zh-cn",
        "filter_by_language": False,
        "auto_parameters": False,
        "exact_match": False,
        "include_usage": False,
        "safe_search": False,
    }
    domains = [item for item in (include_domains or []) if item]
    if domains:
        body["include_domains"] = domains
        body["include_domains_mode"] = domains_mode or "restrict"
    return body


def wave_plan(query: str) -> list:
    """先官网，再维基，再 B 站，最后才是全网。"""
    text = (query or "").strip()
    return [
        {"name": "官网", "query": text, "depth": "advanced", "include_domains": ["rocom.qq.com"], "domains_mode": "restrict"},
        {"name": "维基", "query": f"{text} site:wiki.biligame.com/nrc", "depth": "advanced", "include_domains": ["wiki.biligame.com"], "domains_mode": "restrict"},
        {"name": "视频", "query": text, "depth": "basic", "include_domains": ["bilibili.com"], "domains_mode": "restrict"},
        {"name": "全网", "query": text, "depth": "basic", "include_domains": [], "domains_mode": ""},
    ]


def _tavily(query: str, key: str, endpoint: str, limit: int, depth: str = "basic", include_domains=None, domains_mode: str = "") -> list:
    url = endpoint or "https://api.tavily.com/search"
    data = _read_json(
        url,
        {},
        tavily_payload(query, key, limit, depth, include_domains, domains_mode),
        timeout=30,
    )
    rows = []
    for item in data.get("results") or []:
        built = _item(item.get("title") or "", item.get("url") or "", item.get("content") or item.get("snippet") or "")
        if not built:
            continue
        if item.get("score") is not None:
            try:
                built["score"] = float(item.get("score"))
            except (TypeError, ValueError):
                built["score"] = 0.0
        published = str(item.get("published_date") or "").strip()
        if published:
            built["published_date"] = published
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


_SITE_TOKEN = re.compile(r"(?i)\bsite:[^\s]+")


def deepseek_query(query: str, include_domains=None) -> str:
    """拼 DeepSeek 的查询。站点限制用 site:；排除站在结果侧过滤，以免超过 128 字。"""
    text = _SITE_TOKEN.sub(" ", query or "")
    text = _SPACE.sub(" ", text).strip()
    parts = [text] if text else []
    domains = [item for item in (include_domains or []) if item]
    if domains:
        parts.append(" OR ".join(f"site:{host}" for host in domains))
    if "lang:" not in (query or "").lower():
        parts.append("lang:zh")
    built = " ".join(parts).strip()
    return built[:128]


def _excluded_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return True
    return any(host == item or host.endswith("." + item) for item in _EXCLUDE_DOMAINS)


def _deepseek(query: str, key: str, endpoint: str, limit: int, include_domains=None, ori_question: str = "") -> list:
    """DeepSeek Search API。长摘要优先放进 snippet，便于后面句子核对。"""
    base = (endpoint or "https://api.deepseek.com/v1/tools").rstrip("/")
    url = base if base.endswith("/search") else f"{base}/search"
    question = _SPACE.sub(" ", (ori_question or "").strip())[:128]
    body = {
        "query": deepseek_query(query, include_domains),
        "count": max(1, min(50, int(limit or 10))),
        "need_content": False,
    }
    if question:
        body["ori_question"] = question
    data = _read_json(
        url,
        {"Authorization": f"Bearer {key}"},
        body,
        timeout=30,
    )
    rows = []
    for item in data.get("results") or []:
        page_url = item.get("url") or ""
        if _excluded_url(page_url):
            continue
        excerpt = item.get("summary") or item.get("snippet") or item.get("content") or ""
        built = _item(item.get("title") or "", page_url, _plain(excerpt, 800))
        if not built:
            continue
        if item.get("rerank_score") is not None:
            try:
                built["score"] = float(item.get("rerank_score"))
            except (TypeError, ValueError):
                built["score"] = 0.0
        if item.get("authority") is not None:
            try:
                built["authority"] = int(item.get("authority"))
            except (TypeError, ValueError):
                pass
        published = str(item.get("date") or "").strip()
        if published:
            built["published_date"] = published
        rows.append(built)
    return rows[:limit]


def _deepseek_fetch(url: str, key: str, endpoint: str, limit: int = 1600) -> str:
    """DeepSeek Fetch：一页 Markdown 正文。"""
    safe = _http_url(url)
    if not safe:
        return ""
    base = (endpoint or "https://api.deepseek.com/v1/tools").rstrip("/")
    fetch_url = base if base.endswith("/fetch") else f"{base}/fetch"
    data = _read_json(
        fetch_url,
        {"Authorization": f"Bearer {key}"},
        {"url": safe},
        timeout=12,
    )
    return _plain(data.get("content") or "", limit)


def extract_pages(urls: list) -> dict:
    """用已配置的搜寻密钥读取页面正文。失败时返回空表。"""
    import config

    engine = (config.WEB_SEARCH_ENGINE or "tavily").strip().lower()
    wanted = []
    for url in urls or []:
        safe = _http_url(url)
        if safe and safe not in wanted:
            wanted.append(safe)
    if not wanted:
        return {}
    if engine in {"deepseek"}:
        key = (config.DEEPSEEK_API_KEY or "").strip()
        if not key:
            return {}
        endpoint = (config.WEB_SEARCH_ENDPOINT or "").strip()
        found = {}
        for page in wanted[:2]:
            try:
                text = _deepseek_fetch(page, key, endpoint, 4000)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
                continue
            if text:
                found[page] = text
        return found
    key = (config.WEB_SEARCH_API_KEY or "").strip()
    if not key:
        return {}
    try:
        data = _read_json("https://api.tavily.com/extract", {}, {
            "api_key": key,
            "urls": wanted[:2],
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


_PAGE_SLOTS = threading.BoundedSemaphore(2)


def fetch_html(url: str, limit: int = 1200000) -> str:
    """打开一页，留下原始正文，供图鉴栏目解析。打不开就返回空字符串。同时最多打开两页。"""
    safe = _http_url(url)
    if not safe:
        return ""
    request = Request(safe, headers={"User-Agent": "Mozilla/5.0"})
    with _PAGE_SLOTS:
        try:
            with urlopen(request, timeout=12) as response:
                return response.read(limit).decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError):
            return ""


def read_page(url: str, limit: int = 1600) -> str:
    """打开一页，只留下纯文本。打不开就返回空字符串。同时最多打开两页。

    搜寻引擎是 DeepSeek 时，正文仍优先本地拉取；Fetch 只作为打不开时的补读。
    """
    safe = _http_url(url)
    if not safe or any(host in safe for host in ("youtube.com", "youtu.be")):
        return ""
    request = Request(safe, headers={"User-Agent": "Mozilla/5.0"})
    with _PAGE_SLOTS:
        try:
            with urlopen(request, timeout=8) as response:
                raw = response.read(80000).decode("utf-8", errors="replace")
            text = _plain(raw, limit)
            if text:
                return text
        except (HTTPError, URLError, TimeoutError, OSError):
            text = ""
    import config

    if (config.WEB_SEARCH_ENGINE or "").strip().lower() not in {"deepseek"}:
        return text
    key = (config.DEEPSEEK_API_KEY or "").strip()
    if not key:
        return text
    with _PAGE_SLOTS:
        try:
            return _deepseek_fetch(safe, key, (config.WEB_SEARCH_ENDPOINT or "").strip(), limit) or text
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
            return text


def search_web(query: str, limit: int = 5, depth: str = "", include_domains=None, domains_mode: str = "", ori_question: str = "") -> dict:
    """返回 {reason, results, detail}。reason 为 ok / no_key / empty / error。"""
    import config

    text = (query or "").strip()
    if not text:
        return {"reason": "empty", "results": [], "detail": "没有查询词"}
    engine = (config.WEB_SEARCH_ENGINE or "tavily").strip().lower()
    if engine in {"deepseek"}:
        key = (config.DEEPSEEK_API_KEY or "").strip()
    else:
        key = (config.WEB_SEARCH_API_KEY or "").strip()
    if not key:
        return {"reason": "no_key", "results": [], "detail": "未配置密钥"}
    endpoint = (config.WEB_SEARCH_ENDPOINT or "").strip()
    capped = max(1, min(10, int(limit or 5)))
    try:
        if engine in {"deepseek"}:
            rows = _deepseek(text, key, endpoint, capped, include_domains, ori_question or text)
        elif engine in {"bing"}:
            rows = _bing(text, key, endpoint, capped)
        elif engine in {"brave", "bravesearch"}:
            rows = _brave(text, key, endpoint, capped)
        else:
            rows = _tavily(text, key, endpoint, capped, depth or "basic", include_domains, domains_mode)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"reason": "error", "results": [], "detail": exc.__class__.__name__}
    if not rows:
        return {"reason": "empty", "results": [], "detail": "没有查到网页"}
    return {"reason": "ok", "results": rows, "detail": ""}
