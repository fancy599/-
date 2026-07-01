import { useEffect, useRef, useState } from "react";
import { api, type DocumentPreview } from "../api/client";

type Props = {
  documentId: number | null;
  onClose: () => void;
};

export default function DocumentPreviewModal({ documentId, onClose }: Props) {
  const [data, setData] = useState<DocumentPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"text" | "file">("text");
  const currentIdRef = useRef<number | null>(documentId);

  useEffect(() => {
    currentIdRef.current = documentId;
    setData(null);
    setErr("");
    setTab("text");
    if (!documentId) return;
    setLoading(true);
    api
      .documentPreview(documentId)
      .then((d) => {
        if (currentIdRef.current === documentId) setData(d);
      })
      .catch((e) => {
        if (currentIdRef.current === documentId) setErr(String(e));
      })
      .finally(() => {
        if (currentIdRef.current === documentId) setLoading(false);
      });
  }, [documentId]);

  if (!documentId) return null;

  const fileUrl = api.documentFileUrl(documentId);

  return (
    <div className="modal-mask show" onClick={onClose}>
      <div className="modal preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-hd">
          <div>
            <strong>{data?.document_name || "制度预览"}</strong>
            {data && (
              <p className="modal-sub">
                {data.unit_name} · {data.document_level === "group" ? "集团" : "子公司"}
                {data.version ? ` · ${data.version}` : ""}
                {data.clause_count > 0 ? ` · ${data.clause_count} 条条款` : ""}
              </p>
            )}
          </div>
          <button type="button" className="ghost" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="modal-tabs">
          <button type="button" className={tab === "text" ? "active" : ""} onClick={() => setTab("text")}>
            文本内容
          </button>
          {data?.has_original_file && data.file_ext === "pdf" && (
            <button type="button" className={tab === "file" ? "active" : ""} onClick={() => setTab("file")}>
              原始文件
            </button>
          )}
          <div className="modal-tabs-right">
            {data?.has_original_file && (
              <a href={fileUrl} target="_blank" rel="noreferrer" className="modal-link">
                新窗口打开
              </a>
            )}
          </div>
        </div>
        <div className="modal-bd">
          {loading && <p>加载中…</p>}
          {err && <p className="upload-err">{err}</p>}
          {!loading && !err && data?.table_review_required && (
            <div className="alert warn">
              <strong>检测到复杂表格，需要人工确认</strong>
              <div>可能涉及页码：{data.complex_table_pages}。请结合原始页面确认表格内容。</div>
              <div className="flex">
                {data.complex_table_pages.split(",").filter(Boolean).slice(0, 3).map((page) => (
                  <a key={page} href={`/api/documents/${data.id}/table-snapshot?page=${page}`} target="_blank" rel="noreferrer">
                    查看第 {page} 页原始快照
                  </a>
                ))}
              </div>
            </div>
          )}
          {!loading && !err && data && tab === "text" && (
            <pre className="preview-text">{data.text_content || "（无文本内容）"}</pre>
          )}
          {!loading && !err && data && tab === "file" && data.file_ext === "pdf" && (
            <iframe className="preview-iframe" title="原始文件预览" src={fileUrl} />
          )}
        </div>
      </div>
    </div>
  );
}
