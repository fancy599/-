# 内控制度智能审查平台 — Demo 应用

可本地运行的全栈应用：**FastAPI + React + SQLite**，采用 Hybrid Pipeline，需配置 **OpenAI 兼容 LLM API Key**。

## 环境要求

- Python 3.11+
- Node.js 18+
- LLM API Key（OpenAI / DeepSeek / 通义等 OpenAI 兼容接口）
- 百度智能云文档解析 / OCR 的 API Key 与 Secret Key（PDF 识别必需）
- **`.doc` 旧版 Word**：Windows 建议安装 Microsoft Word，并执行 `pip install pywin32`；或安装 LibreOffice。也可在 Word 中另存为 `.docx` 后上传。

## 快速开始

### 1. 配置环境变量

```bash
cd ic-review-app
copy .env.example .env
```

编辑 `.env`，至少设置：

```env
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
PDF_PARSER_PROVIDER=baidu
BAIDU_OCR_API_KEY=你的百度 OCR API Key
BAIDU_OCR_SECRET_KEY=你的百度 OCR Secret Key
AUTO_SEED=true
```

> **PDF 识别要求：** 本项目的 PDF 识别链路必须使用百度智能云文档解析 / OCR。上传 PDF 前必须完成以上三项配置；未配置时，请勿将 PDF 解析结果用于正式审查。Word、TXT 等非 PDF 文件不受此项限制。

若报错 `invalid temperature: only 1 is allowed for this model`，在 `.env` 增加：

```env
LLM_TEMPERATURE=1
```

（不配置时程序也会自动用 `temperature=1` 重试一次。）

国产模型示例（DeepSeek）：

```env
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

生产环境建议为两个认知 Agent 分别配置模型：

```env
# 中等模型：承担章节并行初审，优先吞吐量与成本
CORE_ANALYSER_MODEL=your-medium-model
CORE_ANALYSER_BASE_URL=https://your-medium-model-gateway/v1
CORE_ANALYSER_API_KEY=your-medium-model-key
CORE_ANALYSER_FALLBACK_MODEL=your-medium-fallback-model

# 大型模型：承担最终合规仲裁，优先准确率与复杂推理
SOE_EXPERT_MODEL=your-large-model
SOE_EXPERT_BASE_URL=https://your-large-model-gateway/v1
SOE_EXPERT_API_KEY=your-large-model-key
SOE_EXPERT_FALLBACK_MODEL=your-large-fallback-model
```

两套模型可连接同一个 LLM Gateway，也可连接不同私有化推理服务。未配置专用连接时暂时回退到通用 `LLM_*` 配置。

### 2. 启动后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开：http://localhost:5173

## 人工验收清单

1. 访问首页，若 `AUTO_SEED=true` 应看到待办任务；否则点击 **加载演示数据**
2. 点击 **继续复核此任务** → 进入差异清单（≥3 条）
3. 点击某条差异 → 双栏对照 → **确认差异** → 复核记录页有记录
4. **制度库** 上传 `.txt` / `.doc` / `.docx` → 列表显示 `parsed`（`.doc` 需本机 Word 或 LibreOffice）
5. **创建任务** 选择集团/子公司文档 → **创建并运行流水线** → 六步进度与 Agent 日志更新 → 进入差异清单
6. **导出 Excel / HTML** 可下载打开

## 运行测试

```bash
cd backend
.venv\Scripts\activate
pytest -v
```

测试使用内存 SQLite + Mock LLM，无需真实 API Key。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/seed/demo` | 写入采购样例数据 |
| GET | `/api/dashboard` | 首页待办 |
| POST | `/api/documents/upload` | 上传制度 |
| POST | `/api/tasks` | 创建任务 |
| POST | `/api/tasks/{id}/run` | 启动流水线 |
| GET | `/api/tasks/{id}/pipeline/stream` | SSE 进度 |
| GET | `/api/tasks/{id}/diffs` | 差异清单 |
| POST | `/api/diffs/{id}/review` | 复核 |
| GET | `/api/tasks/{id}/export?format=xlsx` | 导出 |

## 架构说明

- 产品内置 422 条标准控制点，覆盖 19 个业务领域；启动时自动同步至 `standard_control_points`
- 单份制度体检按所选业务领域加载对应标准控制点，逐项检查制度覆盖情况并展示标准编码与来源依据
- 上传制度和发起单份制度体检时应选择正确业务领域，避免加载不适用的标准控制点
- 确定性代码负责结构化解析、控制点预筛、证据校验和报告统计
- `Core Analyser` 使用中等模型按章节并行识别差异，`SOEExpertAgent` 使用大型模型完成最终仲裁
- `fast/full` 参数仅用于兼容旧客户端，统一映射到 `hybrid`
- 每步输出经 Pydantic 校验并写入 Checkpoint 与 `pipeline_run_logs`
- 无证据的差异标记为 `pending_evidence`，不进入正式报告统计
- 总则、术语与定义等全局章节变化会更新 `global_context_hash`，阻止下游章节错误复用旧缓存
- 补充材料除局部覆盖判断外，还会执行二次污染红线扫描并衍生待确认差异
- 集团基准升级时，历史例外按语义变化自动继承或暂停重审
- 疑似 PDF 复杂权责矩阵会显式警告，并提供原始页面快照供人工核验

## 目录结构

```
ic-review-app/
├── backend/          # FastAPI
├── frontend/         # React + Vite
├── data/             # SQLite + 上传文件（运行时生成）
└── .env.example
```
