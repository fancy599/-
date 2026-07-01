import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import DocumentPreviewModal from "../components/DocumentPreviewModal";
import StatCards from "../components/StatCards";
import { api, STANDARD_CONTROL_DOMAINS, type Document } from "../api/client";

const DOMAIN_RULES: Array<[RegExp, string]> = [
  [/用车|公车|车辆|班车/, "用车管理"],
  [/固定资产|资产/, "资产"],
  [/采购|招标|供应商|询价|招投标/, "采购"],
  [/资金|付款|融资|借款|账户|资金活动/, "资金活动"],
  [/报销|差旅|费用|财务报告|会计|报表/, "财务报告"],
  [/预算/, "全面预算"],
  [/合同/, "合同管理"],
  [/担保/, "担保业务"],
  [/外包/, "业务外包"],
  [/销售|收入|回款/, "销售"],
  [/工程|项目|基建/, "工程项目"],
  [/信息|系统|网络|数据|保密/, "信息系统"],
  [/人事|人力|招聘|薪酬|绩效|培训/, "人力资源"],
  [/三重一大|决策|议事|组织|架构|治理|党委|董事会/, "组织架构"],
  [/战略|发展规划/, "发展战略"],
  [/研发|研究|开发/, "研究与开发"],
  [/文化/, "企业文化"],
  [/社会责任|环保|安全生产/, "社会责任"],
];

// 根据制度名称自动识别业务领域（命中不到默认采购）。
function inferDomain(name: string): string {
  for (const [re, domain] of DOMAIN_RULES) {
    if (re.test(name)) return domain;
  }
  return "采购";
}

export default function Library() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [docName, setDocName] = useState("");
  const [unitName, setUnitName] = useState("");
  const [level, setLevel] = useState("group");
  const [domain, setDomain] = useState("__auto__");
  const [version, setVersion] = useState("");
  const [msg, setMsg] = useState("");
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [levelFilter, setLevelFilter] = useState<"all" | "group" | "subsidiary">("all");
  const [unitFilter, setUnitFilter] = useState<string>("all");
  const [savingId, setSavingId] = useState<number | null>(null);

  function load() {
    api.documents().then(setDocs).catch((e) => setMsg(String(e)));
  }

  useEffect(() => {
    load();
  }, []);

  async function uploadAll(e: React.FormEvent) {
    e.preventDefault();
    if (!files.length) {
      setMsg("请选择文件");
      return;
    }
    if (files.length > 30) {
      setMsg("一次最多上传 30 份，请分批处理");
      return;
    }
    const single = files.length === 1;
    setUploading(true);
    let done = 0;
    let ok = 0;
    const failed: string[] = [];
    let cursor = 0;

    async function worker() {
      while (cursor < files.length) {
        const f = files[cursor++];
        const baseName = f.name.replace(/\.[^.]+$/, "");
        const name = single && docName.trim() ? docName.trim() : baseName;
        const dom = domain === "__auto__" ? inferDomain(baseName) : domain;
        const fd = new FormData();
        fd.append("file", f);
        fd.append("document_name", name);
        fd.append("unit_name", unitName.trim());
        fd.append("document_level", level);
        fd.append("business_domain", dom);
        fd.append("version", single ? version : "");
        try {
          await api.uploadDocument(fd);
          ok += 1;
        } catch (err) {
          const reason = err instanceof Error ? err.message : String(err);
          failed.push(`${baseName}：${reason}`);
        }
        done += 1;
        setMsg(`上传中… 已完成 ${done}/${files.length}`);
      }
    }

    const concurrency = Math.min(3, files.length);
    await Promise.all(Array.from({ length: concurrency }, () => worker()));

    setUploading(false);
    setFiles([]);
    setDocName("");
    setVersion("");
    setMsg(
      `上传完成：成功 ${ok} 份` +
        (failed.length ? `；失败 ${failed.length} 份 —— ${failed.join("；")}` : "")
    );
    load();
  }

  async function removeDoc(doc: Document) {
    if (!window.confirm(`确定删除制度「${doc.document_name}」？\n若已被审查任务引用，需先删除相关任务。`)) {
      return;
    }
    setDeletingId(doc.id);
    setMsg("");
    try {
      await api.deleteDocument(doc.id);
      setMsg("制度已删除");
      load();
    } catch (err) {
      setMsg(String(err));
    } finally {
      setDeletingId(null);
    }
  }

  async function patchDoc(
    doc: Document,
    patch: { business_domain?: string; unit_name?: string; document_level?: string; version?: string }
  ) {
    setSavingId(doc.id);
    try {
      await api.updateDocument(doc.id, patch);
      setDocs((prev) => prev.map((x) => (x.id === doc.id ? { ...x, ...patch } : x)));
    } catch (err) {
      setMsg(String(err));
    } finally {
      setSavingId(null);
    }
  }

  const groupCount = docs.filter((d) => d.document_level === "group").length;
  const subCount = docs.filter((d) => d.document_level === "subsidiary").length;
  const parsedCount = docs.filter((d) => d.parse_status === "parsed").length;
  const units = Array.from(new Set(docs.map((d) => d.unit_name).filter(Boolean)));
  const visibleDocs = docs.filter(
    (d) =>
      (levelFilter === "all" || d.document_level === levelFilter) &&
      (unitFilter === "all" || d.unit_name === unitFilter)
  );
  const statusLabel = (d: Document) => {
    if (d.lock_status === "locked") return "审查中锁定";
    if (d.parse_status === "parsed") return "已解析";
    if (d.parse_status === "low_quality_text") return "OCR质量低";
    if (d.parse_status === "parse_failed") return "解析失败";
    return d.parse_status;
  };

  return (
    <>
      <header className="topbar">
        <div>
          <h1>制度文件</h1>
          <p>集中管理集团和子公司的制度，方便随时预览、检查和复用。</p>
        </div>
        <Link to="/tasks/new">
          <button className="primary" type="button">发起制度检查</button>
        </Link>
      </header>
      <div className="content">
        {msg && <div className={`alert ${msg.includes("成功") ? "info" : "warn"}`}>{msg}</div>}

        <StatCards
          items={[
            { label: "制度总数", value: docs.length },
            { label: "集团制度", value: groupCount },
            { label: "子公司制度", value: subCount },
            { label: "已解析", value: parsedCount, tone: parsedCount === docs.length && docs.length > 0 ? "ok" : "default" },
          ]}
        />

        <div className="panel">
          <div className="panel-hd">
            <strong>上传制度</strong>
            <span className="panel-hd-sub">上传后自动解析入库，发起检查时可重复使用</span>
          </div>
          <div className="panel-bd">
            <form onSubmit={uploadAll}>
              <div className="form-row">
                <label>选择制度文件（可多选，支持 .pdf / .doc / .docx / .txt）</label>
                <input
                  type="file"
                  multiple
                  accept=".pdf,.doc,.docx,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                  disabled={uploading}
                  onChange={(e) => {
                    const fs = e.target.files ? Array.from(e.target.files) : [];
                    setFiles(fs);
                    if (fs.length === 1 && !docName) setDocName(fs[0].name.replace(/\.[^.]+$/, ""));
                  }}
                />
              </div>
              <div className="form-grid">
                {files.length === 1 && (
                  <div className="form-row">
                    <label>制度名称</label>
                    <input value={docName} onChange={(e) => setDocName(e.target.value)} placeholder="默认识别文件名" />
                  </div>
                )}
                <div className="form-row">
                  <label>所属单位{files.length > 1 ? "（统一，可选）" : ""}</label>
                  <input value={unitName} onChange={(e) => setUnitName(e.target.value)} placeholder="留空则不填" />
                </div>
                <div className="form-row">
                  <label>级别</label>
                  <select value={level} onChange={(e) => setLevel(e.target.value)}>
                    <option value="group">集团</option>
                    <option value="subsidiary">子公司</option>
                  </select>
                </div>
                <div className="form-row">
                  <label>业务领域</label>
                  <select value={domain} onChange={(e) => setDomain(e.target.value)}>
                    <option value="__auto__">按文件名自动识别</option>
                    {STANDARD_CONTROL_DOMAINS.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                {files.length === 1 && (
                  <div className="form-row">
                    <label>版本号</label>
                    <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="如 2026.03 版" />
                  </div>
                )}
              </div>
              {files.length > 1 && (
                <p className="panel-tip" style={{ marginTop: 0 }}>
                  已选 {files.length} 份：制度名称取文件名；业务领域
                  {domain === "__auto__" ? "按文件名自动识别" : `统一为「${domain}」`}。
                </p>
              )}
              <button className="primary" type="submit" disabled={uploading}>
                {uploading ? "上传解析中…" : files.length > 1 ? `上传并解析（${files.length} 份）` : "上传并解析"}
              </button>
            </form>
          </div>
        </div>

        <div className="panel">
          <div className="panel-hd">
            <strong>制度列表</strong>
            <div className="list-filters">
              <select className="unit-filter" value={unitFilter} onChange={(e) => setUnitFilter(e.target.value)}>
                <option value="all">全部单位</option>
                {units.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
              <div className="seg">
                <button type="button" className={levelFilter === "all" ? "active" : ""} onClick={() => setLevelFilter("all")}>
                  全部 {docs.length}
                </button>
                <button type="button" className={levelFilter === "group" ? "active" : ""} onClick={() => setLevelFilter("group")}>
                  集团 {groupCount}
                </button>
                <button type="button" className={levelFilter === "subsidiary" ? "active" : ""} onClick={() => setLevelFilter("subsidiary")}>
                  子公司 {subCount}
                </button>
              </div>
            </div>
          </div>
          <div className="panel-bd" style={{ padding: 0 }}>
            <div className="table-scroll">
              <table className="table doc-table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>单位</th>
                    <th>级别</th>
                    <th>业务领域</th>
                    <th>状态</th>
                    <th style={{ width: 208 }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleDocs.map((d) => (
                    <tr key={d.id}>
                      <td><strong>{d.document_name}</strong></td>
                      <td>
                        <input
                          className="cell-input"
                          defaultValue={d.unit_name}
                          disabled={savingId === d.id}
                          placeholder="留空则不填"
                          onBlur={(e) => {
                            const v = e.target.value.trim();
                            if (v !== (d.unit_name || "")) patchDoc(d, { unit_name: v });
                          }}
                        />
                      </td>
                      <td>
                        <select
                          className="cell-select"
                          value={d.document_level}
                          disabled={savingId === d.id}
                          onChange={(e) => patchDoc(d, { document_level: e.target.value })}
                        >
                          <option value="group">集团</option>
                          <option value="subsidiary">子公司</option>
                        </select>
                      </td>
                      <td>
                        <select
                          className="cell-select"
                          value={d.business_domain || "采购"}
                          disabled={savingId === d.id}
                          onChange={(e) => patchDoc(d, { business_domain: e.target.value })}
                        >
                          {STANDARD_CONTROL_DOMAINS.map((dm) => (
                            <option key={dm} value={dm}>{dm}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <span className={`pill ${d.parse_status === "parsed" ? "ok" : d.parse_status === "low_quality_text" ? "amber" : "gray"}`}>
                          {statusLabel(d)}
                        </span>
                        {d.degradation_notes && <div className="table-note">{d.degradation_notes}</div>}
                        {d.table_review_required && (
                          <div className="table-review-warning">
                            <strong>需人工核验复杂表格</strong>
                            <div>疑似权责矩阵页：{d.complex_table_pages}</div>
                            <div className="flex">
                              {d.complex_table_pages.split(",").filter(Boolean).slice(0, 3).map((page) => (
                                <a key={page} href={`/api/documents/${d.id}/table-snapshot?page=${page}`} target="_blank" rel="noreferrer">
                                  查看第 {page} 页快照
                                </a>
                              ))}
                            </div>
                            <div>建议重新上传排版清晰的文件，或结合原始页面人工确认判断结果。</div>
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="row-actions">
                          <button className="ghost sm" type="button" onClick={() => setPreviewId(d.id)}>
                            预览
                          </button>
                          <button
                            className="ghost sm"
                            type="button"
                            disabled={deletingId === d.id}
                            onClick={() => removeDoc(d)}
                          >
                            {deletingId === d.id ? "删除中" : "删除"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visibleDocs.length === 0 && (
              <p style={{ color: "var(--muted)", padding: 18 }}>
                {docs.length === 0 ? "暂无制度，请先上传" : "当前筛选下没有制度"}
              </p>
            )}
          </div>
        </div>
      </div>
      <DocumentPreviewModal documentId={previewId} onClose={() => setPreviewId(null)} />
    </>
  );
}
