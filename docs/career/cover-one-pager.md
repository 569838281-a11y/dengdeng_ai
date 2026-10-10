# 灯灯 · 一页纸

洛克王国智能助手「灯灯」（个人项目，非官方）  
粉丝向原型。游戏名称与素材版权归原权利人。

| 做成了什么 | 系统怎么接 |
| --- | --- |
| 同一页面三个入口：配队、检索、模拟对战。正式前端是 React 19 + Vite + Tailwind，不是旧的 Gradio。 | 浏览器 5173 把 `/api` 转到 FastAPI。配队、检索、对战分三条接口。 |
| 六人名单由 `propose_team_line` 选出，模型只改口吻。校验失败就丢弃这句，改用模板。 | `pokemon_kb` 读 JSON。`complete_team_answer` 补 4 技能、血脉、道具。`TeamCards` 画程序名单。 |
| 查技能和精灵时先走规则和 JSON。没有资料就哭腔，不编图鉴。向量检索是可选步骤。 | `knowledge_search.run_knowledge_search`。政策 PDF 的 `qa_chain` 留在同仓库，不是这条主路径。 |
| 对战按板块公式结算。道具不占回合。愿力强化改第一栏。进化之力保持生命比例。点击后不等待大模型。 | `battle.py` 结算。`_battle_narration` 只用本地模板。 |
| 口吻用 Qwen2.5-1.5B 的 LoRA 蒸馏，8GB 可训。损失只优化助手回答。适配器不随公开仓库分发。 | `lora_collect` 采老师句子。`_mask_labels` 将提示词标为 -100。推理顺序是 LoRA、teacher、模板。 |
| 页面有登录和游客、任务轮询、检索步骤条、灯灯三态头像。 | `ChatApp`、`RagFlow`、`photos.py`。 |

![架构占位](../assets/arch-overview.png)
<!-- 占位：1600x900 白底。模块：Web、API、知识库、对战、LoRA。中文。不要截密钥。 -->

源码：https://github.com/569838281-a11y/dengdeng_ai  
本地：http://127.0.0.1:5173  
未写入任何未实测的准确率或延迟。
