# 简历项目：灯灯

非官方粉丝向原型。游戏名称为洛克王国，素材版权归原权利人。下文不写未实测的准确率、延迟或用户量。

## 中文标题

洛克王国智能助手「灯灯」——检索增强的对战辅助应用（个人项目）

## 英文标题

Dengdeng: a Roco Kingdom battle assistant with checked generation (unofficial personal project)

## 技术栈

FastAPI / React 19 / 结构化知识库 / 可选混合检索 RAG / 智谱 API / PEFT LoRA / 规则对战引擎

## 项目简介

玩家查技能、配六人队、试伤害时，通用模型容易编种族值和技能效果。我做了非官方原型「灯灯」：同一 React 页面提供配队、检索、模拟对战。选人与结算走程序和 JSON，精灵灯灯只把已核对的事实说成口语。无资料时不编图鉴。

## 职责要点

- 用 `pokemon_kb.propose_team_line` 按标签和点名选出 6 人，再由 `complete_team_answer` 补满 4 技能、血脉和道具，避免模型编造名单。
- 检索走 `knowledge_search`：`plan_query` 规则定意图，`lookup_by_plan` 查 JSON 与 `rules.md`，向量召回可选；无命中时 `pick_cry`，不调用模型编图鉴。
- 成文由 `dengdeng_reply.compose` 按本地 LoRA、云端 teacher、模板回退；`_keeps_facts` 与 `team_keeps_roster` 不过就丢弃该次生成。
- 对战在 `battle.py` 按板块 M 结算，道具不占回合；愿力强化改第一栏为愿力冲击，进化之力按生命比例换首领形态。`api._battle_narration` 只用模板，不让模型堵住接口。
- 用 React 19、Vite、Tailwind 做登录、游客和三模式；`ChatApp` 轮询配队与检索任务，`RagFlow` 显示步骤，立绘与灯灯思考、普通、哭腔三态头像走 `photos.py`。
- 用 `lora_collect` 采 teacher 的 jsonl，`train_lora._mask_labels` 把提示词标成 -100，只优化助手回答；基座为 Qwen2.5-1.5B-Instruct，PEFT 的 r=8，按 8GB 显存设置 fp16 与梯度检查点。
- 同仓库保留政策 PDF 实验链：父子块、BM25 与向量混合检索后进入 `qa_chain` 和 `POST /query`。这不是 5173 的检索主路径。

## 英文要点

- Replaced roster picking with `propose_team_line` so the model cannot invent the six names.
- Search is structured first (`plan_query`, JSON, `rules.md`); vector recall is optional; empty hits use `pick_cry`.
- Voice path is LoRA, then teacher, then a template, and each draft must pass a fact check.
- Battle math stays in `battle.py`. Narration does not block `start` or `move`.
- Shipped a React 19 client with job polling, a step strip, and three Dengdeng portraits.
- Distilled tone only: prompt tokens labeled -100, Qwen2.5-1.5B LoRA sized for 8GB.
- Kept a separate policy-PDF RAG chain. It is not the product search path.

## 30 秒口述

这是一个非官方的洛克王国辅助原型。玩家最怕模型编技能和种族值，所以选人、查资料、算伤害都在程序里。`propose_team_line` 配好 6 人，`knowledge_search` 先查 JSON，`battle.py` 按公式结算。灯灯是双灯鱼人设，只负责把这些结果说成人话。本地 LoRA 说得不像或丢了事实，就回退到云端老师，再不行就用模板。对战解说不进这趟模型，避免一点技能就卡住。

## 追问

1. **为什么配队不用模型选人？**  
   名单必须是库里的 6 只，还要满足技能栏、血脉和道具。模型容易多写、少写或换名。`run_collaborative_agents` 里选人调用的是 `propose_team_line`，模型只进入后面的 `reply_team`。

2. **LoRA 和 RAG 各解决什么？**  
   产品检索不是先向量再生成。事实来自 JSON 和 `rules.md`。LoRA 只学「给定这段事实后，用灯灯的口气说」。政策 PDF 那条 `qa_chain` 才是经典混合检索，而且不是 5173 的主路径。

3. **改了 `BM25_WEIGHT`，为什么页面没变化？**  
   结构化查找不读这个权重。它只影响政策库，以及 `data/knowledge_index` 真的建成之后的召回。没有本地 bge-m3 时，索引和召回会跳过。

4. **怎么保证灯灯不编数字？**  
   不能从训练上保证。推理时 `_keeps_facts`、`team_keeps_roster` 检查名字和关键事实还在不在。不在就丢掉这次生成。没有资料时直接 `pick_cry`。

5. **对战为什么不等大模型？**  
   冷加载 1.5B 或等待 teacher 会超过前端超时。`battle_start` 和 `battle_move` 先 `start_battle` / `play_move`，解说只走 `fallback_battle`，并返回 `narration_pending: false`。

6. **愿力强化为什么不是立刻掉血？**  
   源码里点击道具只把第一栏换成愿力冲击，并写下冷却，不结算伤害、不让对方行动。真正出招才扣能量。进化之力则先算当前生命占上限的比例，再套到新上限上。

7. **8GB 怎么训？**  
   `train_lora.py` 固定 batch 1、梯度累积 8、`max_length` 1536、只改 `q_proj` 和 `v_proj`、r=8。有 CUDA 才开 fp16 和梯度检查点。脚本拒绝 7B。CPU 只适合冒烟，不能当成评测结果。

8. **评测数字呢？**  
   `eval_lora.py` 会把基座、LoRA、teacher 写成三列，输出到 `data/lora/eval_report.md`。简历里不引用未贴出的百分比。适配器也不在公开仓库里。

## 技能关键词

| 分组 | 用过的 |
| --- | --- |
| 应用落地 | FastAPI 任务接口、超时与降级、游客与登录、内存对战状态 |
| LLM 工程 | 智谱或 DeepSeek teacher、同一份 `SYSTEM`、生成后校验、失败回退模板 |
| 检索 | 规则意图、JSON 查找、可选向量索引、可选联网搜寻、BM25 与向量只用于政策旧链 |
| 前端 | React 19、Vite、Tailwind、任务轮询、RagFlow、立绘与三态头像 |
| 训练评测 | PEFT LoRA、`_mask_labels`、teacher 采集 jsonl、三列评测脚本、8GB 训练配置 |
