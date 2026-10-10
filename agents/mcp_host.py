"""FastAPI 进程里的 MCP Host。一个 Client 对应文档 Server。"""
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger("policy_qa.mcp")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    logger.addHandler(_handler)
logger.propagate = False

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "agents" / "mcp_docs_server.py"

_HOST = None
_HOST_LOCK = threading.Lock()


def _child_env() -> dict:
    env = {}
    for key in (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "PYTHONPATH",
    ):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env["PYTHONIOENCODING"] = "utf-8"
    env["MCP_WORKSPACE"] = str(ROOT)
    return env


class McpDocsHost:
    """一对一 Client。首次使用时拉起 stdio 子进程。"""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._thread_main, name="mcp-docs-host", daemon=True)
        self._ready = threading.Event()
        self._error = None
        self._tools = []
        self._session = None
        self._stop = None
        self._thread.start()
        if not self._ready.wait(40):
            raise TimeoutError("mcp initialize timed out")
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
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER)],
            cwd=str(ROOT),
            env=_child_env(),
        )
        async with stdio_client(params) as streams:
            read, write = streams
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                server_name = ""
                info = getattr(initialized, "serverInfo", None) or getattr(initialized, "server_info", None)
                if info is not None:
                    server_name = getattr(info, "name", "") or ""
                logger.info("mcp initialize %s", server_name or "ok")
                listed = await session.list_tools()
                self._tools = _pack_listed(listed)
                logger.info("mcp tools/list %s", [item["name"] for item in self._tools])
                self._session = session
                self._stop = asyncio.Event()
                self._ready.set()
                await self._stop.wait()

    def list_tools(self) -> list:
        return [dict(item) for item in self._tools]

    def refresh_tools(self) -> list:
        future = asyncio.run_coroutine_threadsafe(self._refresh(), self._loop)
        return future.result(timeout=30)

    async def _refresh(self) -> list:
        listed = await self._session.list_tools()
        self._tools = _pack_listed(listed)
        logger.info("mcp tools/list %s", [item["name"] for item in self._tools])
        return [dict(item) for item in self._tools]

    def call_tool(self, name: str, arguments: dict) -> str:
        future = asyncio.run_coroutine_threadsafe(self._call(name, arguments or {}), self._loop)
        return future.result(timeout=60)

    async def _call(self, name: str, arguments: dict) -> str:
        logger.info("mcp tools/call %s", name)
        result = await self._session.call_tool(name, arguments)
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            detail = _result_text(result) or "tool error"
            raise RuntimeError(detail)
        return _result_text(result)


def _pack_listed(listed) -> list:
    tools = []
    for tool in listed.tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump(by_alias=True, exclude_none=True)
        tools.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": schema,
        })
    return tools


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


def get_mcp_host() -> McpDocsHost:
    global _HOST
    with _HOST_LOCK:
        if _HOST is None:
            _HOST = McpDocsHost()
        return _HOST
