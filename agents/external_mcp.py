"""按需拉起外部 MCP。文档服务仍走原来的主机，这里只接计算页和视频。"""
import asyncio
import logging
import os
import shutil
import sys
import threading
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger("policy_qa.mcp.external")

_LOCK = threading.Lock()
_HOSTS = {}
_FAILED = set()


def tools_live() -> bool:
    """测试进程不拉起浏览器和转写。正式进程默认拉起，DENG_EXTERNAL_MCP=0 可关掉。"""
    flag = (os.environ.get("DENG_EXTERNAL_MCP") or "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    name = Path(sys.argv[0]).name
    if name.startswith("test_") or name.startswith("pytest"):
        return False
    return True


def _exe(names: tuple) -> str:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def server_spec(name: str):
    """返回 (command, args)。机器上没有启动命令时返回空。"""
    npx = _exe(("npx.cmd", "npx"))
    uvx = _exe(("uvx.exe", "uvx"))
    if name == "playwright":
        if not npx:
            return "", []
        return npx, ["-y", "@playwright/mcp@latest", "--headless"]
    if name == "bilibili_subtitle":
        exe = _exe(("bilibili-subtitle-fetch.exe", "bilibili-subtitle-fetch"))
        if exe:
            return exe, ["serve", "--no-asr"]
        if uvx:
            return uvx, ["--python", "3.12", "bilibili-subtitle-fetch", "serve", "--no-asr"]
        return "", []
    if name == "video_transcript":
        exe = _exe(("video-transcript-mcp.exe", "video-transcript-mcp"))
        if exe:
            return exe, []
        if uvx:
            return uvx, ["video-transcript-mcp"]
        return "", []
    if name == "bilibili":
        if not npx:
            return "", []
        return npx, ["-y", "@xzxzzx/bilibili-mcp@latest"]
    return "", []


class ExternalHost:
    """一个外部服务一条 stdio。启动失败就记住，避免每次再等。"""

    def __init__(self, name: str, command: str, args: list):
        self.name = name
        self._command = command
        self._args = list(args)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._thread_main, name=f"mcp-{name}", daemon=True)
        self._ready = threading.Event()
        self._error = None
        self._session = None
        self._stop = None
        self._thread.start()
        if not self._ready.wait(40):
            self._error = TimeoutError(name)
        if self._error:
            raise self._error

    def _thread_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            self._error = exc
            self._ready.set()

    async def _serve(self) -> None:
        params = StdioServerParameters(command=self._command, args=self._args, env=_child_env())
        async with stdio_client(params) as streams:
            read, write = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                logger.info("external mcp ready %s", self.name)
                self._session = session
                self._stop = asyncio.Event()
                self._ready.set()
                await self._stop.wait()

    def call(self, tool: str, arguments: dict, timeout: int = 40) -> str:
        if self._error or self._session is None:
            raise RuntimeError(self.name)
        future = asyncio.run_coroutine_threadsafe(self._call(tool, arguments or {}), self._loop)
        return future.result(timeout=timeout)

    async def _call(self, tool: str, arguments: dict) -> str:
        logger.info("external mcp %s %s", self.name, tool)
        result = await self._session.call_tool(tool, arguments)
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            raise RuntimeError(_result_text(result) or tool)
        return _result_text(result)


def get_host(name: str):
    if name in _FAILED:
        return None
    with _LOCK:
        if name in _FAILED:
            return None
        host = _HOSTS.get(name)
        if host is not None:
            return host
        command, args = server_spec(name)
        if not command:
            _FAILED.add(name)
            logger.info("external mcp missing %s", name)
            return None
        try:
            host = ExternalHost(name, command, args)
        except Exception as exc:
            _FAILED.add(name)
            logger.warning("external mcp %s 未启动：%s", name, type(exc).__name__)
            return None
        _HOSTS[name] = host
        return host


def call_tool(name: str, tool: str, arguments: dict, timeout: int = 40) -> str:
    host = get_host(name)
    if host is None:
        return ""
    try:
        return host.call(tool, arguments, timeout=timeout) or ""
    except Exception as exc:
        logger.warning("external mcp %s %s 未完成：%s", name, tool, type(exc).__name__)
        return ""


def _child_env() -> dict:
    env = {}
    for key in (
        "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
        "TEMP", "TMP", "COMSPEC", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA",
    ):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _result_text(result) -> str:
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if not parts and structured is not None:
        parts.append(str(structured))
    return "\n".join(parts).strip()
