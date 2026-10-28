import { useCallback, useEffect, useState } from "react";
import {
  apiBase,
  deleteDocument,
  deleteRegion,
  listDocuments,
  listRegions,
  patchDocument,
  patchRegion,
  postKnowledgeIngest,
  postRegion,
  readApiError,
  uploadDocument,
} from "./api";

type DocumentRow = {
  id: string;
  doc_type: string;
  name: string;
  storage_relpath?: string;
  created_at: string;
};

type RegionMetaRow = {
  id: string;
  name: string;
  desc: string;
  created_at: string;
};

export function DocumentLibraryPage() {
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [regionRows, setRegionRows] = useState<RegionMetaRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingRegions, setLoadingRegions] = useState(false);
  const [hint, setHint] = useState<string>("");

  const [filterDocType, setFilterDocType] = useState("");
  const [limit, setLimit] = useState(50);

  const [upDocType, setUpDocType] = useState("law");
  const [upName, setUpName] = useState("");
  const [upFile, setUpFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [kbId, setKbId] = useState("default");
  const [vectorizingId, setVectorizingId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [savingRename, setSavingRename] = useState(false);

  const [metaId, setMetaId] = useState("");
  const [metaName, setMetaName] = useState("");
  const [metaDesc, setMetaDesc] = useState("");
  const [savingMeta, setSavingMeta] = useState(false);

  const loadRegions = useCallback(async () => {
    setLoadingRegions(true);
    try {
      const res = await listRegions();
      if (!res.ok) return;
      setRegionRows((await res.json()) as RegionMetaRow[]);
    } catch {
      /* ignore */
    } finally {
      setLoadingRegions(false);
    }
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    setHint("");
    try {
      const res = await listDocuments({
        doc_type: filterDocType.trim() || undefined,
        limit: Math.min(200, Math.max(1, Number(limit) || 50)),
      });
      if (!res.ok) {
        setHint(`列表加载失败：HTTP ${res.status}`);
        setRows([]);
        return;
      }
      setRows((await res.json()) as DocumentRow[]);
    } catch (e) {
      setHint(`列表加载异常：${String(e)}`);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [filterDocType, limit]);

  useEffect(() => {
    void loadRegions();
  }, [loadRegions]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const upload = async () => {
    if (!upFile) {
      setHint("请选择要上传的文件");
      return;
    }
    setUploading(true);
    setHint("");
    const fd = new FormData();
    fd.append("file", upFile);
    fd.append("doc_type", upDocType.trim() || "misc");
    if (upName.trim()) fd.append("name", upName.trim());
    try {
      const res = await uploadDocument(fd);
      if (!res.ok) {
        setHint(`上传失败：${await readApiError(res)}`);
        return;
      }
      setHint("上传成功（全局文档库，无 region 字段）");
      setUpFile(null);
      const input = document.getElementById("doc-lib-file") as HTMLInputElement | null;
      if (input) input.value = "";
      await loadList();
    } catch (e) {
      setHint(`上传异常：${String(e)}`);
    } finally {
      setUploading(false);
    }
  };

  const saveRegionMeta = async () => {
    const rid = metaId.trim();
    if (!rid) {
      setHint("请填写 region 的 id");
      return;
    }
    setSavingMeta(true);
    setHint("");
    try {
      let res = await postRegion({ id: rid, name: metaName, desc: metaDesc });
      if (res.status === 409) {
        res = await patchRegion(rid, { name: metaName, desc: metaDesc });
      }
      if (!res.ok) {
        setHint(`登记失败：${await readApiError(res)}`);
        return;
      }
      setHint(res.status === 201 ? "region 已创建" : "region 已更新");
      setMetaDesc("");
      await loadRegions();
    } catch (e) {
      setHint(`登记异常：${String(e)}`);
    } finally {
      setSavingMeta(false);
    }
  };

  const removeRegionMeta = async (regionId: string) => {
    if (!window.confirm(`删除 region「${regionId}」？（不影响已有文档）`)) return;
    setHint("");
    try {
      const res = await deleteRegion(regionId);
      if (!res.ok && res.status !== 204) {
        setHint(`删除失败：HTTP ${res.status}`);
        return;
      }
      await loadRegions();
    } catch (e) {
      setHint(`删除异常：${String(e)}`);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(`删除文档 ${id.slice(0, 8)}…？`)) return;
    setHint("");
    try {
      const res = await deleteDocument(id);
      if (!res.ok && res.status !== 204) {
        if (res.status === 409) {
          try {
            const j = (await res.json()) as {
              detail?: string | { message?: string; rule_count?: number };
            };
            const detail = j.detail;
            if (typeof detail === "string") {
              setHint(`删除失败：${detail}`);
            } else if (detail && typeof detail === "object") {
              const msg = detail.message?.trim();
              const count = detail.rule_count;
              if (msg) {
                setHint(`删除失败：${msg}`);
              } else if (count != null) {
                setHint(`删除失败：该文档已被 ${count} 条已发布规范引用，请先处理相关规范`);
              } else {
                setHint(`删除失败：${await readApiError(res)}`);
              }
            } else {
              setHint(`删除失败：${await readApiError(res)}`);
            }
          } catch {
            setHint(`删除失败：HTTP 409（文档仍被规范引用）`);
          }
        } else {
          setHint(`删除失败：${await readApiError(res)}`);
        }
        return;
      }
      setHint("已删除");
      await loadList();
    } catch (e) {
      setHint(`删除异常：${String(e)}`);
    }
  };

  const downloadHref = (id: string) =>
    `${apiBase()}/api/document/${encodeURIComponent(id)}/download`;

  const startRename = (row: DocumentRow) => {
    setRenamingId(row.id);
    setRenameDraft(row.name);
  };

  const cancelRename = () => {
    setRenamingId(null);
    setRenameDraft("");
  };

  const saveRename = async () => {
    const id = renamingId;
    const name = renameDraft.trim();
    if (!id || !name) {
      setHint("展示名不能为空");
      return;
    }
    setSavingRename(true);
    setHint("");
    try {
      const res = await patchDocument(id, { name });
      if (!res.ok) {
        setHint(`重命名失败：${await readApiError(res)}`);
        return;
      }
      setHint("文档名称已更新");
      cancelRename();
      await loadList();
    } catch (e) {
      setHint(`重命名异常：${String(e)}`);
    } finally {
      setSavingRename(false);
    }
  };

  const vectorize = async (documentId: string, documentName: string) => {
    setVectorizingId(documentId);
    setHint(`向量化中：${documentName}…`);
    try {
      const res = await postKnowledgeIngest({
        document_id: documentId,
        kb_id: kbId.trim() || "default",
        replace: true,
      });
      if (!res.ok) {
        setHint(`向量化失败：${await readApiError(res)}`);
        return;
      }
      const out = (await res.json()) as { chunks?: number };
      setHint(`向量化成功：${documentName}，分块 ${out.chunks ?? "?"} 条`);
    } catch (e) {
      setHint(`向量化异常：${String(e)}`);
    } finally {
      setVectorizingId(null);
    }
  };

  return (
    <div className="main">
      <div className="toolbar doc-lib-toolbar">
        <span className="doc-lib-toolbar-title">文档库调试</span>
        <button type="button" className="doc-lib-btn-ghost doc-lib-toolbar-refresh" onClick={() => void loadList()} disabled={loading}>
          刷新列表
        </button>
        <button type="button" className="doc-lib-btn-ghost" onClick={() => void loadRegions()} disabled={loadingRegions}>
          刷新 region 表
        </button>
      </div>

      <div className="doc-lib-page">
        <p className="doc-lib-banner">
          <strong>document</strong> 为<strong>全局</strong>文档库（无 <code>region_id</code>）；<strong>region</strong>{" "}
          独立存于 <code>data/region.db</code>，供设备与巡检业务使用。向量化请用{" "}
          <code>POST /api/knowledge/ingest</code>（<code>document_id</code> + <code>kb_id</code>）。
        </p>

        {hint ? <p className="doc-lib-hint">{hint}</p> : null}

        <section className="doc-lib-panel">
          <h2>region 登记</h2>
          <p className="doc-lib-muted doc-lib-tight-top">
            区域字典与文档库分离；设备绑定 <code>region_id</code> 后，巡检业务由设备推导区域。
          </p>
          <div className="doc-lib-form-row doc-lib-meta-form">
            <label>
              id
              <input value={metaId} onChange={(e) => setMetaId(e.target.value)} placeholder="region 主键 id" />
            </label>
            <label>
              name
              <input value={metaName} onChange={(e) => setMetaName(e.target.value)} placeholder="展示名" />
            </label>
            <label className="doc-lib-label-grow">
              desc
              <input value={metaDesc} onChange={(e) => setMetaDesc(e.target.value)} placeholder="职责 / 说明" />
            </label>
            <button type="button" className="doc-lib-btn-inline" disabled={savingMeta} onClick={() => void saveRegionMeta()}>
              {savingMeta ? "保存中…" : "登记 / 更新"}
            </button>
          </div>
          {loadingRegions ? (
            <p className="doc-lib-muted">加载中…</p>
          ) : regionRows.length === 0 ? (
            <p className="doc-lib-muted">暂无登记</p>
          ) : (
            <table className="doc-lib-table doc-lib-table-compact">
              <thead>
                <tr>
                  <th>id</th>
                  <th>name</th>
                  <th>desc</th>
                  <th>created_at</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {regionRows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <code className="doc-lib-code">{r.id}</code>
                    </td>
                    <td>{r.name || "—"}</td>
                    <td>{r.desc || "—"}</td>
                    <td className="doc-lib-muted">{r.created_at}</td>
                    <td className="doc-lib-actions">
                      <button type="button" className="doc-lib-btn-danger" onClick={() => void removeRegionMeta(r.id)}>
                        删除登记
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="doc-lib-panel">
          <h2>上传</h2>
          <div className="doc-lib-form-grid">
            <label>
              文件
              <input id="doc-lib-file" type="file" onChange={(e) => setUpFile(e.target.files?.[0] ?? null)} />
            </label>
            <label>
              doc_type
              <input value={upDocType} onChange={(e) => setUpDocType(e.target.value)} placeholder="law" />
            </label>
            <label>
              展示名（可选）
              <input value={upName} onChange={(e) => setUpName(e.target.value)} placeholder="默认用文件名" />
            </label>
          </div>
          <button type="button" disabled={uploading} onClick={() => void upload()}>
            {uploading ? "上传中…" : "上传"}
          </button>
        </section>

        <section className="doc-lib-panel">
          <h2>列表筛选</h2>
          <div className="doc-lib-form-row">
            <span className="doc-lib-label">doc_type</span>
            <input value={filterDocType} onChange={(e) => setFilterDocType(e.target.value)} placeholder="可选" />
            <span className="doc-lib-label">limit</span>
            <input type="number" min={1} max={200} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
            <span className="doc-lib-label">kb_id（向量化）</span>
            <input value={kbId} onChange={(e) => setKbId(e.target.value)} placeholder="default" />
          </div>
        </section>

        <section className="doc-lib-table-wrap">
          {loading ? <p className="doc-lib-muted">加载中…</p> : null}
          {!loading && rows.length === 0 ? <p className="doc-lib-muted">暂无数据</p> : null}
          {!loading && rows.length > 0 ? (
            <table className="doc-lib-table">
              <thead>
                <tr>
                  <th>name</th>
                  <th>doc_type</th>
                  <th>created_at</th>
                  <th>id</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="doc-lib-td-name">
                      {renamingId === r.id ? (
                        <div className="doc-lib-rename-row">
                          <input
                            value={renameDraft}
                            onChange={(e) => setRenameDraft(e.target.value)}
                            placeholder="展示名"
                          />
                          <button type="button" disabled={savingRename} onClick={() => void saveRename()}>
                            {savingRename ? "保存中…" : "保存"}
                          </button>
                          <button type="button" className="doc-lib-btn-ghost" disabled={savingRename} onClick={cancelRename}>
                            取消
                          </button>
                        </div>
                      ) : (
                        r.name
                      )}
                    </td>
                    <td>{r.doc_type}</td>
                    <td className="doc-lib-muted">{r.created_at}</td>
                    <td>
                      <code className="doc-lib-code-sm">{r.id}</code>
                    </td>
                    <td className="doc-lib-actions">
                      <button type="button" disabled={renamingId === r.id} onClick={() => startRename(r)}>
                        重命名
                      </button>
                      <button
                        type="button"
                        disabled={vectorizingId === r.id || renamingId === r.id}
                        onClick={() => void vectorize(r.id, r.name)}
                      >
                        {vectorizingId === r.id ? "向量化中…" : "向量化"}
                      </button>
                      <a href={downloadHref(r.id)} target="_blank" rel="noreferrer">
                        下载
                      </a>
                      <button type="button" className="doc-lib-btn-danger" onClick={() => void remove(r.id)}>
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      </div>
    </div>
  );
}
