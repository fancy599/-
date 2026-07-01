# CLAUDE.md

本文件用于指导 Claude / Claude Code 在本仓库中工作。

## 交流约定（最高优先级）

- **始终用中文回答**，包括解释、计划、提交说明与代码注释中的说明性文字。
- 表述简洁直接，先给结论与改动，再给必要说明；避免冗长铺陈。
- 改动代码前先理解 PRD 与现有实现；涉及多文件或结构性改动时，先说明问题与方案再动手。
- 不擅自做大范围重构或破坏性变更；无法运行测试验证时，优先选择向后兼容的小改动，并说明未验证的部分。

## 项目简介

内控制度智能审查平台（事务所自用）。面向事务所咨询人员，用"确定性工程解析 + 两层 AI 认知判断 + 人工复核"完成：

- **集团 vs 子公司**制度差异审查；
- **单份制度体检**（基于标准控制点库，无需集团基准）；
- 输出带证据链、可复核、可导出（Word/Excel/HTML）的差异/缺陷底稿。

完整需求见上层目录的《内控制度智能审查平台 PRD》。第一阶段聚焦差异引擎质量，不做泛化合规问答。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.x + SQLite（WAL），Python 3.11+。
- 前端：React + Vite + TypeScript + React Router。
- LLM：OpenAI 兼容接口（OpenAI / DeepSeek / 通义等），可为两层 Agent 分别配置模型。
- 导出：openpyxl（Excel）、python-docx（Word）。

## 目录结构

```
ic-review-app/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── config.py          # 配置（.env 读取）
│   │   ├── db.py              # 引擎/会话/建表与 SQLite 在线列迁移
│   │   ├── models.py          # ORM 模型
│   │   ├── schemas.py         # Pydantic 出入参
│   │   ├── seed.py            # 演示数据
│   │   ├── api/routes.py      # 全部 HTTP 路由（含单制度体检、导出）
│   │   ├── pipeline/          # 流水线
│   │   │   ├── orchestrator.py   # 六步主编排（Hybrid Pipeline）
│   │   │   ├── agents.py         # 两层认知 Agent + 历史编排
│   │   │   ├── agent_schemas.py  # Agent 输入输出 Pydantic 约束
│   │   │   └── prompts.py        # 提示词
│   │   └── services/          # 确定性工程模块
│   │       ├── parser.py            # 解析/OCR/表格路由
│   │       ├── clause_splitter.py   # 条款切分
│   │       ├── control_heuristic.py # 控制点启发抽取
│   │       ├── match_prefilter.py   # 匹配前相似度预筛
│   │       ├── evidence_verify.py   # 证据校验
│   │       ├── robustness.py        # 低置信度降级安全栏
│   │       ├── standard_control_library.py # 标准控制点库（含种子）
│   │       ├── export.py            # Excel/Word/HTML 导出
│   │       └── text_normalize.py    # 正文清洗
│   │   └── utils/timeutil.py  # 统一 UTC 时间工具
│   ├── tests/                 # pytest（内存 SQLite + Mock LLM）
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/             # Home/Library/TaskCreate/TaskDetail/DiffDetail/SingleAudit/Records/Governance
│       ├── components/        # Layout/PipelineBanner/StatCards 等
│       ├── pipeline/          # PipelineContext（SSE/轮询进度）
│       ├── api/client.ts      # 后端调用
│       └── styles.css         # 全局样式
└── docker-compose.yml
```

## 启动与测试

后端（默认端口 8000）：

```bat
cd ic-review-app
copy .env.example .env   :: 填写 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL，建议 AUTO_SEED=true
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端（默认端口 5173）：

```bat
cd ic-review-app\frontend
npm install
npm run dev
```

常用地址：前端 http://localhost:5173 ，API http://localhost:8000 ，健康检查 `/api/health` ，接口文档 `/docs` 。

测试（无需真实 Key，用内存 SQLite + Mock LLM）：

```bat
cd backend && .venv\Scripts\activate && pytest -v
```

## 架构与主链路

仅 **两个需要大模型认知判断的 Agent**，其余（解析、切分、检索、规则、证据校验、报告、调度）都是确定性工程模块，不包装成 Agent。

| 认知 Agent | 职责 |
|---|---|
| Core Analyser（初审，中等模型） | 对"集团/标准控制点 + 召回候选证据"判覆盖与差异 |
| SOEExpertAgent（仲裁，大型模型） | 对候选差异做保留/驳回/风险修正/合规仲裁 |

六步 Hybrid 主链路（`orchestrator.py`）：本地结构化解析 → 标准控制点/规则上下文 → 控制点抽取 → Core Analyser 覆盖判定（控制点按章节分桶并行）→ SOEExpert 仲裁 → 证据/血缘校验降级 → 报告 → 人工三级复核 → 导出。

- 创建任务接口立即返回 `task_id`，长任务后台执行；前端经 SSE/轮询监听。
- 单个控制点失败仅生成该点"待确认/中风险"兜底，不致整任务失败。
- LLM 失败按"同模型重试 → 备用模型 → 待确认兜底"降级（见 `services/llm.py`）。
- 低置信度强判断自动降级为"待确认/中风险"（`services/robustness.py`，阈值 0.60）。

## 数据模型要点

- 隔离单元应为"客户项目 `engagement_id`"（PRD §11/§12 的上线硬门，**当前尚未实现**，见下方待办）。
- 证据血缘表 `DiffClauseMapping` 用于一条差异关联多条原文；PRD 要求其为**唯一来源**（当前仍由 `Difference` 的单值条款外键反向生成，属待整改）。
- `ReviewTask.task_type`：`group_vs_subsidiary` / `single`，显式区分集团对子公司与单制度体检（勿再用 `group_id==subsidiary_id` 隐式判断）。
- 标准控制点库以数据库为运行期来源，代码常量仅作首次初始化种子。

## 关键设计原则（务必遵守）

1. 以**控制点**为分析单元做全文语义覆盖判断，不按条款编号/章节顺序强制配对。
2. 每条结论必须**引用原文**（文件名/章节/条款/页码）；无证据来源只进"待人工确认"，不进正式底稿。
3. 控制点抽取要过滤目的、范围、口号、定义、标题等非控制性内容。
4. 置信度由可观测信号**合成**，不直接采用模型自报值。
5. 确定性问题（金额阈值、越权、三重一大、职责分离）优先走规则/正则/命名实体识别，再交模型处理语义不确定部分。
6. 面向用户界面**不展示英文 Agent 名/模型名/技术流水线名**；用业务化中文（如"制度对照检查""单份制度体检""复核与导出"）。
7. 时间统一 UTC 存储，交互用带时区 ISO 8601，前端按本地时区展示。

## 开发约定与注意事项

- 新增/修改字段优先**带默认值**并在 `db.py` 的在线迁移字典中补列，保证旧 SQLite 平滑升级。
- 导出统一走 `services/export.py`：`export_task_xlsx` / `export_task_docx` / `export_task_html`，路由 `/api/tasks/{id}/export?format=xlsx|docx|html`。
- 改 ORM 字段时同步检查：`schemas.py` 出参、`db.py` 迁移、相关路由与导出。
- 前后端地址/端口、CORS 通过 `.env` 配置，不要硬编码本机地址。
- 提交前在本机跑 `pytest -v` 回归（沙箱环境常无网络、装不全依赖，无法跑全量）。

## 已知待办（按优先级，详见上层《PRD对照代码审查报告.md》）

- **P0**：客户项目级隔离 `engagement_id` + 数据访问层强制过滤 + 利益冲突隔离 + 数据生命周期/销毁。
- **P1**：证据血缘改为唯一来源（去 `Difference` 单值条款外键）；落实"以控制点为中心的检索召回（向量+规则+关键词 Top-K）"；单制度体检 `group_document_id` 改为可空。
- **P2**：三级复核链建模与签字身份；置信度多信号合成与来源记录；复杂表格/权责矩阵结构化解析。
- **P3**：`llm.py` OOM 判断加括号、备用模型跨温度循环重置；评测集与质量基线流程。
