# MCP 与提示词 Function Calling

Host 是 FastAPI 进程。每个 Server 配一个 Client，这里只有文档 Server。Server 用 stdio，工具是 `read_tabular`、`write_tabular`、`read_document`、`write_document`，能读写真的 CSV、DOCX、PDF。调试列表：`GET /api/v1/mcp/tools`。

```text
React
  → FastAPI（Host）
       Client ──stdio── MCP Server（CSV / DOCX / PDF）
       提示词 Function Calling
            1. tools/list 写进提示词
            2. 云端模型只输出 {"name","arguments"}
            3. 文档工具走 tools/call；run_trial_battle 走 battle.py
            4. 结果交给灯灯口吻
```

这不是厂商的 `functions[]` 参数，也不是在 `plan_query` 里看见「谁赢」就开战。模型若一直输出 JSON，最多三轮后改用模板口吻。LoRA 只负责成文。

演示名册在 `knowledge/party_demo/party.csv`。用户自己的表格放在 `data/party/`，不进仓库。
