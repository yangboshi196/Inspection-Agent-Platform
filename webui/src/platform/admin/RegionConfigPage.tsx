import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { Badge } from "../components/Badge";
import { Modal } from "../components/Modal";
import type { CameraDevice, InspectionWorkEntity, SensorDevice } from "../types";
import {
  deleteEquipment,
  loadCamerasAndSensors,
  loadSensorReadings,
  patchEquipment,
  type SensorReadingRow,
} from "../equipmentApi";
import { EquipmentImportModal } from "./EquipmentImportModal";
import { EquipmentCreateModal } from "./EquipmentCreateModal";
import { EquipmentBatchImportModal } from "./EquipmentBatchImportModal";
import { RtspLivePreview } from "./RtspLivePreview";
import { buildNewRegionPath } from "./regionCreateUtils";
import { loadRegions, removeRegion, regionNameMap, type RegionRow } from "../regionApi";
import {
  buildRegionTree,
  collectRegionScopeIds,
  findRegionTreeNode,
  flattenRegionTree,
  flattenRegionTreeWithCollapse,
  parentRegionName,
} from "../regionTree";
import { loadLinkedInspectionWorks } from "../inspectionWorkApi";
import {
  deviceStats,
  kindLabel,
  regionDeviceCount,
  toDeviceList,
  type DeviceKind,
  type DeviceListItem,
} from "./deviceMock";

type KindFilter = "all" | DeviceKind;
type OnlineFilter = "all" | "online" | "offline";

/** 区域配置：层级区域树 + 选中区域后管理设备 */
export function RegionConfigPage() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [regions, setRegions] = useState<RegionRow[]>([]);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [sensors, setSensors] = useState<SensorDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(
    () => searchParams.get("region"),
  );
  const [onlineFilter, setOnlineFilter] = useState<OnlineFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [regionKw, setRegionKw] = useState("");
  const [kw, setKw] = useState("");
  const [hint, setHint] = useState("");
  const [previewCam, setPreviewCam] = useState<CameraDevice | null>(null);
  const [historySensor, setHistorySensor] = useState<SensorDevice | null>(null);
  const [linkedWorks, setLinkedWorks] = useState<InspectionWorkEntity[]>([]);
  const [sensorHistory, setSensorHistory] = useState<SensorReadingRow[]>([]);
  const [linkedLoading, setLinkedLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [equipmentImportOpen, setEquipmentImportOpen] = useState(false);
  const [equipmentCreateOpen, setEquipmentCreateOpen] = useState(false);
  const [equipmentBatchOpen, setEquipmentBatchOpen] = useState(false);
  const [collapsedRegionIds, setCollapsedRegionIds] = useState<Set<string>>(() => new Set());
  const [deletingRegion, setDeletingRegion] = useState(false);
  const [editName, setEditName] = useState("");
  const [editKind, setEditKind] = useState<DeviceKind>("camera");
  const [editDesc, setEditDesc] = useState("");
  const [editPlatformAddress, setEditPlatformAddress] = useState("");
  const [debouncedPreviewRtsp, setDebouncedPreviewRtsp] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedPreviewRtsp(editPlatformAddress.trim());
    }, 800);
    return () => window.clearTimeout(timer);
  }, [editPlatformAddress]);

  const regionNames = useMemo(() => regionNameMap(regions), [regions]);
  const regionNameOf = (regionId: string) => regionNames[regionId] ?? regionId;
  const assignableRegions = useMemo(
    () => regions.map((r) => ({ id: r.id, name: r.name })),
    [regions],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const regs = await loadRegions({ force: true });
        const names = regionNameMap(regs);
        const equip = await loadCamerasAndSensors((id) => names[id] || id);
        if (cancelled) return;
        setRegions(regs);
        setCameras(equip.cameras);
        setSensors(equip.sensors);
      } catch (e) {
        if (!cancelled) setHint(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const regionInitRef = useRef(false);

  useEffect(() => {
    if (regions.length === 0) return;
    const fromNav = (location.state as { region?: string } | null)?.region;
    if (fromNav && regions.some((r) => r.id === fromNav)) {
      setSelectedRegionId(fromNav);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("region", fromNav);
          return next;
        },
        { replace: true },
      );
      window.history.replaceState({}, document.title);
      return;
    }
    const fromUrl = searchParams.get("region");
    const urlId = fromUrl && regions.some((r) => r.id === fromUrl) ? fromUrl : null;
    const syncUrl = (id: string) => {
      setSearchParams(
        (prev) => {
          if (prev.get("region") === id) return prev;
          const next = new URLSearchParams(prev);
          next.set("region", id);
          return next;
        },
        { replace: true },
      );
    };
    if (urlId) {
      setSelectedRegionId((cur) => (cur === urlId ? cur : urlId));
      return;
    }
    if (regionInitRef.current) return;
    regionInitRef.current = true;
    const first = regions.find((r) => r.id !== "r0") ?? regions[0];
    if (!first) return;
    setSelectedRegionId(first.id);
    syncUrl(first.id);
  }, [regions, searchParams, setSearchParams, location.state]);

  const stats = deviceStats(cameras, sensors);
  const allDevices = useMemo(() => toDeviceList(cameras, sensors), [cameras, sensors]);

  const regionTree = useMemo(
    () => buildRegionTree(regions, (id) => regionDeviceCount(cameras, sensors, id)),
    [regions, cameras, sensors],
  );

  const visibleRegionNodes = useMemo(() => {
    const q = regionKw.trim().toLowerCase();
    const flat = q
      ? flattenRegionTree(regionTree)
      : flattenRegionTreeWithCollapse(regionTree, collapsedRegionIds);
    if (!q) return flat;
    return flat.filter((node) =>
      [node.name, node.id, node.desc, parentRegionName(regions, node.parent_id)]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [regionTree, regionKw, regions, collapsedRegionIds]);

  const activeRegionNode = useMemo(
    () => (selectedRegionId ? findRegionTreeNode(regionTree, selectedRegionId) : null),
    [regionTree, selectedRegionId],
  );

  const resolvedRegion = useMemo(() => {
    if (activeRegionNode) return activeRegionNode;
    if (!selectedRegionId) return null;
    const row = regions.find((r) => r.id === selectedRegionId);
    if (!row) return null;
    return {
      ...row,
      parent_id: row.parent_id ?? "",
      sort_order: row.sort_order ?? 0,
      depth: 0,
      deviceCount: regionDeviceCount(cameras, sensors, row.id),
      subtreeDeviceCount: regionDeviceCount(cameras, sensors, row.id),
      childCount: 0,
      children: [],
    };
  }, [activeRegionNode, selectedRegionId, regions, cameras, sensors]);

  const scopeRegionIds = useMemo(() => {
    if (activeRegionNode) return collectRegionScopeIds(activeRegionNode);
    if (selectedRegionId) return [selectedRegionId];
    return [];
  }, [activeRegionNode, selectedRegionId]);

  const scopedDevices = useMemo(() => {
    if (!selectedRegionId) return [];
    return allDevices.filter((d) => scopeRegionIds.includes(d.regionId));
  }, [allDevices, selectedRegionId, scopeRegionIds]);

  const scopedStats = useMemo(() => {
    const cams = scopedDevices.filter((d) => d.kind === "camera");
    const sens = scopedDevices.filter((d) => d.kind === "sensor");
    return {
      total: scopedDevices.length,
      cameras: cams.length,
      sensors: sens.length,
      online: scopedDevices.filter((d) => d.online).length,
      offline: scopedDevices.filter((d) => !d.online).length,
    };
  }, [scopedDevices]);

  const filtered = useMemo(() => {
    let list = scopedDevices;
    if (kindFilter !== "all") list = list.filter((d) => d.kind === kindFilter);
    if (onlineFilter === "online") list = list.filter((d) => d.online);
    if (onlineFilter === "offline") list = list.filter((d) => !d.online);
    const q = kw.trim().toLowerCase();
    if (q) {
      list = list.filter((d) =>
        [d.name, d.description, d.id, d.regionName, d.subLabel].join(" ").toLowerCase().includes(q),
      );
    }
    return list;
  }, [scopedDevices, kindFilter, onlineFilter, kw]);

  const selectedItem =
    selectedId && scopedDevices.some((d) => d.id === selectedId)
      ? allDevices.find((d) => d.id === selectedId) ?? null
      : null;
  const selectedCamera = selectedItem?.kind === "camera" ? cameras.find((c) => c.id === selectedItem.id) : null;
  const selectedSensor = selectedItem?.kind === "sensor" ? sensors.find((s) => s.id === selectedItem.id) : null;

  useEffect(() => {
    if (!selectedItem) return;
    setEditName(selectedItem.name);
    setEditKind(selectedItem.kind);
    setEditDesc(selectedItem.description);
    setEditPlatformAddress(
      selectedCamera?.platformAddress ?? selectedSensor?.platformAddress ?? "",
    );
  }, [selectedItem?.id]);

  useEffect(() => {
    if (!selectedItem?.id) {
      setLinkedWorks([]);
      return;
    }
    let cancelled = false;
    setLinkedLoading(true);
    void loadLinkedInspectionWorks(selectedItem.id)
      .then((works) => {
        if (!cancelled) setLinkedWorks(works);
      })
      .catch((e) => {
        if (!cancelled) setHint(String(e));
      })
      .finally(() => {
        if (!cancelled) setLinkedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedItem?.id]);

  useEffect(() => {
    if (!historySensor?.id) {
      setSensorHistory([]);
      return;
    }
    let cancelled = false;
    setHistoryLoading(true);
    void loadSensorReadings(historySensor.id)
      .then((rows) => {
        if (!cancelled) setSensorHistory(rows);
      })
      .catch((e) => {
        if (!cancelled) setHint(String(e));
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [historySensor?.id]);

  const setCameraRegion = async (id: string, regionId: string) => {
    try {
      await patchEquipment(id, { region_id: regionId });
      setCameras((list) =>
        list.map((c) => (c.id === id ? { ...c, regionId, regionName: regionNameOf(regionId) } : c)),
      );
      setHint("");
    } catch (e) {
      setHint(String(e));
    }
  };

  const setSensorRegion = async (id: string, regionId: string) => {
    try {
      await patchEquipment(id, { region_id: regionId });
      setSensors((list) =>
        list.map((s) => (s.id === id ? { ...s, regionId, regionName: regionNameOf(regionId) } : s)),
      );
      setHint("");
    } catch (e) {
      setHint(String(e));
    }
  };

  const updateCamera = async (id: string, patch: Partial<CameraDevice>) => {
    try {
      await patchEquipment(id, {
        name: patch.name,
        description: patch.description,
        platform_name: patch.platformName,
        platform_address: patch.platformAddress,
        online: patch.online,
        region_id: patch.regionId,
        thumbnail: patch.thumbnail,
      });
      setCameras((list) =>
        list.map((c) =>
          c.id === id
            ? {
                ...c,
                ...patch,
                regionName: patch.regionId ? regionNameOf(patch.regionId) : c.regionName,
              }
            : c,
        ),
      );
    } catch (e) {
      setHint(String(e));
    }
  };

  const updateSensor = async (id: string, patch: Partial<SensorDevice>) => {
    try {
      await patchEquipment(id, {
        name: patch.name,
        description: patch.description,
        platform_name: patch.platformName,
        platform_address: patch.platformAddress,
        online: patch.online,
        region_id: patch.regionId,
        data_type: patch.dataType,
        unit: patch.unit,
      });
      setSensors((list) =>
        list.map((s) =>
          s.id === id
            ? {
                ...s,
                ...patch,
                regionName: patch.regionId ? regionNameOf(patch.regionId) : s.regionName,
              }
            : s,
        ),
      );
    } catch (e) {
      setHint(String(e));
    }
  };

  const deleteDevice = async (item: DeviceListItem) => {
    if (!window.confirm(`确定删除设备「${item.name}」（${item.id}）？此操作不可恢复。`)) return;
    try {
      await deleteEquipment(item.id);
      if (item.kind === "camera") setCameras((list) => list.filter((c) => c.id !== item.id));
      else setSensors((list) => list.filter((s) => s.id !== item.id));
      setSelectedId(null);
      setHint("已删除设备");
    } catch (e) {
      setHint(String(e));
    }
  };

  const saveDeviceFields = async () => {
    if (!selectedItem) return;
    if (!editName.trim()) {
      setHint("设备名称不能为空");
      return;
    }
    setEditSaving(true);
    try {
      const row = await patchEquipment(selectedItem.id, {
        name: editName.trim(),
        kind: editKind,
        description: editDesc.trim(),
        platform_address: editPlatformAddress.trim(),
      });
      setEditName(row.name);
      setEditKind(row.kind);
      setEditDesc(row.description);
      setEditPlatformAddress(row.platform_address ?? "");
      setCameras((list) =>
        list.map((c) =>
          c.id === selectedItem.id
            ? {
                ...c,
                name: row.name,
                description: row.description,
                platformAddress: row.platform_address ?? "",
              }
            : c,
        ),
      );
      setSensors((list) =>
        list.map((s) =>
          s.id === selectedItem.id
            ? {
                ...s,
                name: row.name,
                description: row.description,
                platformAddress: row.platform_address ?? "",
              }
            : s,
        ),
      );
      setHint(
        selectedCamera && editPlatformAddress.trim()
          ? "设备信息已保存，巡检将使用该 RTSP 流"
          : "设备信息已保存",
      );
      if (row.kind !== selectedItem.kind) {
        await reloadEquipment();
      }
    } catch (e) {
      setHint(String(e));
    } finally {
      setEditSaving(false);
    }
  };

  const reloadEquipment = async () => {
    const equip = await loadCamerasAndSensors(regionNameOf);
    setCameras(equip.cameras);
    setSensors(equip.sensors);
  };

  const selectRegion = (regionId: string) => {
    setSelectedRegionId(regionId);
    setSelectedId(null);
    setKindFilter("all");
    setOnlineFilter("all");
    setKw("");
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("region", regionId);
        return next;
      },
      { replace: true },
    );
  };

  const toggleRegionCollapse = (regionId: string) => {
    setCollapsedRegionIds((prev) => {
      const next = new Set(prev);
      if (next.has(regionId)) next.delete(regionId);
      else next.add(regionId);
      return next;
    });
  };

  const handleDeleteRegion = async () => {
    if (!resolvedRegion || deletingRegion) return;
    if (resolvedRegion.childCount > 0) {
      setHint("请先删除所有子区域");
      return;
    }
    const regionName = resolvedRegion.name;
    const regionId = resolvedRegion.id;
    const parentId = resolvedRegion.parent_id;
    const directDeviceCount = allDevices.filter((d) => d.regionId === regionId).length;
    const confirmMsg =
      directDeviceCount > 0
        ? `确定删除区域「${regionName}」？将同时删除该区域内的 ${directDeviceCount} 台设备，此操作不可恢复。`
        : `确定删除区域「${regionName}」？此操作不可恢复。`;
    if (!window.confirm(confirmMsg)) return;

    setDeletingRegion(true);
    setHint("");
    try {
      await removeRegion(regionId);
      const regs = await loadRegions({ force: true });
      setRegions(regs);
      await reloadEquipment();
      setSelectedId(null);
      const next =
        (parentId && regs.some((r) => r.id === parentId) ? parentId : null) ??
        regs.find((r) => r.id !== regionId)?.id ??
        null;
      if (next) selectRegion(next);
      else {
        setSelectedRegionId(null);
        setSearchParams(
          (prev) => {
            const params = new URLSearchParams(prev);
            params.delete("region");
            return params;
          },
          { replace: true },
        );
      }
      setHint(`已删除区域「${regionName}」${directDeviceCount > 0 ? `，并清空 ${directDeviceCount} 台设备` : ""}`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setDeletingRegion(false);
    }
  };

  return (
    <div className="pf-scroll pf-dev-page pf-region-config-page">
      <header className="pf-dev-top-bar">
        <div className="pf-dev-top-left">
          <div className="pf-dev-title-block">
            <span className="pf-dev-title-mark" aria-hidden>◎</span>
            <h1>区域配置</h1>
          </div>
          <div className="pf-dev-metrics" aria-label="区域与设备统计">
            <span className="pf-dev-metric pf-dev-metric-blue"><strong>{regions.length}</strong><em>区域</em></span>
            <span className="pf-dev-metric pf-dev-metric-purple"><strong>{stats.total}</strong><em>设备</em></span>
            <span className="pf-dev-metric pf-dev-metric-orange"><strong>{stats.cameras}</strong><em>摄像头</em></span>
            <span className="pf-dev-metric pf-dev-metric-green"><strong>{stats.online}</strong><em>在线</em></span>
          </div>
          <span className="pf-dev-demo-tag">已接后端</span>
        </div>
        <div className="pf-dev-header-actions">
          <Link
            to={buildNewRegionPath(selectedRegionId)}
            className="pf-btn pf-btn-sm pf-btn-primary"
            title={selectedRegionId ? "在选中区域下新建子区域" : "新建顶级区域"}
          >
            + 新建区域
          </Link>
          <button type="button" className="pf-btn pf-btn-sm" onClick={() => setEquipmentImportOpen(true)}>
            导入演示包
          </button>
        </div>
      </header>

      {loading ? <div className="pf-dev-status">加载设备中…</div> : null}
      {hint ? <div className="pf-dev-status">{hint}</div> : null}

      <div className="pf-region-config-layout">
        <aside className="pf-panel pf-region-tree-panel">
          <div className="pf-region-tree-head">
            <h2 className="pf-dev-section-title">区域层级</h2>
          </div>
          <input
            type="search"
            className="pf-cell-input pf-region-tree-search"
            placeholder="搜索区域…"
            value={regionKw}
            onChange={(e) => setRegionKw(e.target.value)}
          />
          <ul className="pf-region-tree-list">
            {visibleRegionNodes.length === 0 ? (
              <li className="pf-region-tree-empty">暂无匹配区域</li>
            ) : (
              visibleRegionNodes.map((node) => {
                const hasChildren = node.childCount > 0;
                const isCollapsed = collapsedRegionIds.has(node.id);
                const isActive = selectedRegionId === node.id;
                return (
                  <li key={node.id}>
                    <div
                      className={`pf-region-tree-row${isActive ? " is-active" : ""}`}
                      style={{ "--pf-region-depth": node.depth } as CSSProperties}
                    >
                      {hasChildren ? (
                        <button
                          type="button"
                          className={`pf-region-tree-toggle${isCollapsed ? "" : " is-expanded"}`}
                          aria-label={isCollapsed ? "展开子区域" : "收起子区域"}
                          aria-expanded={!isCollapsed}
                          onClick={() => toggleRegionCollapse(node.id)}
                        >
                          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                            <path
                              d="M3 1.5 L7 5 L3 8.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </button>
                      ) : (
                        <span className="pf-region-tree-toggle pf-region-tree-toggle-spacer" aria-hidden />
                      )}
                      <button
                        type="button"
                        className="pf-region-tree-item"
                        onClick={() => selectRegion(node.id)}
                      >
                        <span className="pf-region-tree-item-main">
                          <span className="pf-region-tree-level">{node.depth === 0 ? "总" : `${node.depth}级`}</span>
                          <span className="pf-region-tree-name">{node.name}</span>
                        </span>
                        <span className="pf-region-tree-meta">
                          {hasChildren ? <em>{node.childCount} 子区</em> : null}
                          <strong>{node.subtreeDeviceCount}</strong>
                        </span>
                      </button>
                    </div>
                  </li>
                );
              })
            )}
          </ul>
        </aside>

        <section className="pf-region-workspace">
          {!resolvedRegion ? (
            <div className="pf-region-workspace-empty">
              <span className="pf-region-workspace-empty-icon" aria-hidden>◎</span>
              <h3>选择区域以管理设备</h3>
              <p>左侧按从大到小展示区域层级，点击某一区域后在此查看并维护其范围内设备。新建区域请使用页头「+ 新建区域」。</p>
            </div>
          ) : (
            <>
              <div className="pf-region-context-bar pf-panel">
                <div className="pf-region-context-main">
                  <div className="pf-region-context-title">
                    <Badge tone="info">{resolvedRegion.depth === 0 ? "顶级区域" : `${resolvedRegion.depth} 级区域`}</Badge>
                    <h2>{resolvedRegion.name}</h2>
                    <code>{resolvedRegion.id}</code>
                  </div>
                  <p className="pf-region-context-desc">
                    {resolvedRegion.desc || "暂无区域说明"}
                    {resolvedRegion.childCount > 0 ? " · 列表含下级区域设备" : ""}
                  </p>
                  <div className="pf-region-context-stats">
                    <span>上级 · {parentRegionName(regions, resolvedRegion.parent_id)}</span>
                    <span>设备 · {scopedStats.total}</span>
                    <span>摄像头 · {scopedStats.cameras}</span>
                    <span>传感器 · {scopedStats.sensors}</span>
                    <span>在线 · {scopedStats.online}</span>
                  </div>
                </div>
                <div className="pf-region-context-actions">
                  <Link
                    to={buildNewRegionPath(resolvedRegion.id)}
                    className="pf-btn pf-btn-sm"
                    title="在当前区域下新建子区域"
                  >
                    + 子区域
                  </Link>
                  <Link
                    to={`/admin/regions/${resolvedRegion.id}/edit`}
                    className="pf-region-edit-link"
                    title="编辑区域信息"
                  >
                    <svg
                      className="pf-region-edit-link-icon"
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                    <span>编辑</span>
                  </Link>
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm pf-btn-danger"
                    title={resolvedRegion.childCount > 0 ? "请先删除所有子区域" : "删除当前区域及其设备"}
                    disabled={deletingRegion}
                    onClick={() => void handleDeleteRegion()}
                  >
                    {deletingRegion ? "删除中…" : "删除区域"}
                  </button>
                </div>
              </div>

              <div className="pf-region-device-layout">
                <section className="pf-panel pf-dev-list-panel">
                  <div className="pf-region-device-list-head">
                    <div className="pf-region-device-list-title-row">
                      <h2 className="pf-dev-section-title">设备列表 ({filtered.length})</h2>
                      <div className="pf-region-device-list-actions">
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm pf-btn-primary"
                          onClick={() => setEquipmentCreateOpen(true)}
                        >
                          + 添加设备
                        </button>
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm"
                          onClick={() => setEquipmentBatchOpen(true)}
                        >
                          批量导入
                        </button>
                      </div>
                    </div>
                    <div className="pf-region-device-filters" role="toolbar" aria-label="设备筛选">
                      <div className="pf-region-device-filter-group">
                        <span className="pf-region-device-filter-label">类型</span>
                        <div className="pf-dev-filter-row pf-dev-filter-row-segmented">
                          {([
                            { id: "all" as const, label: "全部" },
                            { id: "camera" as const, label: "摄像头" },
                            { id: "sensor" as const, label: "传感器" },
                          ]).map((cat) => (
                            <button
                              key={cat.id}
                              type="button"
                              className={`pf-dev-filter-chip${kindFilter === cat.id ? " is-active" : ""}`}
                              onClick={() => {
                                setKindFilter(cat.id);
                                setSelectedId(null);
                              }}
                            >
                              {cat.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="pf-region-device-filter-group">
                        <span className="pf-region-device-filter-label">状态</span>
                        <div className="pf-dev-filter-row pf-dev-filter-row-segmented">
                          {([
                            { id: "all" as const, label: "全部" },
                            { id: "online" as const, label: "在线" },
                            { id: "offline" as const, label: "离线" },
                          ]).map((s) => (
                            <button
                              key={s.id}
                              type="button"
                              className={`pf-dev-filter-chip${onlineFilter === s.id ? " is-active" : ""}`}
                              onClick={() => setOnlineFilter(s.id)}
                            >
                              {s.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="pf-region-device-filter-group pf-region-device-filter-search">
                        <span className="pf-region-device-filter-label">搜索</span>
                        <input
                          type="search"
                          className="pf-cell-input pf-region-device-search"
                          placeholder="名称、ID、区域…"
                          value={kw}
                          onChange={(e) => setKw(e.target.value)}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="pf-dev-list">
                    {filtered.length === 0 ? (
                      <p className="pf-dev-list-empty">
                        当前区域范围内暂无设备。可使用「+ 添加设备」单条录入，或「批量导入」按 CSV 模板导入。
                      </p>
                    ) : (
                      filtered.map((d) => (
                        <DeviceRow
                          key={d.id}
                          item={d}
                          active={selectedItem?.id === d.id}
                          onSelect={() => setSelectedId(d.id)}
                        />
                      ))
                    )}
                  </div>
                </section>

                <section className="pf-panel pf-dev-detail-panel">
                  {selectedItem && (selectedCamera || selectedSensor) ? (
            <div className="pf-dev-detail-body">
              <div className="pf-dev-detail-head">
                <div>
                  <div className="pf-dev-detail-badges">
                    <Badge tone="info">{kindLabel(selectedItem.kind)}</Badge>
                    <Badge tone={selectedItem.online ? "success" : "draft"}>
                      {selectedItem.online ? "在线" : "离线"}
                    </Badge>
                  </div>
                  <p className="pf-dev-detail-id">ID：{selectedItem.id}</p>
                </div>
                <div className="pf-dev-detail-actions">
                  <button type="button" className="pf-btn pf-btn-sm pf-btn-danger" onClick={() => deleteDevice(selectedItem)}>
                    删除设备
                  </button>
                </div>
              </div>

              <section className="pf-dev-edit-block">
                <h3 className="pf-dev-block-title">编辑设备</h3>
                <label className="pf-dev-field">
                  <span>设备名称</span>
                  <input
                    className="pf-cell-input"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                  />
                </label>
                <label className="pf-dev-field">
                  <span>类型</span>
                  <select
                    className="pf-cell-input"
                    value={editKind}
                    onChange={(e) => setEditKind(e.target.value as DeviceKind)}
                  >
                    <option value="camera">摄像头</option>
                    <option value="sensor">传感器</option>
                  </select>
                </label>
                <label className="pf-dev-field">
                  <span>描述</span>
                  <textarea
                    className="pf-cell-textarea pf-dev-textarea"
                    rows={3}
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    placeholder="地点、画面、业务说明等"
                  />
                </label>
              </section>

              <section className="pf-dev-platform-block">
                <h3 className="pf-dev-block-title">接入平台</h3>
                <dl className="pf-dev-platform-dl">
                  <div>
                    <dt>平台名称</dt>
                    <dd>{selectedCamera?.platformName ?? selectedSensor?.platformName ?? "—"}</dd>
                  </div>
                </dl>
                <label className="pf-dev-field">
                  <span>{selectedCamera ? "RTSP 流地址" : "平台地址"}</span>
                  <input
                    className="pf-cell-input pf-dev-rtsp-input"
                    value={editPlatformAddress}
                    onChange={(e) => setEditPlatformAddress(e.target.value)}
                    placeholder={
                      selectedCamera
                        ? "rtsp://admin:password@192.168.1.47:554/Streaming/Channels/101（卡顿可试 102 子码流）"
                        : "mqtt://iot-gw.local:1883/sensors/sen-001"
                    }
                    spellCheck={false}
                  />
                  {selectedCamera ? (
                    <span className="pf-dev-field-hint">
                      填写后保存；预览将通过该 RTSP 实时拉流（与 VLC 相同地址格式）
                    </span>
                  ) : null}
                </label>
                <button
                  type="button"
                  className="pf-btn pf-btn-sm pf-btn-primary pf-dev-save-btn"
                  disabled={editSaving}
                  onClick={() => void saveDeviceFields()}
                >
                  {editSaving ? "保存中…" : "保存修改"}
                </button>
              </section>

              {selectedCamera ? (
                <DeviceMonitorPreview
                  camera={selectedCamera}
                  rtspAddress={debouncedPreviewRtsp || selectedCamera.platformAddress}
                  onOpen={() =>
                    setPreviewCam({
                      ...selectedCamera,
                      platformAddress: editPlatformAddress.trim() || selectedCamera.platformAddress,
                    })
                  }
                  liveRefreshMs={2000}
                  livePaused={!!previewCam && previewCam.id === selectedCamera.id}
                />
              ) : null}

              <section className="pf-dev-linked-works">
                <h3 className="pf-dev-block-title">关联巡检业务 ({linkedLoading ? "…" : linkedWorks.length})</h3>
                {linkedWorks.length > 0 ? (
                  <ul className="pf-dev-linked-work-list">
                    {linkedWorks.map((work) => (
                      <li key={work.work_id}>
                        <Link to="/admin/inspection-works" className="pf-dev-linked-work-item">
                          <strong>{work.name}</strong>
                          <span>{work.region_name}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="pf-dev-linked-empty">当前设备尚未绑定巡检业务</p>
                )}
              </section>

              <label className="pf-dev-field">
                <span>所属区域</span>
                <select
                  className="pf-cell-input"
                  value={selectedItem.regionId}
                  onChange={(e) => {
                    const rid = e.target.value;
                    if (selectedCamera) setCameraRegion(selectedCamera.id, rid);
                    if (selectedSensor) setSensorRegion(selectedSensor.id, rid);
                  }}
                >
                  {assignableRegions.map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>
              </label>

              <dl className="pf-dev-dl">
                <div><dt>区域</dt><dd>{selectedItem.regionName}</dd></div>
                {selectedSensor ? (
                  <>
                    <div><dt>数据类型</dt><dd>{selectedSensor.dataType}</dd></div>
                    <div><dt>单位</dt><dd>{selectedSensor.unit}</dd></div>
                  </>
                ) : (
                  <>
                    <div><dt>类型</dt><dd>视频流</dd></div>
                    <div><dt>接入</dt><dd>{editPlatformAddress.trim() ? "RTSP 直连" : "未配置"}</dd></div>
                  </>
                )}
              </dl>

              <div className="pf-dev-detail-foot">
                {selectedCamera ? (
                  <button type="button" className="pf-btn pf-btn-primary pf-btn-sm" onClick={() => setPreviewCam(selectedCamera)}>
                    查看画面
                  </button>
                ) : selectedSensor ? (
                  <button type="button" className="pf-btn pf-btn-primary pf-btn-sm" onClick={() => setHistorySensor(selectedSensor)}>
                    历史数据
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="pf-dev-detail-empty">选择设备查看接入平台与关联巡检业务</p>
          )}
                </section>
              </div>
            </>
          )}
        </section>
      </div>

      <Modal open={!!previewCam} title={previewCam?.name ?? ""} onClose={() => setPreviewCam(null)} wide>
        {previewCam ? (
          <DeviceMonitorPreview
            camera={previewCam}
            rtspAddress={previewCam.platformAddress}
            large
            liveRefreshMs={1200}
            livePaused={false}
          />
        ) : null}
        <p className="pf-page-subtitle">ID：{previewCam?.id} · 区域：{previewCam?.regionName}</p>
      </Modal>

      <EquipmentImportModal
        open={equipmentImportOpen}
        onClose={() => setEquipmentImportOpen(false)}
        currentDeviceCount={stats.total}
        onImported={async ({ inserted, mode }) => {
          setHint("");
          try {
            await reloadEquipment();
            setHint(
              inserted > 0
                ? `已${mode === "replace" ? "全量替换并" : ""}导入 ${inserted} 条演示设备`
                : "演示包设备均已存在，未新增记录",
            );
          } catch (e) {
            setHint(String(e));
          }
        }}
      />

      {resolvedRegion ? (
        <>
          <EquipmentCreateModal
            open={equipmentCreateOpen}
            regionId={resolvedRegion.id}
            regionName={resolvedRegion.name}
            onClose={() => setEquipmentCreateOpen(false)}
            onCreated={async (equipmentId) => {
              await reloadEquipment();
              setSelectedId(equipmentId);
              setHint("设备已创建");
            }}
          />
          <EquipmentBatchImportModal
            open={equipmentBatchOpen}
            defaultRegionId={resolvedRegion.id}
            defaultRegionName={resolvedRegion.name}
            onClose={() => setEquipmentBatchOpen(false)}
            onImported={async ({ inserted, skipped, errors }) => {
              await reloadEquipment();
              setHint(
                `批量导入完成：新增 ${inserted} 条${skipped > 0 ? `，跳过 ${skipped} 条` : ""}${errors > 0 ? `，失败 ${errors} 条` : ""}`,
              );
            }}
          />
        </>
      ) : null}

      <Modal open={!!historySensor} title={`${historySensor?.name ?? ""} · 历史数据`} onClose={() => setHistorySensor(null)}>
        {historyLoading ? <p className="pf-page-subtitle">加载中…</p> : null}
        <div className="pf-chart-bars">
          {sensorHistory.map((h, i) => (
            <div
              key={i}
              className={`pf-chart-bar ${h.status}`}
              style={{ height: `${(h.value / 35) * 100}%` }}
              title={`${h.time}: ${h.value}`}
            />
          ))}
        </div>
        <table className="pf-table" style={{ marginTop: 16 }}>
          <thead>
            <tr>
              <th>时间</th>
              <th>数值</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {sensorHistory.map((h) => (
              <tr key={h.time}>
                <td>{h.time}</td>
                <td>{h.value}</td>
                <td>{h.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Modal>
    </div>
  );
}

function DeviceMonitorPreview({
  camera,
  large,
  onOpen,
  rtspAddress,
  liveRefreshMs = 1500,
  livePaused = false,
}: {
  camera: CameraDevice;
  large?: boolean;
  onOpen?: () => void;
  rtspAddress?: string;
  liveRefreshMs?: number;
  livePaused?: boolean;
}) {
  const useRtsp = Boolean((rtspAddress || "").trim());
  const previewOnlyRtsp =
    useRtsp && rtspAddress!.trim() !== (camera.platformAddress || "").trim()
      ? rtspAddress
      : undefined;
  const body = (
    <div
      className={`pf-dev-monitor-preview${camera.online ? "" : " is-offline"}${large ? " pf-dev-monitor-preview-lg" : ""}${useRtsp ? " has-rtsp-stream" : ""}`}
      style={{ background: camera.thumbnail }}
    >
      {useRtsp ? (
        <>
            <RtspLivePreview
            equipmentId={camera.id}
            refreshMs={liveRefreshMs}
            paused={livePaused}
            large={large}
            onZoom={onOpen}
            previewRtsp={previewOnlyRtsp}
          />
          <span className="pf-dev-monitor-rtsp-url" title={rtspAddress}>
            {rtspAddress}
          </span>
        </>
      ) : null}
      <span className="pf-dev-monitor-corner pf-dev-monitor-corner-tl" aria-hidden />
      <span className="pf-dev-monitor-corner pf-dev-monitor-corner-tr" aria-hidden />
      <span className="pf-dev-monitor-corner pf-dev-monitor-corner-bl" aria-hidden />
      <span className="pf-dev-monitor-corner pf-dev-monitor-corner-br" aria-hidden />
      {useRtsp ? null : <span className="pf-dev-monitor-scan" aria-hidden />}
      {camera.online || useRtsp ? (
        <span className="pf-dev-monitor-rec">
          <i aria-hidden /> {useRtsp ? "RTSP" : "REC"}
        </span>
      ) : null}
      <span className="pf-dev-monitor-ts">2026-05-19 14:32:08</span>
      <span className="pf-dev-monitor-label">{camera.name}</span>
    </div>
  );

  if (onOpen) {
    return (
      <div
        className="pf-dev-monitor-trigger"
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen();
          }
        }}
      >
        {body}
      </div>
    );
  }
  return body;
}

function DeviceRow({
  item,
  active,
  onSelect,
}: {
  item: DeviceListItem;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={`pf-dev-list-item${active ? " is-active" : ""}`} onClick={onSelect}>
      <div className="pf-dev-list-item-top">
        <div className="pf-dev-list-item-title">
          <span className="pf-dev-kind-icon" aria-hidden>{item.kind === "camera" ? "◎" : "◫"}</span>
          <strong>{item.name}</strong>
        </div>
        <Badge tone={item.online ? "success" : "draft"}>{item.online ? "在线" : "离线"}</Badge>
      </div>
      <p>{item.description || "暂无描述"}</p>
      <div className="pf-dev-list-item-meta">
        <span>{item.subLabel}</span>
        <span>{item.regionName}</span>
        <span>{kindLabel(item.kind)}</span>
      </div>
    </button>
  );
}
