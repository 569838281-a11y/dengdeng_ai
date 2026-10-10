# 灯灯 · 洛克王国对战辅助

灯灯是一只双灯鱼。她把已经核对过的图鉴、规则和出场说成口语。六人名单、技能、血脉、道具和伤害由程序裁定，不交给模型编造。

非官方粉丝向研究原型，未获权利人授权，不得商用。游戏名称与美术的版权归原权利人。密钥放在本机 `.env`，不要提交。

## 能做什么

页面是 React 19，入口 `http://127.0.0.1:5173`。三种模式：

- **智能配队。** 只查本地名录、仓库、出场规则和这段对话里已经记下的卡片。仓库里凑得齐六只不同的精灵，并且出场规则已取到，才写下一套出场。点名的主力或核心必须在场上；「针对某只」的那只是对手，不会被编进队伍。名录里没有、但这句话里已经有一张够用的精灵卡时，可以让她做主力，头像用灯灯自己的样子顶上。标签和能否首领化只认用户补充，不从网页推断。
- **检索信息。** 规则先判断要查的栏目：技能、技能池、种族值、伤害原因。名录里有的精灵，种族值、技能效果和克制以本地为准。名录里没有的名字，先读洛克王国世界图鉴，读不到再按开关到外面查找，并收成同一张精灵卡。外面的结果不写回 `knowledge/pokemon/`。
- **模拟对战。** `battle.py` 在进程里结算。开战和出招先返回战报，解说用本地模板。检索里问两只谁赢时，会在气泡里走同一套试场。

同一段对话会记住有用的补充和配队习惯，例如某只精灵的首领化、尽量使用的道具，以及「以某只为主力」带来的使用偏好。噪声和「我最喜欢的精灵是某某」这种没有配队动作的句子不记。新开一段对话是空的。灯灯还在想时，补一句条件会并进当前问题；另起一件事则分开回答。

仓库增减、查看出场、删除或修改某一套，仍走固定吩咐。模型可以提出函数名，原句对得上规矩时以规矩为准。

## 架构

```text
浏览器 :5173
  → Vite 代理 /api
  → FastAPI :8000
       ├─ 配队   检索环（仓库、规则、条件）→ 程序选人与补全 → 灯灯口吻
       ├─ 检索   规则定栏目 → 本地 JSON / 图鉴或联网 → 精灵卡
       ├─ 对战   battle.py 结算 → 模板解说
       └─ 吩咐   提示词函数调用 → 原句纠正 → 仓库与出场表
  文档读写经 MCP（CSV、DOCX、PDF）。配队选人不走这条通道。
```

正式入口不是 Gradio。`app.py` 仍可单独打开旧页面。政策 PDF 的混合检索留在 `POST /api/v1/query`，不是网页上的检索主路径。`TEAM_USE_VECTOR` 默认关闭，配队不读那套向量库。

云端模型（智谱或 DeepSeek）负责口吻、听不清时的短意图，以及检索里最多三轮的函数选择。余额不足时，规矩仍能分流和配队。本地 LoRA 只学习「给定事实之后怎么说」，适配器不随仓库分发，默认关闭。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI、Uvicorn |
| 前端 | React 19、Vite |
| 知识 | `knowledge/pokemon/` 的 JSON，`knowledge/rules.md` |
| 图鉴与联网 | 洛克王国世界图鉴优先，其余用 Tavily 抽取正文 |
| 文档工具 | MCP stdio，一个文档服务 |
| 吩咐 | 提示词函数调用，不是厂商的 `functions[]` |
| 可选旧链 | LangChain、Chroma、bge-m3、BM25 |
| 可选口吻 | Qwen2.5-1.5B-Instruct 上的 LoRA |

## 仓库结构

```text
.
├── api.py                 # HTTP 入口
├── pokemon_kb.py          # 图鉴、选人、补全、核对
├── knowledge_search.py    # 检索、图鉴卡、名录外主力
├── battle.py              # 对战结算
├── web_search.py          # 联网与网页正文
├── photos.py              # 本地立绘；名录外的名字用灯灯的图
├── agents/                # 配队环、吩咐、记事、MCP、口吻
├── web/                   # React 页面
├── knowledge/             # 精灵 JSON 与规则
├── docs/新手复现指南.md
├── requirements.txt
├── .env.example
└── run_web.bat
```

公开仓库不含 `.env`、`photo/` 里的图片、`web/public/ui/*.png`、`chroma_db/`、`bge-m3/`、`data/lora/`、会话记事和追踪。没有立绘时，头像位置显示爪印。

## 快速开始

```bat
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
cd web
npm install
```

在 `.env` 里填写自己的 `ZHIPU_API_KEY`。然后双击 `run_web.bat`，或开两个终端：

```bat
set PYTHONIOENCODING=utf-8
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
.\.venv\Scripts\python.exe -u api.py
```

```bat
cd web
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。接口说明在 `http://127.0.0.1:8000/docs`。没有政策 PDF 也可以配队、检索和对战。本机没有 Redis 时，会话落到磁盘。没有本地 bge-m3 时，向量步骤跳过，结构化查找仍可用。

更细的步骤见 `docs/新手复现指南.md`。`docs/当前实现盘点.md` 若与本页不一致，以代码和本页为准。

## 配置

改 `.env` 后重启接口。下表不包含真实密钥。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `ZHIPU_API_KEY` | 空 | 智谱密钥。为空时进程拒绝启动 |
| `LLM_PROVIDER` | `zhipu` | `zhipu` 或 `deepseek` |
| `OPENAI_MODEL` | `glm-4-flash` | 智谱模型名 |
| `DEEPSEEK_API_KEY` | 空 | 仅 DeepSeek 需要 |
| `TEAM_LLM_TIMEOUT` | 45 | 短调用超时（秒） |
| `VOICE_LLM_TIMEOUT` | 120 | 灯灯成文超时（秒） |
| `TEAM_USE_VECTOR` | `false` | 为 true 时配队才尝试向量库 |
| `USE_LORA_REPLIER` | `false` | 为 true 且适配器存在时，配队与检索先走 LoRA |
| `WEB_SEARCH_API_KEY` | 空 | 检索模式的联网。引擎默认 Tavily |
| `WEB_SEARCH_ENGINE` | `tavily` | `tavily`、`bing` 或 `bravesearch` |
| `REDIS_URL` | `redis://localhost:16379/0` | 不可用时自动改用磁盘 |
| `SESSION_TTL` | 3600 | 会话保留秒数 |

`CHUNK_SIZE` 与 `CHUNK_OVERLAP` 在 `config.py` 里固定为 500 和 50。

## 接口

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/v1/auth/register`、`/login`、`/change-password` | 注册、登录、改密。密码至少 6 位，无盐 SHA-256，只适合本机演示 |
| `POST /api/v1/session` | 新开会话。记事跟这次会话走 |
| `POST /api/v1/agents/jobs`，`GET .../jobs/{id}` | 配队任务与轮询 |
| `POST /api/v1/knowledge/jobs`，`GET .../jobs/{id}` | 检索任务。联网开关只在检索模式传入 |
| `POST /api/v1/followup` | 思考过程中补一句条件，或另起一件事 |
| `POST /api/v1/battle/start`，`POST /api/v1/battle/{id}/move` | 开战与出招 |
| `GET /api/v1/pokemon`，`GET /api/v1/photo/{name}` | 名录与立绘 |
| `GET /api/v1/mcp/tools` | 当前文档工具名单 |
| `POST /api/v1/query` | 政策文档旧链 |

## 可选训练

采集调用云端教师，不需要显卡。训练建议至少 8GB 显存。下载基座时不要设置 `HF_HUB_OFFLINE`。

```bat
.\.venv\Scripts\python.exe -m agents.lora_collect
.\.venv\Scripts\python.exe train_lora.py
.\.venv\Scripts\python.exe eval_lora.py
```

确认存在 `data/lora/adapter/adapter_config.json` 后，把 `USE_LORA_REPLIER` 设为 `true` 并重启。未实际跑出的准确率不要写进说明。`train_dpo.py` 与 `train_ppo.py` 只导出偏好或打分，不更新云端权重。

## 局限

- 口吻模型不保证事实。对不上核对的那次生成会被丢掉。
- 图鉴只覆盖 `knowledge/pokemon/` 里已有的精灵，不是完整游戏。
- 对战只结算 `battle.py` 里写明的规则。
- 名录已有的种族值、技能效果和克制表不用网页覆盖。
- 配队不联网。检索联网默认避开其他怪物游戏和洛克王国页游页面。
- 密码哈希无盐，仅适合本地演示。

## 许可

代码以 [MIT License](LICENSE) 授权。该许可不覆盖游戏名称、立绘、界面切图、技能原文或其他权利人的素材。

```bibtex
@misc{dengdeng2026,
  title        = {灯灯：面向洛克王国对战辅助的结构化检索与口吻蒸馏原型},
  author       = {Dengdeng AI contributors},
  year         = {2026},
  howpublished = {\url{https://github.com/569838281-a11y/dengdeng_ai}},
  note         = {非官方研究原型。游戏名称与素材版权归原权利人。}
}
```
