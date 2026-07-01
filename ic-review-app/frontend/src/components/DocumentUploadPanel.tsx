import { useState } from "react";
import { api, STANDARD_CONTROL_DOMAINS, type Document } from "../api/client";

type Props = {
  documentLevel: "group" | "subsidiary";
  title: string;
  onUploaded: (doc: Document) => void;
  /** 内嵌模式：不显示自身的展开按钮，直接渲染上传表单（用于已经分好区的页面）。 */
  embedded?: boolean;
};

const defaults = {
  group: { unit_name: "集团总部", document_name: "" },
  subsidiary: { unit_name: "子公司", document_name: "" },
};

export default function DocumentUploadPanel({ documentLevel, title, onUploaded, embedded = false }: Props) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [unitName, setUnitName] = useState(defaults[documentLevel].unit_name);
  const [docName, setDocName] = useState("");
  const [version, setVersion] = useState("");
  const [businessDomain, setBusinessDomain] = useState("采购");
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setErr("请选择文件");
      return;
    }
    const name = docName.trim() || file.name.replace(/\.[^.]+$/, "");
    setUploading(true);
    setErr("");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("document_name", name);
    fd.append("unit_name", unitName);
    fd.append("document_level", documentLevel);
    fd.append("business_domain", businessDomain);
    fd.append("version", version);
    try {
      const doc = await api.uploadDocument(fd);
      onUploaded(doc);
      setOpen(false);
      setFile(null);
      setDocName("");
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="upload-panel">
      {!embedded && (
        <button type="button" className="ghost" onClick={() => setOpen(!open)}>
          {open ? "收起" : title}
        </button>
      )}
      {(embedded || open) && (
        <form className="upload-panel-form" onSubmit={handleUpload}>
          <div className="form-row">
            <label>选择文件（支持 .pdf / .doc / .docx，兼容 .txt）</label>
            <input
              type="file"
              accept=".pdf,.doc,.docx,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              onChange={(e) => {
                const f = e.target.files?.[0] || null;
                setFile(f);
                if (f && !docName) setDocName(f.name.replace(/\.[^.]+$/, ""));
              }}
            />
          </div>
          <div className="form-row">
            <label>制度名称</label>
            <input value={docName} onChange={(e) => setDocName(e.target.value)} placeholder="默认识别文件名" />
          </div>
          <div className="form-row">
            <label>所属单位</label>
            <input value={unitName} onChange={(e) => setUnitName(e.target.value)} required />
          </div>
          <div className="form-row">
            <label>业务领域</label>
            <select value={businessDomain} onChange={(e) => setBusinessDomain(e.target.value)}>
              {STANDARD_CONTROL_DOMAINS.map((domain) => (
                <option key={domain} value={domain}>{domain}</option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label>版本号</label>
            <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="如 V2026.03" />
          </div>
          {err && <p className="upload-err">{err}</p>}
          <button className="primary" type="submit" disabled={uploading}>
            {uploading ? "上传解析中…" : "上传并加入制度库"}
          </button>
        </form>
      )}
    </div>
  );
}
