# 作品集站点大纲

站点只放已经能对上源码的项目。灯灯是主案例。语气与 `portfolio.md` 相同。图都先用占位，清单见该文件文末。

非官方粉丝向原型。洛克王国素材版权归原权利人。

## 首页

- 标题：会把模型接进产品，并在它说错时停下来。
- 一段介绍：做检索、校验、降级和界面，而不是只调聊天接口。
- 一个主案例卡片：灯灯。三张图链到 `docs/assets/demo-team.png`、`demo-search.png`、`demo-battle.png`。
- 封面 `docs/assets/cover.png`。
- 按钮：看案例、看源码（https://github.com/569838281-a11y/dengdeng_ai）。

## 项目页

按 `docs/career/portfolio.md` 的顺序排成一页：

1. 一句话和三张演示图。
2. 角色：知识、接口、界面、口吻模型。
3. 约束：不能编数值、接口不能等模型、8GB、版权。
4. `docs/assets/arch-overview.png` 和旁注。
5. 三个切片。结构化优先、程序配队、LoRA 只训口吻且对战先结算。
6. 不超过 6 条亮点。
7. 三分钟演示脚本，含一键配招。
8. GitHub 与本地 5173。
9. 反思：评测数字、LoRA 默认开关、素材授权。

页内不要出现 Vue 主前端、模型自动选 6 人、或未实测百分比。政策 RAG 放在页脚一条：「同仓库还有一条文档检索实验，不是这个案例的主路径。」配图用 `docs/assets/flow-rag.png`。

## 关于我

- 目标岗位：AI 应用工程师。
- 能讲清的一件事：哪些步骤必须是程序，哪些步骤可以交给模型。
- 技能只列用过的：FastAPI、React 19、规则检索、可选 RAG、智谱 API、PEFT LoRA、任务轮询与降级。
- 不写用户量。不写密钥。联系方式用占位，不要写真实账号。

## 页面文件建议

| 页面 | 建议路径 | 内容来源 |
| --- | --- | --- |
| 首页 | `index.html` 或 Notion 首页 | 本节「首页」 |
| 灯灯 | `dengdeng.html` 或 Notion 子页 | `portfolio.md` |
| 关于 | `about.html` | 本节「关于我」 |

构建方式可以是 GitHub Pages 的静态页，或把 `portfolio.md` 直接贴进 Notion。PDF 用 `cover-one-pager.md` 作附件，不用把整份案例缩成一页。
