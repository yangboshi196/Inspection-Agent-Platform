import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link, useMatch, useNavigate, useSearchParams } from "react-router-dom";
import { patchRegion, postRegion, readApiError } from "../../api";
import { loadRegions, type RegionRow } from "../regionApi";
import {
  buildRegionTree,
  flattenRegionTree,
  parentRegionName,
  type RegionTreeNode,
} from "../regionTree";
import { resolveInitialParentId, suggestSortOrder } from "./regionCreateUtils";

function regionBreadcrumb(regions: RegionRow[], parentId: string, leafName?: string): string[] {
  const parts: string[] = [];
  let pid = parentId.trim();
  const guard = new Set<string>();
  while (pid && !guard.has(pid)) {
    guard.add(pid);
    const row = regions.find((r) => r.id === pid);
    if (!row) break;
    parts.unshift(row.name);
    pid = (row.parent_id ?? "").trim();
  }
  if (leafName?.trim()) parts.push(leafName.trim());
  return parts;
}

export function RegionDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isNew = !!useMatch("/admin/regions/new");
  const editMatch = useMatch("/admin/regions/:regionId/edit");
  const regionId = editMatch?.params.regionId;

  const [regions, setRegions] = useState<RegionRow[]>([]);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [parentId, setParentId] = useState("");
  const [sortOrder, setSortOrder] = useState(0);
  const [parentKw, setParentKw] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const regionTree = useMemo(() => buildRegionTree(regions, () => 0), [regions]);
  const flatRegions = useMemo(() => flattenRegionTree(regionTree), [regionTree]);

  const parentOptions = useMemo(() => {
    const exclude = new Set<string>();
    if (!isNew && regionId) {
      const node = flatRegions.find((n) => n.id === regionId);
      if (node) {
        const walk = (n: RegionTreeNode) => {
          exclude.add(n.id);
          for (const c of n.children) walk(c);
        };
        walk(node);
      }
    }
    const draftId = code.trim();
    if (draftId) exclude.add(draftId);
    return flatRegions.filter((r) => !exclude.has(r.id));
  }, [flatRegions, isNew, regionId, code]);

  const parentKwNorm = parentKw.trim().toLowerCase();
  const showTopLevelParentOption =
    !parentKwNorm ||
    ["顶级", "无上级", "根", "top", "root"].some((k) => k.includes(parentKwNorm) || parentKwNorm.includes(k));

  const filteredParentOptions = useMemo(() => {
    if (!parentKwNorm) return parentOptions;
    return parentOptions.filter(
      (n) =>
        n.name.toLowerCase().includes(parentKwNorm) ||
        n.id.toLowerCase().includes(parentKwNorm) ||
        parentRegionName(regions, n.parent_id).toLowerCase().includes(parentKwNorm),
    );
  }, [parentOptions, parentKwNorm, regions]);

  const breadcrumb = useMemo(
    () => regionBreadcrumb(regions, parentId, name),
    [regions, parentId, name],
  );

  const selectedParent = parentId ? parentOptions.find((n) => n.id === parentId) : null;

  const canSave =
    name.trim().length > 0 && code.trim().length > 0 && description.trim().length > 0 && !saving;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const loadedRegions = await loadRegions();
        if (cancelled) return;
        setRegions(loadedRegions);
        if (isNew) {
          const initialParent = resolveInitialParentId(searchParams.get("parent"), loadedRegions);
          setParentId(initialParent);
          setSortOrder(suggestSortOrder(initialParent, loadedRegions));
          return;
        }
        const base = loadedRegions.find((r) => r.id === regionId);
        if (!base) {
          setError("区域不存在");
          return;
        }
        setName(base.name);
        setCode(base.id);
        setDescription(base.desc ?? "");
        setParentId(base.parent_id ?? "");
        setSortOrder(base.sort_order ?? 0);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isNew, regionId, searchParams]);

  // 新建时切换上级区域，自动建议同级排序（避免与已有兄弟节点冲突）
  useEffect(() => {
    if (!isNew || loading || regions.length === 0) return;
    setSortOrder(suggestSortOrder(parentId, regions));
  }, [isNew, loading, parentId, regions]);

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    setError("");
    try {
      const rid = code.trim();
      if (isNew) {
        const res = await postRegion({
          id: rid,
          name: name.trim(),
          desc: description,
          parent_id: parentId,
          sort_order: sortOrder,
        });
        if (!res.ok) throw new Error(await readApiError(res));
      } else {
        const res = await patchRegion(regionId!, {
          name: name.trim(),
          desc: description,
          parent_id: parentId,
          sort_order: sortOrder,
        });
        if (!res.ok) throw new Error(await readApiError(res));
      }
      navigate("/admin/regions", { state: { region: rid } });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="pf-scroll pf-region-editor-page">
      <div className="pf-region-editor-shell">
        <header className={`pf-region-editor-hero${isNew ? " is-new" : " is-edit"}`}>
          <div className="pf-region-editor-hero-top">
            <Link to="/admin/regions" className="pf-region-editor-back">
              <span aria-hidden>←</span> 返回区域配置
            </Link>
            <span className={`pf-region-editor-mode${isNew ? " is-new" : " is-edit"}`}>
              {isNew ? "新建" : "编辑"}
            </span>
          </div>
          <div className="pf-region-editor-hero-main">
            <h1>{isNew ? "新建区域" : "编辑区域"}</h1>
            <p className="pf-region-editor-hero-desc">
              {isNew
                ? "填写区域编号、名称与上级归属；若在列表中已选中某区域再点「新建」，将自动作为其子区域。"
                : "修改区域名称、上级归属与排序，编号创建后不可变更。"}
            </p>
            {breadcrumb.length > 0 ? (
              <nav className="pf-region-editor-path" aria-label="层级路径预览">
                {breadcrumb.map((part, i) => (
                  <span key={`${part}-${i}`} className="pf-region-editor-path-item">
                    {i > 0 ? <span className="pf-region-editor-path-sep" aria-hidden>/</span> : null}
                    <span className={i === breadcrumb.length - 1 ? "is-leaf" : undefined}>{part}</span>
                  </span>
                ))}
              </nav>
            ) : isNew && !parentId ? (
              <p className="pf-region-editor-hero-desc">将创建为<strong>顶级区域</strong>（无上级）。</p>
            ) : null}
            {!isNew && regionId ? (
              <div className="pf-region-editor-id-chip">
                <span>区域编号</span>
                <code>{regionId}</code>
              </div>
            ) : null}
          </div>
        </header>

        {error ? <div className="pf-region-editor-alert">{error}</div> : null}

        {loading ? (
          <div className="pf-region-editor-loading">
            <span className="pf-region-editor-loading-dot" />
            加载区域数据…
          </div>
        ) : (
          <div className="pf-region-editor-body">
            <section className="pf-region-editor-section">
              <header className="pf-region-editor-section-head">
                <span className="pf-region-editor-step">1</span>
                <div>
                  <h2>基本信息</h2>
                  <p>区域编号全局唯一；名称与描述说明为必填，将展示在区域树与设备归属中。</p>
                </div>
              </header>
              <div className="pf-region-editor-fields">
                <label className="pf-region-editor-field pf-region-editor-field-wide">
                  <span>区域名称</span>
                  <input
                    className="pf-region-editor-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="如 A座大堂与公区"
                    autoFocus={isNew}
                  />
                </label>
                <label className="pf-region-editor-field">
                  <span>区域编号</span>
                  <input
                    className="pf-region-editor-input"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="如 r5"
                    disabled={!isNew}
                  />
                  <em>{isNew ? "全局唯一，建议 r 前缀" : "不可修改"}</em>
                </label>
                <label className="pf-region-editor-field">
                  <span>同级排序</span>
                  <input
                    className="pf-region-editor-input"
                    type="number"
                    value={sortOrder}
                    onChange={(e) => setSortOrder(Number(e.target.value) || 0)}
                  />
                  <em>数值越小越靠前</em>
                </label>
                <label className="pf-region-editor-field pf-region-editor-field-wide">
                  <span>描述说明（必填）</span>
                  <textarea
                    className="pf-region-editor-input pf-region-editor-textarea"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="区域位置、关联业务说明等（必填）"
                    rows={3}
                    required
                  />
                </label>
              </div>
            </section>

            <section className="pf-region-editor-section">
              <header className="pf-region-editor-section-head">
                <span className="pf-region-editor-step">2</span>
                <div>
                  <h2>上级区域</h2>
                  <p>选择父级节点构成树形结构；选「顶级区域」则 parent_id 为空。</p>
                </div>
              </header>
              {parentId === "" ? (
                <div className="pf-region-editor-parent-current">
                  <span className="pf-region-editor-parent-current-label">当前选中</span>
                  <strong>顶级区域</strong>
                  <span>（无上级）</span>
                </div>
              ) : selectedParent ? (
                <div className="pf-region-editor-parent-current">
                  <span className="pf-region-editor-parent-current-label">当前选中</span>
                  <strong>{selectedParent.name}</strong>
                  <code>{selectedParent.id}</code>
                </div>
              ) : null}
              <input
                type="search"
                className="pf-region-editor-input pf-region-editor-parent-search"
                placeholder="搜索上级区域名称或编号…"
                value={parentKw}
                onChange={(e) => setParentKw(e.target.value)}
              />
              <ul className="pf-region-editor-parent-list" role="listbox" aria-label="上级区域">
                {showTopLevelParentOption ? (
                  <li>
                    <button
                      type="button"
                      role="option"
                      aria-selected={parentId === ""}
                      className={`pf-region-editor-parent-item${parentId === "" ? " is-active" : ""}`}
                      style={{ "--pf-region-depth": 0 } as CSSProperties}
                      onClick={() => setParentId("")}
                    >
                      <span className="pf-region-editor-parent-radio" aria-hidden />
                      <span className="pf-region-editor-parent-level">顶级</span>
                      <span className="pf-region-editor-parent-name">无上级（顶级区域）</span>
                    </button>
                  </li>
                ) : null}
                {filteredParentOptions.length === 0 && !showTopLevelParentOption ? (
                  <li className="pf-region-editor-parent-empty">暂无匹配区域</li>
                ) : (
                  filteredParentOptions.map((node) => {
                    const active = parentId === node.id;
                    return (
                      <li key={node.id}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={active}
                          className={`pf-region-editor-parent-item${active ? " is-active" : ""}`}
                          style={{ "--pf-region-depth": node.depth } as CSSProperties}
                          onClick={() => setParentId(node.id)}
                        >
                          <span className="pf-region-editor-parent-radio" aria-hidden />
                          <span className="pf-region-editor-parent-level">
                            {node.depth === 0 ? "顶级" : `${node.depth} 级`}
                          </span>
                          <span className="pf-region-editor-parent-name">{node.name}</span>
                          <code>{node.id}</code>
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            </section>

            <aside className="pf-region-editor-tips">
              <h3>提示</h3>
              <ul>
                <li>设备请在「区域配置 → 导入设备」中按 region_id 归属。</li>
                <li>子区域统计会包含下级设备，请合理划分层级。</li>
                {isNew ? (
                  <li>
                    当前上级：
                    <strong>{parentId ? parentRegionName(regions, parentId) : "顶级（无上级）"}</strong>
                  </li>
                ) : regionId ? (
                  <li>
                    当前上级：<strong>{parentRegionName(regions, parentId)}</strong>
                  </li>
                ) : null}
              </ul>
            </aside>
          </div>
        )}

        {!loading ? (
          <footer className="pf-region-editor-footer">
            <Link to="/admin/regions" className="pf-btn pf-btn-sm">
              取消
            </Link>
            <button
              type="button"
              className={`pf-btn pf-btn-sm pf-btn-primary${saving ? " is-loading" : ""}`}
              disabled={!canSave}
              onClick={() => void save()}
            >
              {saving ? "保存中…" : isNew ? "创建区域" : "保存修改"}
            </button>
          </footer>
        ) : null}
      </div>
    </div>
  );
}
