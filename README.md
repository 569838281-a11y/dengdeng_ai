# 灯灯 · 洛克王国对战辅助系统

结构化知识优先，混合检索与 LoRA 成文为辅。灯灯（双灯鱼）只把已经核对过的事实说成口语。

粉丝向研究与演示原型。未获官方授权，不得用于商业用途。游戏名称、立绘与界面素材的版权归原权利人。请使用环境变量配置密钥，本仓库不含密钥。

<!-- badges: Python | React | FastAPI | MIT | Demo -->
<!-- ![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB) -->
<!-- ![React](https://img.shields.io/badge/React-19-149ECA) -->
<!-- ![FastAPI](https://img.shields.io/badge/FastAPI-0.1-009688) -->
<!-- ![License](https://img.shields.io/badge/License-MIT-blue) -->
<!-- ![Demo](https://img.shields.io/badge/Demo-local-lightgrey) -->

![产品封面](docs/assets/cover.png)
<!-- 占位：1920x800，内容要求见文末「图片清单」第 1 行 -->

## 摘要

洛克王国的对战资料分散在图鉴、规则和技能表里。直接询问通用大模型，容易编造种族值、特性与技能效果。本仓库给出一个可复现的研究原型：以 JSON 知识库和规则检索为主路径，由程序完成六人配队与对战结算；角色灯灯只负责口吻。政策文档上的混合检索是可选旧链，不是网页主路径。Qwen2.5-1.5B 的 LoRA 只蒸馏「给定上下文之后怎么说」，不学习图鉴，适配器不随仓库分发。事实校验失败时，系统回退到云端教师模型或程序模板。接口启动时不预加载嵌入模型。页面提供配队、检索与模拟对战。本系统不替代官方客户端。

## 功能

- **智能配队。** `propose_team_line` 按标签与点名选出 6 只精灵，`complete_team_answer` 补满每只 4 个技能、血脉和唯一道具。大模型不负责挑人。灯灯事后改口吻，前端用程序名单画卡片。
- **检索信息。** 规则先判定意图，再查 JSON 与 `rules.md`。只有规则无法判定时，才让模型输出意图 JSON。灯灯成文后做事实校验。
- **模拟对战。** `battle.py` 按规则结算伤害、道具与异常。开战和出招先返回战报，解说使用本地模板，不在请求里等待大模型。
- **可选政策 RAG。** PDF 经分块、向量与 BM25 后，由 `POST /api/v1/query` 或 Gradio 回答。这不是 `http://127.0.0.1:5173` 的主路径。
- **可选联网搜寻。** 仅检索模式、且用户打开开关时生效。没有搜索密钥时明确说明本次没有联网，不假装已经搜索。

## 演示

截图尚未放入仓库。下列路径是占位，拍摄要求见文末清单。图中不要出现密钥、手机号或真实账号，演示名使用「小洛克」。

![智能配队](docs/assets/demo-team.png)
<!-- 占位：1440x900，内容要求见文末「图片清单」第 3 行 -->

![检索信息](docs/assets/demo-search.png)
<!-- 占位：1440x900，内容要求见文末「图片清单」第 4 行 -->

![模拟对战](docs/assets/demo-battle.png)
<!-- 占位：1440x900，内容要求见文末「图片清单」第 5 行 -->

## 系统架构

浏览器只访问 Vite 开发服务器。页面是 React 19。Vite 把 `/api` 转发到 FastAPI。配队进入 `pokemon_kb`，检索进入 `knowledge_search`，对战进入 `battle`。需要口语时才调用 `dengdeng_reply`：本地 LoRA、云端教师、程序模板，按校验结果依次回退。对战接口不进入这条成文链。

![架构总图](docs/assets/arch-overview.png)
<!-- 占位：1600x900 白底，内容要求见文末「图片清单」第 2 行 -->

```text
浏览器 :5173
  → Vite 代理 /api
  → FastAPI :8000
       ├─ 配队  pokemon_kb.propose_team_line → complete_team_answer → dengdeng_reply
       ├─ 检索  knowledge_search（规则意图 → JSON）→ 可选网页 / 可选向量 → dengdeng_reply
       └─ 对战  battle.py 结算 → fallback_battle 模板
  可选：USE_LORA_REPLIER 时，配队与检索的成文先走 data/lora/adapter
  可选旧链：PDF → chroma_db → qa_chain → POST /api/v1/query
```

正式入口不是 Gradio，也不是 Vue。`app.py` 仍可单独启动旧的 Gradio 页面（默认端口 7862）。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI、Uvicorn |
| 编排 | LangChain（政策链与可选向量检索） |
| 向量库 | Chroma，嵌入模型 bge-m3 |
| 词面检索 | BM25（中文分词） |
| 云端模型 | 智谱 GLM 或 DeepSeek，仅作教师与政策问答 |
| 前端 | React 19、Vite 6、Tailwind CSS 4、Lucide |
| 训练 | PEFT LoRA、Hugging Face Trainer、基座 Qwen2.5-1.5B-Instruct |

RAG（Retrieval-Augmented Generation）指先检索段落再生成。LoRA（Low-Rank Adaptation）指在冻结基座旁训练一小层适配器。BM25 按词匹配。Chroma 是本地向量库。Teacher 是云端 API，没有可训练权重。Student 是 1.5B 开源模型。Adapter 是 LoRA 权重目录，需在本地训练，不在本仓库中。

## 方法

### 知识层

每只精灵一份 JSON，字段同构，见 `knowledge/pokemon/`。规则、技能总表和属性克制在 `knowledge/rules.md`。`knowledge/知识库.md` 是人类原稿，运行时代码不读取，避免和 JSON 重复索引。读取与选人在 `pokemon_kb.py`：`load_pokemon`、`propose_team_line`、`complete_team_answer`、`validate_team_answer`。

`dengdeng_kb.py` 是未被引用的副本，不要把它当成图鉴。

### 检索

`knowledge_search.plan_query` 先用规则判定意图。点到名字、技能、属性或板块时不调用模型。只有结果仍是 `unknown` 时，`_plan_with_model` 才要求云端输出意图 JSON。`lookup_by_plan` 从 JSON 和规则组装事实。

向量索引是加分项，目录为 `data/knowledge_index`，与政策库 `chroma_db` 不是同一套。没有本地 bge-m3 且进程离线时，索引与召回步骤跳过，回答仍使用结构化命中。`BM25_WEIGHT` 不参与结构化查找。

### 政策 RAG（可选旧链）

`document_processor` 解析 `data/` 中的 PDF，并可并入 `rules.md` 板块，不收录精灵 JSON。`embeddings.py` 调用 bge-m3。`vectorstore.py` 与 `bm25_chinese.py` 做混合检索，`query_router.py` 在政策链上做自适应路由，`qa_chain.py` 生成回答。入口是 `POST /api/v1/query`。`QA_PROMPT` 仍写「洛克宠物配队助手」，与网页里灯灯的 `SYSTEM` 不是同一条提示词。

![政策 RAG 数据流](docs/assets/flow-rag.png)
<!-- 占位：1400x800，内容要求见文末「图片清单」第 6 行 -->

### 成文

`agents/dengdeng_persona.py` 定义唯一的系统提示和校验函数。`agents/dengdeng_reply.compose` 的顺序是：若 `USE_LORA_REPLIER` 开启且适配器存在，则本地 LoRA；否则或校验失败时走教师；再失败则程序模板。检索校验为 `_keeps_facts`，配队校验为 `team_keeps_roster`。无资料时 `pick_cry`，不调用模型。

### LoRA

`agents/lora_collect.py` 用现有程序产生事实，再让教师只改口吻，写入 `data/lora/train.jsonl`。`train_lora._mask_labels` 把提示词部分的 label 设为 `-100`，损失只优化助手回答。`LoraConfig` 的实际值为 `r=8`、`lora_alpha=16`、`lora_dropout=0.05`、`target_modules=["q_proj","v_proj"]`。训练默认 3 个 epoch、`max_length=1536`、batch 1、梯度累积 8、CUDA 上使用 fp16 与梯度检查点。脚本拒绝 7B 基座。`train_dpo.py` 与 `train_ppo.py` 只导出偏好或打分，不更新权重。`lora_reproducer.py` 与 `agents/skill_distill.py` 属于旧撰写员路径，不是产品成文。

![LoRA 训练与回退](docs/assets/flow-lora.png)
<!-- 占位：1400x800，内容要求见文末「图片清单」第 7 行 -->

### 对战

`battle.start_battle` 与 `play_move` 在进程内结算，记录约 1800 秒后过期。`api._battle_narration` 只调用 `fallback_battle`。道具不占回合。愿力强化把第一栏换成愿力冲击，而不是立即造成伤害。进化之力按生命比例切换首领形态。

## 仓库结构

```text
.
├── api.py                      # HTTP 入口
├── app.py                      # 旧 Gradio，非 5173 主路径
├── config.py                   # 环境变量与构建指纹
├── pokemon_kb.py               # 图鉴、选人、补全
├── knowledge_search.py         # 网页检索主路径
├── battle.py                   # 对战结算
├── photos.py                   # 读取本地 photo/
├── web_search.py               # 可选公网检索
├── qa_chain.py                 # 政策问答链
├── train_lora.py               # LoRA 训练
├── eval_lora.py                # 基座 / LoRA / 教师对比
├── agents/                     # 配队编排、灯灯人设、采集
├── web/                        # React 19 前端（不含依赖与切图）
├── knowledge/                  # JSON 图鉴、rules.md、原稿
├── scripts/                    # bge-m3 下载、Ragas 检查
├── docs/新手复现指南.md
├── requirements.txt
├── .env.example
├── run_web.bat
└── run_api.bat
```

公开仓库不包含 `photo/` 中的图片、`web/public/ui/*.png`、`.env`、`chroma_db/`、`bge-m3/`、`data/lora/adapter`、政策 PDF 与 `node_modules`。立绘目录需要克隆后自行准备，可参考 `photo/.gitkeep`。

![登录与游客入口](docs/assets/ui-auth.png)
<!-- 占位：1200x800，内容要求见文末「图片清单」第 8 行 -->

## 快速开始

```bat
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
cd web
npm install
```

在 `.env` 中填写自己的 `ZHIPU_API_KEY`。不要把该文件提交到 Git。然后开两个终端：

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

浏览器打开 `http://127.0.0.1:5173`。也可双击 `run_web.bat`。接口文档在 `http://127.0.0.1:8000/docs`。

没有政策 PDF 也可以使用配队、检索和对战。没有 `photo/` 时，立绘位置显示占位爪印，界面切图回退到 Lucide 图标。

更细的步骤、超时和失败日志见 `docs/新手复现指南.md`。`docs/项目精读-新手版.md`、`docs/洛克宠物配队-技术方案.md` 与 `docs/当前实现盘点.md` 若仍留在本地工作副本中，不要当作当前行为。

## 配置

数值与 `config.py`、`.env.example` 一致。改 `.env` 后需重启 API。下表不包含真实密钥。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `ZHIPU_API_KEY` | 空 | 智谱密钥。为空时进程拒绝启动 |
| `ZHIPU_BASE_URL` | `https://open.bigmodel.cn` | 智谱地址 |
| `LLM_PROVIDER` | `zhipu` | `zhipu` 或 `deepseek` |
| `OPENAI_MODEL` | `glm-4-flash` | 智谱模型名 |
| `DEEPSEEK_API_KEY` | 空 | 仅 DeepSeek 供应商需要 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 模型名 |
| `LLM_TIMEOUT` | 60 | 政策 `/query` 超时（秒） |
| `TEAM_LLM_TIMEOUT` | 45 | 意图规划等短调用 |
| `VOICE_LLM_TIMEOUT` | 120 | 灯灯教师成文。未写入 `.env.example`，代码读取该变量 |
| `TEAM_USE_VECTOR` | `false` | 为 true 时配队才尝试政策向量库 |
| `USE_LORA_REPLIER` | `false` | 为 true 且适配器存在时，配队与检索先走 LoRA |
| `WEB_SEARCH_API_KEY` | 空 | 联网搜寻。引擎默认 `tavily`，也可 `bing`、`bravesearch` |
| `WEB_SEARCH_ENGINE` | `tavily` | 搜索引擎 |
| `WEB_SEARCH_ENDPOINT` | 空 | 空则使用官方地址 |
| `DATA_DIR` | `data` | PDF 与检索索引的父目录 |
| `PERSIST_DIRECTORY` | `chroma_db` | 政策 Chroma |
| `USE_PARENT_CHILD` | `true` | 政策文档父子块 |
| `BM25_WEIGHT` / `VECTOR_WEIGHT` | 0.5 / 0.5 | 仅混合检索。不影响 JSON 结构化查找 |
| `USE_RERANKER` | `false` | 重排序，默认关闭 |
| `EMBEDDING_MODEL` | 本地目录 `bge-m3`，否则 `BAAI/bge-m3` | 不由 `.env` 覆盖 |

`config.py` 将 `CHUNK_SIZE` 与 `CHUNK_OVERLAP` 固定为 500 与 50。只改 `.env.example` 里的同名项不会生效。

## API 摘要

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/v1/auth/register`、`/login`、`/change-password` | 注册、登录、改密。密码至少 6 位，存储为无盐 SHA-256 |
| `POST /api/v1/agents/jobs`，`GET /api/v1/agents/jobs/{id}` | 配队任务与轮询 |
| `POST /api/v1/knowledge/jobs`，`GET /api/v1/knowledge/jobs/{id}` | 检索任务。`use_web` 仅在检索模式由页面传入 |
| `POST /api/v1/battle/start`，`POST /api/v1/battle/{id}/move` | 开战与出招 |
| `GET /api/v1/pokemon`，`GET /api/v1/pokemon/{name}/skills` | 名录与技能 |
| `GET /api/v1/photo/{name}` | 本地 `photo/` 中的 PNG。公开仓库不附带这些文件 |
| `POST /api/v1/query` | 政策 RAG 旧链 |
| `POST /api/v1/rebuild` | 重建政策向量库 |

游客请求不带 `user_id`。前端默认请求超时 15 秒；配队与检索创建为 12 秒，轮询 8 秒；对战开始与出招为 20 秒。

## 复现实验

硬件建议：训练与评测使用不少于 8GB 显存的 NVIDIA GPU。CPU 只适合冒烟，不作为论文数字。采集阶段调用云端教师，不需要 GPU。下载基座时不要设置 `HF_HUB_OFFLINE`，可设置 `HF_ENDPOINT=https://hf-mirror.com`。

```bat
.\.venv\Scripts\python.exe -m agents.lora_collect
.\.venv\Scripts\python.exe train_lora.py
.\.venv\Scripts\python.exe eval_lora.py
```

训练完成后，确认本地存在 `data/lora/adapter/adapter_config.json`，在 `.env` 设置 `USE_LORA_REPLIER=true` 并重启 API。评测表写入 `data/lora/eval_report.md`。未实际运行时不要填写准确率。

显存不足时保持 batch 为 1 与梯度检查点，将 `--max-length` 降到 1280 或 1024，不要改用 7B。

## 评测与局限

- 口吻模型不保证事实。校验失败会丢弃该次生成。
- 没有向量库时，检索信息跳过混合检索，不会因此编造种族值。
- 图鉴覆盖范围以 `knowledge/pokemon/` 为准，不是完整游戏图鉴。
- 对战只实现已写入 `battle.py` 的规则。星陨印记、奉献等未实现的机制不会被静默结算。
- 联网结果只作背景，不覆盖本地技能效果与种族值。
- 密码哈希无盐，仅适合本地演示。

## 路线图

- 补齐 `docs/assets/` 中的架构图与界面截图。
- 在有 GPU 的环境重新采集、训练并公布不含权重的评测表。
- 将政策问答提示词与灯灯人设彻底分开，避免读者把 `/query` 当成网页主路径。

## 伦理与免责

本项目是非官方的粉丝向研究原型，未获腾讯或洛克王国权利人的授权，禁止商用。仓库不提供游戏客户端、立绘或界面切图。请勿把模型输出当作官方规则。请勿提交密钥、个人账号或未授权的游戏美术。

若本地 `.env` 或历史提交曾经离开本机，请在对应控制台轮换密钥，并停止使用已暴露的密钥。

## 引用

```bibtex
@misc{dengdeng2026,
  title        = {灯灯：面向洛克王国对战辅助的结构化检索与口吻蒸馏原型},
  author       = {Dengdeng AI contributors},
  year         = {2026},
  howpublished = {\url{https://github.com/569838281-a11y/dengdeng_ai}},
  note         = {非官方研究原型。游戏名称与素材版权归原权利人。}
}
```

## 许可证

代码以 [MIT License](LICENSE) 授权。该许可不覆盖游戏名称、立绘、UI 切图、技能原文或其他权利人素材。这些内容即使出现在本地工作副本中，也不因本仓库的 MIT 条款而获得再授权。

## 图片清单

| 文件名 | 尺寸 | 位置 | 要求 | 优先级 |
| --- | --- | --- | --- | --- |
| `docs/assets/cover.png` | 1920×800 | 文首 | 产品封面：登录页或主界面。打码密钥与个人账号，演示名用「小洛克」 | P0 |
| `docs/assets/arch-overview.png` | 1600×900，白底 | 架构 | 模块框图：Web、API、知识库、对战、LoRA。中文标注，可用 draw.io 导出 | P0 |
| `docs/assets/demo-team.png` | 1440×900 | 演示 | 智能配队结果，能看见 6 人卡片 | P0 |
| `docs/assets/demo-search.png` | 1440×900 | 演示 | 检索信息、RagFlow 步骤条、灯灯气泡 | P0 |
| `docs/assets/demo-battle.png` | 1440×900 | 演示 | 对战场面，可为一键配招后开战 | P0 |
| `docs/assets/flow-rag.png` | 1400×800 | 方法 · 政策 RAG | PDF → 分块 → 向量 → BM25 → 生成，并标明这是可选旧链 | P1 |
| `docs/assets/flow-lora.png` | 1400×800 | 方法 · LoRA | 教师采集 → label=-100 → adapter → 校验回退。不要画出权重文件内容 | P0 |
| `docs/assets/ui-auth.png` | 1200×800 | 仓库结构之后 | 登录、注册与游客入口 | P2 |
