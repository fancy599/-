const API = "/api";

export const STANDARD_CONTROL_DOMAINS = [
  "组织架构",
  "发展战略",
  "人力资源",
  "社会责任",
  "企业文化",
  "资金活动",
  "采购",
  "资产",
  "销售",
  "研究与开发",
  "工程项目",
  "担保业务",
  "业务外包",
  "财务报告",
  "全面预算",
  "合同管理",
  "内部信息传递",
  "信息系统",
  "用车管理",
] as const;

export type Health = { status: string; llm_configured: boolean; llm_model: string; message: string };
export type Document = {
  id: number;
  document_name: string;
  unit_name: string;
  document_level: string;
  business_domain: string;
  version: string;
  parse_status: string;
  lock_status: string;
  quality_status: string;
  parse_error_code: string;
  degradation_notes: string;
  table_review_required: boolean;
  complex_table_pages: string;
  ocr_confidence: number | null;
  page_count: number | null;
  file_size: number;
  created_at: string;
};

export type DocumentPreview = Document & {
  file_ext: string | null;
  has_original_file: boolean;
  text_content: string;
  clause_count: number;
};
export type Task = {
  id: number;
  task_name: string;
  business_domain: string;
  description: string;
  group_document_id: number;
  subsidiary_document_id: number;
  status: string;
  execution_mode: string;
  executor_backend: string;
  prompt_bundle_version: string;
  core_model_version: string;
  expert_model_version: string;
  result_version: number;
  degradation_reason: string;
  current_step: number;
  pipeline_error: string | null;
  report_summary: string | null;
  created_at: string;
  completed_at: string | null;
  diff_count: number;
  high_risk_count: number;
  pending_review_count: number;
  reference_template_id?: string;
  reference_template_title?: string;
};
export type Dashboard = {
  pending_task: Task | null;
  total_tasks: number;
  pending_reviews: number;
  recent_tasks: Task[];
};
export type Difference = {
  id: number;
  task_id: number;
  diff_type: string;
  risk_level: string;
  control_topic: string;
  summary: string;
  group_excerpt: string;
  subsidiary_excerpt: string;
  group_location: string;
  subsidiary_location: string;
  ai_reason: string;
  suggestion: string;
  confidence: number;
  evidence_ok: boolean;
  review_status: string;
};
export type DifferenceDetail = Difference & {
  group_clause_text: string;
  subsidiary_clause_text: string;
  group_external_regulation?: string;
  group_external_basis?: string;
  group_clause_truncated?: boolean;
  subsidiary_clause_truncated?: boolean;
  expert_reviewed?: boolean;
  expert_review_note?: string;
  semantic_review?: boolean;
  single_document_audit?: boolean;
  table_review_required?: boolean;
  table_review_documents?: Array<{ side: string; document_id: number; pages: string }>;
};
export type PolicyTemplateSummary = {
  policy_id: string;
  title: string;
  domain: string;
  standard_domain: string;
  owner: string;
  volume: string;
  sequence: number;
  control_count: number;
};
export type PolicyTemplateControl = {
  risk: string;
  topic: string;
  requirement: string;
  evidence: string;
  external_regulation: string;
  external_basis: string;
};
export type PolicyTemplateDetail = PolicyTemplateSummary & {
  controls: PolicyTemplateControl[];
  excerpt_text: string;
};
export type ReviewLog = {
  id: number;
  difference_id: number;
  task_id: number;
  action: string;
  comment: string;
  reviewer: string;
  created_at: string;
  diff_summary: string;
  risk_level: string;
  diff_type: string;
};
export type PipelineLog = {
  id: number;
  step: number;
  agent_name: string;
  status: string;
  message: string;
  duration_ms: number;
  created_at: string;
};
export type Exemption = {
  id: number;
  difference_id: number;
  task_id: number;
  control_topic: string;
  org_scope: string;
  justification: string;
  policy_basis: string;
  base_version: string;
  governance_note: string;
  status: string;
  effective_from: string | null;
  expires_at: string | null;
  approved_by: string;
  created_by: string;
  created_at: string;
};
export type Supplement = {
  id: number;
  difference_id: number;
  task_id: number;
  assignee: string;
  requirement: string;
  status: string;
  due_at: string | null;
  submitted_text: string;
  result: string;
  result_reason: string;
  pollution_scan_result: string;
  derived_difference_ids: string;
  created_at: string;
  submitted_at: string | null;
  closed_at: string | null;
};
export type ParseClausePreview = {
  id: number;
  chapter_title: string;
  clause_no: string;
  location_label: string;
  excerpt: string;
  text_len: number;
};
export type TaskParsePreview = {
  task_id: number;
  group_document_name: string;
  sub_document_name: string;
  group_clauses: ParseClausePreview[];
  sub_clauses: ParseClausePreview[];
};

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    const messages: Record<string, string> = {
      ERR_DOC_ENCRYPTED: "该文档处于加密保护，系统无法深度解析。请上传脱密版或可编辑版本。",
      ERR_DOC_CORRUPTED: "该文档可能已损坏，系统无法读取。请重新导出后上传。",
      ERR_DOC_EMPTY_OR_ENCRYPTED: "未能提取有效文字。请确认文件非空、未加密，或上传可编辑版本。",
      ERR_DOC_LOW_QUALITY: "文档 OCR 识别质量过低，系统已保留不确定区域，请上传更清晰版本后重试。",
      ERR_LLM_OOM: "当前本地算力服务器满载，任务已安全停止在当前步骤。请稍后从失败步骤继续。",
      ERR_LLM_TIMEOUT: "大模型多次响应超时，任务已安全停止在当前步骤。您可以稍后继续运行。",
      ERR_LLM_FAILED: "智能审查服务暂时不可用，任务已保留当前进度。请稍后重试。",
    };
    const code = Object.keys(messages).find((key) => detail.includes(key));
    return code ? messages[code] : detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const it = item as { msg: string; loc?: unknown[] };
          const field =
            Array.isArray(it.loc) && it.loc.length ? String(it.loc[it.loc.length - 1]) : "";
          return field ? `${field}: ${it.msg}` : String(it.msg);
        }
        return JSON.stringify(item);
      })
      .join("; ");
  }
  return JSON.stringify(detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, init);
  } catch (e) {
    throw new Error(
      `无法连接后端（${API}）。请确认已启动：uvicorn app.main:app --reload --port 8000。原始错误：${e}`
    );
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatErrorDetail((err as { detail?: unknown }).detail ?? res.statusText));
  }
  if (res.headers.get("content-type")?.includes("application/json")) {
    return res.json();
  }
  return res.text() as unknown as T;
}

export const api = {
  health: () => request<Health>("/health"),
  seed: () => request<{ message: string; task_id: number }>("/seed/demo", { method: "POST" }),
  dashboard: () => request<Dashboard>("/dashboard"),
  documents: () => request<Document[]>("/documents"),
  documentPreview: (id: number) => request<DocumentPreview>(`/documents/${id}/preview`),
  documentFileUrl: (id: number) => `${API}/documents/${id}/file`,
  uploadDocument: (form: FormData) =>
    request<Document>("/documents/upload", { method: "POST", body: form }),
  deleteDocument: (id: number) =>
    request<{ ok: boolean; message: string }>(`/documents/${id}`, { method: "DELETE" }),
  updateDocument: (id: number, body: { business_domain?: string; unit_name?: string; document_level?: string; version?: string }) =>
    request<Document>(`/documents/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  reparseDocument: (id: number) =>
    request<Document>(`/documents/${id}/reparse`, { method: "POST" }),
  aiReformatDocument: (id: number) =>
    request<DocumentPreview>(`/documents/${id}/ai-reformat`, { method: "POST" }),
  runSingleAuditBatch: (form: FormData) =>
    request<{
      submitted: number;
      total: number;
      max_parallel: number;
      tasks: Array<{ file: string; ok: boolean; task_id?: number; document_id?: number; task_name?: string; error?: string }>;
    }>("/single-audits/batch", { method: "POST", body: form }),
  tasks: () => request<Task[]>("/tasks"),
  deleteTask: (id: number) =>
    request<{ ok: boolean; message: string }>(`/tasks/${id}`, { method: "DELETE" }),
  task: (id: number) => request<Task>(`/tasks/${id}`),
  createTask: (body: object) =>
    request<Task>("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  runTask: (id: number, mode: "hybrid" | "fast" | "full" = "hybrid") =>
    request<{ message: string; mode: string; eta_hint: string; deprecated_notice?: string; degradation_notice?: string }>(
      `/tasks/${id}/run?mode=${mode}`,
      { method: "POST" }
    ),
  runtimeStatus: () => request<Record<string, unknown>>("/runtime/status"),
  taskExecution: (id: number) => request<Record<string, unknown>>(`/tasks/${id}/execution`),
  runSingleAudit: (body: { document_id: number; task_name?: string; business_domain?: string; mode?: string; template_id?: string }) =>
    request<Task>("/single-audits/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  diffs: (taskId: number, params?: Record<string, string>) => {
    const q = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<Difference[]>(`/tasks/${taskId}/diffs${q}`);
  },
  diff: (id: number) => request<DifferenceDetail>(`/diffs/${id}`),
  policyTemplates: (domain?: string) =>
    request<PolicyTemplateSummary[]>(`/policy-templates${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`),
  policyTemplate: (id: string) => request<PolicyTemplateDetail>(`/policy-templates/${encodeURIComponent(id)}`),
  reviewDiff: (id: number, action: string, comment: string) =>
    request<Difference>(`/diffs/${id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, comment }),
    }),
  createExemption: (id: number, body: { justification: string; policy_basis?: string; org_scope?: string; expires_at?: string | null }) =>
    request<Exemption>(`/diffs/${id}/exemptions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  exemptions: () => request<Exemption[]>("/exemptions"),
  approveExemption: (id: number) => request<Exemption>(`/exemptions/${id}/approve`, { method: "POST" }),
  revokeExemption: (id: number) => request<Exemption>(`/exemptions/${id}/revoke`, { method: "POST" }),
  createSupplement: (id: number, body: { assignee: string; requirement: string; due_at?: string | null }) =>
    request<Supplement>(`/diffs/${id}/supplements`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  supplements: () => request<Supplement[]>("/supplements"),
  submitSupplement: (id: number, submitted_text: string) =>
    request<Supplement>(`/supplements/${id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submitted_text }),
    }),
  reviews: () => request<ReviewLog[]>("/reviews"),
  undoReview: (logId: number) =>
    request<{ ok: boolean; difference_id: number }>(`/reviews/${logId}`, { method: "DELETE" }),
  pipelineLogs: (taskId: number) => request<PipelineLog[]>(`/tasks/${taskId}/pipeline/logs`),
  taskParsePreview: (taskId: number, limit = 20, excerptLen = 300) =>
    request<TaskParsePreview>(
      `/tasks/${taskId}/parse-preview?limit=${limit}&excerpt_len=${excerptLen}`
    ),
  exportUrl: (taskId: number, format: "xlsx" | "html") => `${API}/tasks/${taskId}/export?format=${format}`,
};

export function subscribePipeline(
  taskId: number,
  onEvent: (data: Record<string, unknown>) => void
): () => void {
  const es = new EventSource(`${API}/tasks/${taskId}/pipeline/stream`);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* ignore */
    }
  };
  // 不主动 close：避免短暂断连导致收不到后续事件；轮询作兜底
  return () => es.close();
}
