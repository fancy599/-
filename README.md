# 内控制度智能审查平台

面向企业内控制度建设与审查的全栈应用。平台将制度文档解析、标准控制点匹配、AI 差异识别、专家仲裁、人工复核和报告导出串成一条可追踪的审查流水线，帮助用户快速发现制度缺失、冲突、表述不清及证据不足等问题。

> 项目仍处于迭代阶段，不建议直接用于未经人工复核的正式合规结论。

## 核心能力

- 支持 `.txt`、`.doc`、`.docx`、`.pdf` 制度文件上传与解析
- 基于标准控制点库进行制度覆盖检查和差异识别
- 采用 Core Analyser 与 SOE Expert 的分层 AI 审查流程
- 提供任务进度、Agent 日志、差异对照和人工复核记录
- 支持集团制度与子公司制度的依赖、变更和例外治理
- 导出 Excel / HTML 审查结果
- 对缺少证据、复杂 PDF 和高风险差异提供显式提示

## 技术栈

- 后端：Python、FastAPI、SQLAlchemy、Pydantic、SQLite
- 前端：React、TypeScript、Vite
- 异步能力：Celery、Redis（可选）
- 文档处理：PyMuPDF、python-docx、OpenPyXL
- AI：OpenAI 兼容接口，可分别配置分析模型与专家模型

## 目录结构

```text
.
├─ README.md
└─ ic-review-app/       # 可运行的全栈应用
   ├─ backend/          # FastAPI API、审查流水线、控制点数据与测试
   ├─ frontend/         # React + Vite 前端
   ├─ docker-compose.yml
   └─ .env.example      # 环境变量示例
```

运行密钥、本地数据库、用户上传文件、日志、构建目录、客户交付输出及工作区中间文件均通过 `.gitignore` 排除，不应提交到仓库。

## 本地启动

### 1. 准备环境

需要安装：

- Python 3.11+
- Node.js 18+
- 百度智能云文档解析 / OCR 的 API Key 与 Secret Key（PDF 识别必需）
- 可选：Redis 7（启用异步任务时使用）
- Windows 解析旧版 `.doc` 时建议安装 Microsoft Word 和 `pywin32`；也可使用 LibreOffice

复制配置模板：

```powershell
cd .\ic-review-app
Copy-Item .env.example .env
```

编辑 `.env`，至少配置一个 OpenAI 兼容模型：

```env
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
PDF_PARSER_PROVIDER=baidu
BAIDU_OCR_API_KEY=your-baidu-api-key
BAIDU_OCR_SECRET_KEY=your-baidu-secret-key
AUTO_SEED=true
```

生产环境可通过 `CORE_ANALYSER_*` 与 `SOE_EXPERT_*` 分别配置分析模型和专家模型。完整选项见 [`ic-review-app/.env.example`](ic-review-app/.env.example)。

### PDF 识别说明

本项目的 PDF 识别链路必须使用百度智能云文档解析 / OCR。上传 PDF 前，请确保 `.env` 中已经配置：

```env
PDF_PARSER_PROVIDER=baidu
BAIDU_OCR_API_KEY=your-baidu-api-key
BAIDU_OCR_SECRET_KEY=your-baidu-secret-key
```

未配置百度 OCR 时，请勿将 PDF 解析结果用于正式审查。Word、TXT 等非 PDF 文件不受此项限制。

### 2. 启动后端

```powershell
cd .\ic-review-app\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端健康检查：`http://localhost:8000/api/health`

### 3. 启动前端

另开一个终端：

```powershell
cd .\ic-review-app\frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。

### 4. 可选：启动 Redis

```powershell
cd .\ic-review-app
docker compose up -d
```

仅在 `.env` 中设置 `TASK_EXECUTOR=celery` 时需要 Redis；本地开发可继续使用默认线程执行器。

## 运行测试

后端：

```powershell
cd .\ic-review-app\backend
.\.venv\Scripts\Activate.ps1
pytest -v
```

前端：

```powershell
cd .\ic-review-app\frontend
npm run build
```

测试使用隔离数据库和 Mock LLM，不需要真实 API Key。

## 典型使用流程

1. 上传集团制度、子公司制度或待审单份制度。
2. 选择业务领域并创建审查任务。
3. 系统解析条款、筛选控制点并运行 AI 审查流水线。
4. 在差异清单中查看原文、依据、风险等级和修改建议。
5. 人工确认、驳回或补充审查结论。
6. 导出 Excel / HTML 报告并保留复核记录。

## 安全说明

- 不要提交 `.env` 或任何真实 API Key。
- 不要提交本地数据库和 `uploads` 中的原始制度文件。
- AI 结果仅作为辅助意见；正式合规判断必须由具备相应职责和专业能力的人员复核。
- 将项目部署到生产环境前，请补充身份认证、权限控制、审计日志、密钥托管、传输加密和数据生命周期策略。
