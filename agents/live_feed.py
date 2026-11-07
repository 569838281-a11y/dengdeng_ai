"""把任务上的新句子立刻交给正在听的页面。没人听时直接丢掉。"""
import queue
import threading

_LOCK = threading.Lock()
_FEEDS = {}


def publish(job_id: str, payload: dict) -> None:
    job = (job_id or "").strip()
    if not job or not isinstance(payload, dict):
        return
    with _LOCK:
        listeners = list(_FEEDS.get(job) or [])
    for feed in listeners:
        feed.put(dict(payload))


def subscribe(job_id: str) -> queue.Queue:
    feed = queue.Queue()
    job = (job_id or "").strip()
    with _LOCK:
        _FEEDS.setdefault(job, []).append(feed)
    return feed


def unsubscribe(job_id: str, feed: queue.Queue) -> None:
    job = (job_id or "").strip()
    with _LOCK:
        rows = [item for item in (_FEEDS.get(job) or []) if item is not feed]
        if rows:
            _FEEDS[job] = rows
        else:
            _FEEDS.pop(job, None)
