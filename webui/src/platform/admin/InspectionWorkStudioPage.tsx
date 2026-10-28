import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "../components/Badge";
import type { AlgorithmItem, CameraDevice, KnowledgeRule, InspectionScheduleMode, InspectionWorkEntity, SensorDevice } from "../types";
import {
  createInspectionWork,
  deleteInspectionWork,
  listInspectionWorks,
  patchInspectionWork,
  readApiError,
  runInspectionWork,
} from "../../api";
import { loadAlgorithmCatalog } from "../algorithmApi";
import { loadCamerasAndSensors } from "../equipmentApi";
import { loadRegions, regionNameMap } from "../regionApi";
import { buildRegionTree, collectRegionScopeIds, findRegionTreeNode } from "../regionTree";
import {
  apiRowToInspectionWork,
  inspectionWorkToCreateBody,
  inspectionWorkToPatchBody,
} from "../inspectionWorkApi";
import {
  emptyInspectionWork,
  toggleId,
} from "../inspectionWorkStudio";
import {
  PERIODIC_INTERVAL_OPTIONS,
  CONTINUOUS_CHECK_INTERVAL_LABEL,
  CONTINUOUS_ANALYSIS_WINDOW_SEC,
  SCHEDULE_MODE_OPTIONS,
  applyEquipmentWithRegion,
  effectiveRegionIds,
  formatWorkRegionLabel,
  scheduleModeLabel,
} from "../inspectionWorkUtils";
import { loadLogEntries } from "../logsApi";
import { loadPublishedRules } from "./knowledgeApi";
import { AiWorkComposerModal } from "./AiWorkComposerModal";
import { AiGenerationTracePanel } from "./AiGenerationTracePanel";
import { EquipmentAlgoConfigModal } from "./EquipmentAlgoConfigModal";
import { EquipmentSelectRow } from "./EquipmentSelectRow";
import { RegionScopePicker } from "./RegionScopePicker";
import { WorkReportTemplateBindModal } from "./WorkReportTemplateBindModal";
import { ReportPushModal } from "./ReportPushModal";
import { WorkTrackingModal } from "./WorkTrackingModal";
import {
  getWorkTracking,
  listWorkTracking,
  publishWorkTracking,
  unpublishWorkTracking,
} from "./workTrackingApi";
import type { WorkReportTemplateBinding } from "./workReportTemplateApi";
import { getWorkReportTemplateBinding } from "./workReportTemplateApi";
import { useAuth } from "../AuthContext";

function workSummary(w: InspectionWorkEntity) {
  return `${w.rule_set.length} 规范 · ${w.algorithm_set.length} 算法 · ${w.equipment_set.length} 设备`;
}

function workCompleteness(w: InspectionWorkEntity) {
  let score = 0;
  if (w.rule_set.length > 0) score += 34;
  if (w.algorithm_set.length > 0) score += 33;
  if (w.equipment_set.length > 0) score += 33;
  return score;
}

/** 从业务日志条目中取与当前 work 相关的最新进度文案。 */
function pickRunLogProgress(workId: string, items: Array<{ message: string; raw: string }>): string | null {
  const related = items.filter((e) => e.raw.includes(workId) || e.message.includes(workId));
  const latest = related[related.length - 1] ?? items[items.length - 1];
  const msg = latest?.message?.trim();
  return msg || null;
}

function rebuildRuleSet(ruleIds: string[], catalog: KnowledgeRule[]) {
  return ruleIds
    .map((id) => {
      const r = catalog.find((x) => x.id === id);
      if (!r) return null;
      return {
        rule_id: r.id,
        name: r.name,
        level: "important",
      };
    })
    .filter(Boolean) as InspectionWorkEntity["rule_set"];
}

function rebuildAlgoSet(algoIds: string[], catalog: AlgorithmItem[]) {
  return algoIds
    .map((id) => {
      const a = catalog.find((x) => x.id === id);
      if (!a) return null;
      return { algorithm_id: a.id, name: a.name, health: a.health };
    })
    .filter(Boolean) as InspectionWorkEntity["algorithm_set"];
}

function rebuildEquipSet(
  equipIds: string[],
  cameras: CameraDevice[],
  sensors: SensorDevice[],
) {
  return equipIds
    .map((id) => {
      const cam = cameras.find((x) => x.id === id);
      if (cam) return { equipment_id: cam.id, name: cam.name, role: "camera" };
      const sen = sensors.find((x) => x.id === id);
      if (sen) return { equipment_id: sen.id, name: sen.name, role: "sensor" };
      return null;
    })
    .filter(Boolean) as InspectionWorkEntity["equipment_set"];
}

type ResourceCardProps = {
  selected: boolean;
  title: string;
  subtitle: string;
  icon: string;
  accent: "purple" | "orange" | "green" | "blue";
  onToggle: () => void;
};

function ResourceCard({ selected, title, subtitle, icon, accent, onToggle }: ResourceCardProps) {
  return (
    <button
      type="button"
      className={`pf-studio-resource-card pf-studio-accent-${accent}${selected ? " is-selected" : ""}`}
      onClick={onToggle}
      aria-pressed={selected}
      title={`${title} · ${subtitle}`}
    >
      <span className="pf-studio-resource-card-glow" aria-hidden />
      <span className="pf-studio-resource-card-icon">{icon}</span>
      <span className="pf-studio-resource-card-body">
        <strong>{title}</strong>
        <small>{subtitle}</small>
      </span>
      <span className="pf-studio-resource-check" aria-hidden>
        {selected ? "✓" : ""}
      </span>
    </button>
  );
}

function workSearchHaystack(w: InspectionWorkEntity): string {
  return [
    w.name,
    w.desc,
    w.region_name,
    w.region_id,
    w.work_id,
    scheduleModeLabel(w.schedule_mode),
    w.source === "ai" ? "AI" : "手动",
    ...w.rule_set.map((r) => r.name),
    ...w.algorithm_set.map((a) => a.name),
    ...w.equipment_set.map((e) => e.name),
  ]
    .join(" ")
    .toLowerCase();
}

function scheduleBadgeTone(mode: InspectionScheduleMode): "info" | "success" | "warning" | "default" {
  switch (mode) {
    case "periodic":
      return "info";
    case "scheduled":
      return "success";
    case "continuous":
      return "warning";
    default:
      return "default";
  }
}

export function InspectionWorkStudioPage() {
  const { loading: authLoading, isAuthenticated } = useAuth();
  const [works, setWorks] = useState<InspectionWorkEntity[]>([]);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [sensors, setSensors] = useState<SensorDevice[]>([]);
  const [regionRows, setRegionRows] = useState<Awaited<ReturnType<typeof loadRegions>>>([]);
  const [publishedRules, setPublishedRules] = useState<KnowledgeRule[]>([]);
  const [algorithms, setAlgorithms] = useState<AlgorithmItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [listFilter, setListFilter] = useState<InspectionScheduleMode | "all">("all");
  const [workStatusFilter, setWorkStatusFilter] = useState<"all" | "online" | "offline">("all");
  const [dirty, setDirty] = useState(false);
  const [newWorkIds, setNewWorkIds] = useState<Set<string>>(() => new Set());
  const [configEquipId, setConfigEquipId] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [trackingOpen, setTrackingOpen] = useState(false);
  const [reportPushOpen, setReportPushOpen] = useState(false);
  const [trackingPublished, setTrackingPublished] = useState(false);
  const [trackingBusy, setTrackingBusy] = useState(false);
  const [publishedWorkIds, setPublishedWorkIds] = useState<Set<string>>(() => new Set());
  const [reportTemplateOpen, setReportTemplateOpen] = useState(false);
  const [reportTemplateBinding, setReportTemplateBinding] = useState<WorkReportTemplateBinding | null>(
    null,
  );
  const [resourceTab, setResourceTab] = useState<"rules" | "algos" | "equip">("rules");
  const [ruleKeyword, setRuleKeyword] = useState("");
  const [workKeyword, setWorkKeyword] = useState("");
  const [toast, setToast] = useState("");
  const [hint, setHint] = useState("");
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);

  const dirtyRef = useRef(false);
  const selectedIdRef = useRef<string | null>(null);
  const newWorkIdsRef = useRef<Set<string>>(new Set());
  const manualRegionsRef = useRef(false);
  dirtyRef.current = dirty;
  selectedIdRef.current = selectedId;
  newWorkIdsRef.current = newWorkIds;

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(""), 2400);
  };

  const refreshPublishedWorkIds = useCallback(async () => {
    try {
      const items = await listWorkTracking();
      setPublishedWorkIds(new Set(items.map((item) => item.work_id)));
    } catch {
      /* 列表角标非关键路径，失败时保留上次状态 */
    }
  }, []);

  const reloadWorks = useCallback(async (regionsForNames: Awaited<ReturnType<typeof loadRegions>>) => {
    const res = await listInspectionWorks(undefined, 200);
    if (!res.ok) throw new Error(await readApiError(res));
    const data = (await res.json()) as { items: Record<string, unknown>[] };
    const names = regionNameMap(regionsForNames);
    const list = data.items.map((row) => {
      const w = apiRowToInspectionWork(row);
      if (w.region_ids?.length) {
        const label = formatWorkRegionLabel(w.region_ids, names);
        w.region_id = label.region_id;
        w.region_name = label.region_name;
      } else if (w.region_id) {
        w.region_name = names[w.region_id] || w.region_id;
      }
      return w;
    });
    setWorks((prev) => {
      const keepLocal = new Map<string, InspectionWorkEntity>();
      for (const w of prev) {
        if (newWorkIdsRef.current.has(w.work_id)) {
          keepLocal.set(w.work_id, w);
        }
      }
      const editingId = selectedIdRef.current;
      if (dirtyRef.current && editingId) {
        const edited = prev.find((w) => w.work_id === editingId);
        if (edited) keepLocal.set(editingId, edited);
      }
      return list.map((w) => keepLocal.get(w.work_id) ?? w);
    });
    setSelectedId((prev) => {
      if (prev && list.some((w) => w.work_id === prev)) return prev;
      return list[0]?.work_id ?? null;
    });
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const regions = await loadRegions();
        const names = regionNameMap(regions);
        const [equip, rules, algos] = await Promise.all([
          loadCamerasAndSensors((id) => names[id] || id),
          loadPublishedRules(),
          loadAlgorithmCatalog(),
        ]);
        if (cancelled) return;
        setRegionRows(regions);
        setCameras(equip.cameras);
        setSensors(equip.sensors);
        setPublishedRules(rules);
        setAlgorithms(algos);
        await reloadWorks(regions);
        await refreshPublishedWorkIds();
      } catch (e) {
        if (!cancelled) setHint(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // 等 AuthContext 完成 /me 后再拉取，避免与 token 解析竞态导致 GET 长期 Pending
  }, [authLoading, isAuthenticated, reloadWorks, refreshPublishedWorkIds]);

  const allEquipment = useMemo(() => [...cameras, ...sensors], [cameras, sensors]);

  const equipCountByRegion = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of cameras) counts.set(c.regionId, (counts.get(c.regionId) ?? 0) + 1);
    for (const s of sensors) counts.set(s.regionId, (counts.get(s.regionId) ?? 0) + 1);
    return counts;
  }, [cameras, sensors]);


  const regionNames = useMemo(() => regionNameMap(regionRows), [regionRows]);

  const equipCountFor = useCallback(
    (id: string) => equipCountByRegion.get(id) ?? 0,
    [equipCountByRegion],
  );

  const regionTreeRoots = useMemo(() => {
    const roots = buildRegionTree(regionRows, (id) => equipCountByRegion.get(id) ?? 0);
    if (roots.length === 1 && roots[0].id === "r0") return roots[0].children;
    return roots.filter((r) => r.id !== "r0");
  }, [regionRows, equipCountByRegion]);

  const filteredWorks = useMemo(() => {
    const kw = workKeyword.trim().toLowerCase();
    let list = works;
    if (listFilter !== "all") {
      list = list.filter((w) => w.schedule_mode === listFilter);
    }
    if (workStatusFilter !== "all") {
      list = list.filter((w) => w.work_status === workStatusFilter);
    }
    if (kw) {
      list = list.filter((w) => workSearchHaystack(w).includes(kw));
    }
    return [...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }, [works, listFilter, workStatusFilter, workKeyword]);

  const selected = works.find((w) => w.work_id === selectedId) ?? null;

  useEffect(() => {
    if (!selected || newWorkIds.has(selected.work_id)) {
      setReportTemplateBinding(null);
      return;
    }
    let cancelled = false;
    void getWorkReportTemplateBinding(selected.work_id)
      .then((row) => {
        if (!cancelled) setReportTemplateBinding(row);
      })
      .catch(() => {
        if (!cancelled) setReportTemplateBinding(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.work_id, newWorkIds]);

  const reportTemplateButtonLabel = useMemo(() => {
    if (reportTemplateBinding?.enabled && reportTemplateBinding.template_name) {
      return reportTemplateBinding.template_name;
    }
    return "报告模版";
  }, [reportTemplateBinding]);

  useEffect(() => {
    if (!triggering || !selectedId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await loadLogEntries({
          source: "business",
          q: selectedId,
          limit: 30,
        });
        if (cancelled || !data.available) return;
        const progress = pickRunLogProgress(selectedId, data.items);
        if (progress) setHint(progress);
      } catch {
        /* 轮询失败不影响主流程 */
      }
    };
    void poll();
    const timer = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [triggering, selectedId]);

  const hasCoreData = works.length > 0;
  const statusMsg =
    loading && !hasCoreData
      ? "加载巡检业务…"
      : triggering
        ? hint || `正在执行「${selected?.name ?? "巡检业务"}」，请稍候…`
        : saving
          ? "正在保存…"
          : hint;

  const editorScopeRegionIds = useMemo(() => {
    const ids = effectiveRegionIds(selected ?? { region_ids: [], region_id: "" });
    if (ids.length === 0) return null;
    const scope = new Set<string>();
    for (const id of ids) {
      const node = findRegionTreeNode(regionTreeRoots, id);
      if (node) {
        for (const sid of collectRegionScopeIds(node)) scope.add(sid);
      } else {
        scope.add(id);
      }
    }
    return scope;
  }, [selected?.region_ids, selected?.region_id, regionTreeRoots]);

  const selectedRegionIds = useMemo(() => {
    if (!selected) return [];
    if ((selected.region_ids?.length ?? 0) > 0) return selected.region_ids!;
    if (manualRegionsRef.current) return [];
    return effectiveRegionIds(selected);
  }, [selected?.region_ids, selected?.region_id, selected?.work_id]);

  const editorCameras = useMemo(() => {
    if (!editorScopeRegionIds) return cameras;
    return cameras.filter((c) => editorScopeRegionIds.has(c.regionId));
  }, [cameras, editorScopeRegionIds]);

  const editorSensors = useMemo(() => {
    if (!editorScopeRegionIds) return sensors;
    return sensors.filter((s) => editorScopeRegionIds.has(s.regionId));
  }, [sensors, editorScopeRegionIds]);

  const selectedRuleIds = selected?.rule_set.map((r) => r.rule_id) ?? [];
  const selectedAlgoIds = selected?.algorithm_set.map((a) => a.algorithm_id) ?? [];
  const selectedEquipIds = selected?.equipment_set.map((e) => e.equipment_id) ?? [];

  const filteredPublishedRules = useMemo(() => {
    let list = publishedRules;
    const kw = ruleKeyword.trim().toLowerCase();
    if (!kw) return list;
    return list.filter((r) => {
      const hay = [r.name, r.scenario, r.requirements, r.sourceFile].join(" ").toLowerCase();
      return hay.includes(kw);
    });
  }, [publishedRules, ruleKeyword]);

  useEffect(() => {
    setConfigEquipId(null);
    manualRegionsRef.current = false;
  }, [selectedId]);

  const patchSelected = useCallback((patch: Partial<InspectionWorkEntity>) => {
    if (!selectedId) return;
    dirtyRef.current = true;
    setDirty(true);
    setWorks((list) =>
      list.map((w) =>
        w.work_id === selectedId
          ? {
              ...w,
              ...patch,
              updated_at: new Date().toISOString().slice(0, 16).replace("T", " "),
            }
          : w,
      ),
    );
  }, [selectedId]);

  const patchEquipment = useCallback((equipIds: string[]) => {
    if (!selectedId) return;
    dirtyRef.current = true;
    setDirty(true);
    setWorks((list) => {
      const current = list.find((w) => w.work_id === selectedId);
      if (!current) return list;
      const equipment_set = rebuildEquipSet(equipIds, cameras, sensors);
      const regionPatch = applyEquipmentWithRegion(
        current,
        equipment_set,
        cameras,
        sensors,
        regionNames,
      );
      const keepManualRegions =
        manualRegionsRef.current || (current.region_ids?.length ?? 0) > 0;
      const merged = keepManualRegions
        ? {
            equipment_set,
            region_id: current.region_id,
            region_name: current.region_name,
            region_ids: current.region_ids,
          }
        : regionPatch;
      const nextParams = { ...(current.equipment_algo_params ?? {}) };
      for (const id of Object.keys(nextParams)) {
        if (!equipIds.includes(id)) delete nextParams[id];
      }
      return list.map((w) =>
        w.work_id === selectedId
          ? {
              ...w,
              ...merged,
              equipment_algo_params: nextParams,
              updated_at: new Date().toISOString().slice(0, 16).replace("T", " "),
            }
          : w,
      );
    });
  }, [selectedId, cameras, sensors, regionNames]);

  const patchSelectedRegions = useCallback(
    (regionIds: string[]) => {
      if (!selectedId) return;
      manualRegionsRef.current = true;
      dirtyRef.current = true;
      setDirty(true);
      const region = formatWorkRegionLabel(regionIds, regionNames);
      setWorks((list) =>
        list.map((w) =>
          w.work_id === selectedId
            ? {
                ...w,
                ...region,
                region_ids: [...region.region_ids],
                updated_at: new Date().toISOString().slice(0, 16).replace("T", " "),
              }
            : w,
        ),
      );
    },
    [selectedId, regionNames],
  );

  const refreshTrackingStatus = useCallback(async (workId: string) => {
    if (!workId || newWorkIds.has(workId)) {
      setTrackingPublished(false);
      return;
    }
    try {
      const row = await getWorkTracking(workId);
      setTrackingPublished(!!row.published);
    } catch {
      setTrackingPublished(false);
    }
  }, [newWorkIds]);

  useEffect(() => {
    if (!selectedId) {
      setTrackingPublished(false);
      return;
    }
    void refreshTrackingStatus(selectedId);
  }, [selectedId, refreshTrackingStatus]);

  const handleToggleTrackingPublish = async () => {
    if (!selected || trackingBusy) return;
    if (dirty || newWorkIds.has(selected.work_id)) {
      showToast("请先保存业务后再发布");
      return;
    }
    setTrackingBusy(true);
    try {
      if (trackingPublished) {
        await unpublishWorkTracking(selected.work_id);
        setTrackingPublished(false);
        setPublishedWorkIds((prev) => {
          const next = new Set(prev);
          next.delete(selected.work_id);
          return next;
        });
        showToast("下架成功");
      } else {
        await publishWorkTracking(selected.work_id);
        setTrackingPublished(true);
        setPublishedWorkIds((prev) => new Set(prev).add(selected.work_id));
        showToast("发布成功");
      }
    } catch (e) {
      showToast(String(e));
    } finally {
      setTrackingBusy(false);
    }
  };

  const selectWork = (workId: string) => {
    if (dirty && selectedId && workId !== selectedId) {
      if (!window.confirm("当前有未保存的更改，确定切换？")) return;
    }
    setSelectedId(workId);
    setDirty(false);
  };

  const replaceWork = (saved: InspectionWorkEntity) => {
    setWorks((list) => list.map((w) => (w.work_id === saved.work_id ? saved : w)));
  };

  const handleSave = async () => {
    if (!selected) return;
    const name = selected.name.trim();
    if (!name) {
      showToast("请填写巡检业务名称");
      return;
    }
    if (selected.rule_set.length === 0) {
      showToast("请至少选择一条规范");
      setResourceTab("rules");
      return;
    }
    if (selected.algorithm_set.length === 0) {
      showToast("请至少选择一个算法");
      setResourceTab("algos");
      return;
    }
    if (selected.equipment_set.length === 0) {
      showToast("请至少选择一台设备");
      setResourceTab("equip");
      return;
    }
    if ((selected.region_ids?.length ?? 0) === 0 && !selected.region_id.trim()) {
      showToast("请至少选择一个作用区域");
      return;
    }

    const payload = {
      ...selected,
      name,
      updated_at: new Date().toISOString().slice(0, 16).replace("T", " "),
    };

    setSaving(true);
    setHint("正在保存…");
    try {
      const isNew = newWorkIds.has(selected.work_id);
      const res = isNew
        ? await createInspectionWork(inspectionWorkToCreateBody(payload))
        : await patchInspectionWork(selected.work_id, inspectionWorkToPatchBody(payload));
      if (!res.ok) throw new Error(await readApiError(res));
      const row = (await res.json()) as Record<string, unknown>;
      const saved = apiRowToInspectionWork(row);
      if (saved.region_ids?.length) {
        const label = formatWorkRegionLabel(saved.region_ids, regionNames);
        saved.region_id = label.region_id;
        saved.region_name = label.region_name;
      } else if (saved.region_id) {
        saved.region_name = regionNames[saved.region_id] || saved.region_id;
      }
      replaceWork(saved);
      setNewWorkIds((prev) => {
        const next = new Set(prev);
        next.delete(selected.work_id);
        return next;
      });
      setDirty(false);
      setHint(`已保存「${saved.name}」`);
      showToast("已保存");
    } catch (e) {
      setHint(String(e));
      showToast(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleTriggerRun = async () => {
    if (!selected || triggering) return;
    if (dirty || newWorkIds.has(selected.work_id)) {
      showToast("请先保存业务配置后再触发");
      return;
    }
    if (selected.schedule_mode !== "manual") {
      showToast("仅「手动触发」运行周期可执行此操作");
      return;
    }
    if (!trackingPublished) {
      showToast("请先发布业务后再触发");
      return;
    }
    if (selected.work_status === "offline") {
      showToast("业务已下线，请先上线");
      return;
    }

    setTriggering(true);
    setHint(`正在触发「${selected.name}」…`);
    try {
      const res = await runInspectionWork(selected.work_id);
      if (!res.ok) throw new Error(await readApiError(res));
      const data = (await res.json()) as {
        events_created?: number;
        warnings?: string[];
        tasks?: Array<{ mode?: string; detecttype?: number; algorithm_name?: string }>;
      };
      const n = data.events_created ?? 0;
      const warn = (data.warnings ?? []).filter(Boolean);
      const vaioTasks = (data.tasks ?? []).filter((t) => t.mode === "vaio");
      const vaioHint =
        vaioTasks.length > 0
          ? `VAIO ${vaioTasks.map((t) => `${t.algorithm_name ?? "算法"}(${t.detecttype})`).join("、")} · `
          : "";
      const summary =
        warn.length > 0
          ? `${vaioHint}执行完成：写入 ${n} 条事件；${warn.join("；")}`
          : `${vaioHint}执行完成：写入 ${n} 条事件，可在事件中心查看`;
      setHint(summary);
      showToast(summary);
    } catch (e) {
      setHint(String(e));
      showToast(String(e));
    } finally {
      setTriggering(false);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm(`确定删除「${selected.name}」？`)) return;

    const id = selected.work_id;
    const isNew = newWorkIds.has(id);
    try {
      if (!isNew) {
        const res = await deleteInspectionWork(id);
        if (!res.ok) throw new Error(await readApiError(res));
      }
      setWorks((list) => list.filter((w) => w.work_id !== id));
      setNewWorkIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      const remaining = filteredWorks.filter((w) => w.work_id !== id);
      setSelectedId(remaining[0]?.work_id ?? null);
      setDirty(false);
      setHint(`已删除「${selected.name}」`);
      showToast("已删除");
    } catch (e) {
      setHint(String(e));
      showToast(String(e));
    }
  };

  const handleNewManual = () => {
    if (dirty && !window.confirm("当前有未保存的更改，确定新建？")) return;
    const w = emptyInspectionWork();
    setWorks((list) => [w, ...list]);
    setSelectedId(w.work_id);
    setNewWorkIds((prev) => new Set(prev).add(w.work_id));
    setDirty(true);
  };

  const handleAiImport = (generated: InspectionWorkEntity[]) => {
    setWorks((list) => [...generated, ...list]);
    setNewWorkIds((prev) => {
      const next = new Set(prev);
      for (const w of generated) next.add(w.work_id);
      return next;
    });
    setSelectedId(generated[0]?.work_id ?? selectedId);
    setDirty(true);
    const note = `已导入 ${generated.length} 条 AI 巡检业务，请确认后保存`;
    setHint(note);
    showToast(note);
  };

  return (
    <div className="pf-scroll pf-studio-page">
      <header className="pf-studio-top-bar">
        <div className="pf-studio-top-left">
          <div className="pf-studio-title-block">
            <span className="pf-studio-title-mark" aria-hidden>◉</span>
            <h1>巡检业务</h1>
          </div>
          <div className="pf-studio-metrics" aria-label="概览统计">
            <span className="pf-studio-metric pf-studio-metric-blue"><strong>{works.length}</strong><em>巡检业务</em></span>
            <span className="pf-studio-metric pf-studio-metric-purple"><strong>{publishedRules.length}</strong><em>规范</em></span>
            <span className="pf-studio-metric pf-studio-metric-orange"><strong>{algorithms.length}</strong><em>算法</em></span>
            <span className="pf-studio-metric pf-studio-metric-green"><strong>{allEquipment.length}</strong><em>设备</em></span>
          </div>
          <span className="pf-studio-demo-tag">{loading ? "加载中" : "已接后端"}</span>
        </div>
        <div className="pf-studio-header-actions">
          <button type="button" className="pf-btn pf-btn-sm" onClick={() => setReportPushOpen(true)}>
            报告推送
          </button>
          <button type="button" className="pf-btn pf-btn-sm" onClick={() => setTrackingOpen(true)}>
            业务追踪
          </button>
          <button type="button" className="pf-btn pf-btn-sm" onClick={handleNewManual}>
            手动新建
          </button>
          <button type="button" className="pf-btn pf-btn-sm pf-btn-primary pf-studio-ai-trigger" onClick={() => setAiOpen(true)}>
            <span aria-hidden>✦</span> AI 生成
          </button>
        </div>
      </header>

      {statusMsg ? <div className="pf-kb-status">{statusMsg}</div> : null}

      <div className="pf-studio-layout">
        <aside className="pf-studio-panel pf-studio-list">
          <div className="pf-studio-panel-head">
            <h3>巡检业务列表</h3>
            <span className="pf-studio-count-badge">{filteredWorks.length}</span>
          </div>          <div className="pf-studio-list-search">
            <input
              type="search"
              className="pf-cell-input pf-studio-list-search-input"
              placeholder="搜索名称、区域、规范、设备…"
              value={workKeyword}
              onChange={(e) => setWorkKeyword(e.target.value)}
            />
            {workKeyword.trim() ? (
              <button type="button" className="pf-btn pf-btn-sm" onClick={() => setWorkKeyword("")}>
                清除
              </button>
            ) : null}
          </div>
          <div className="pf-studio-list-filters">
            <span className="pf-studio-list-filters-label">运行方式</span>
            <div className="pf-studio-list-filters-row">
              <button
                type="button"
                className={`pf-studio-filter-chip${listFilter === "all" ? " is-active" : ""}`}
                onClick={() => setListFilter("all")}
              >
                全部
              </button>
              {SCHEDULE_MODE_OPTIONS.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={`pf-studio-filter-chip${listFilter === o.id ? " is-active" : ""}`}
                  onClick={() => setListFilter(o.id)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <div className="pf-studio-list-filters">
            <span className="pf-studio-list-filters-label">运行状态</span>
            <div className="pf-studio-list-filters-row">
              {([
                { id: "all" as const, label: "全部" },
                { id: "online" as const, label: "运行中" },
                { id: "offline" as const, label: "已下线" },
              ]).map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={`pf-studio-filter-chip${workStatusFilter === o.id ? " is-active" : ""}`}
                  onClick={() => setWorkStatusFilter(o.id)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <ul className="pf-studio-work-list">
            {filteredWorks.length === 0 ? (
              <li className="pf-studio-work-empty">
                <p>{works.length === 0 ? "暂无巡检业务" : "无匹配巡检业务"}</p>
                <small>
                  {works.length === 0
                    ? "点击右上角 AI 生成，或手动新建"
                    : "请调整关键词或筛选条件"}
                </small>              </li>
            ) : (
              filteredWorks.map((w) => {
                const pct = workCompleteness(w);
                return (
                  <li key={w.work_id}>
                    <button
                      type="button"
                      className={`pf-studio-work-item${selectedId === w.work_id ? " is-active" : ""}`}
                      onClick={() => selectWork(w.work_id)}
                    >
                      <div className="pf-studio-work-item-top">
                        <strong className="pf-studio-work-item-title">
                          <span className="pf-studio-work-item-name">{w.name}</span>
                          {!newWorkIds.has(w.work_id) ? (
                            <span
                              className={`pf-studio-work-publish-tag${
                                publishedWorkIds.has(w.work_id) ? " is-published" : ""
                              }`}
                            >
                              {publishedWorkIds.has(w.work_id) ? "（已发布）" : "（未发布）"}
                            </span>
                          ) : (
                            <span className="pf-studio-work-publish-tag">（未发布）</span>
                          )}
                        </strong>
                        <div className="pf-studio-work-badges">
                          {newWorkIds.has(w.work_id) ? <Badge tone="warning">未保存</Badge> : null}
                        </div>
                      </div>
                      <div className="pf-studio-work-tags">
                        <Badge tone={scheduleBadgeTone(w.schedule_mode)}>{scheduleModeLabel(w.schedule_mode)}</Badge>
                        {w.region_name ? <Badge tone="default">{w.region_name}</Badge> : null}
                      </div>
                      <span className="pf-studio-work-meta">{workSummary(w)}</span>
                      <div className="pf-studio-work-progress" aria-hidden>
                        <span style={{ width: `${pct}%` }} />
                      </div>
                      <time className="pf-studio-work-time">{w.updated_at}</time>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </aside>

        <div className="pf-studio-main">
        <section className="pf-studio-panel pf-studio-editor">
          {!selected ? (
            <div className="pf-studio-empty-editor">
              <h3>选择或创建巡检业务</h3>
              <p>配置规范、算法、设备与时间检查方式</p>
              <button type="button" className="pf-btn pf-btn-primary" onClick={handleNewManual}>
                开始手动配置
              </button>
            </div>
          ) : (
            <div className="pf-studio-editor-body">
              <section className="pf-studio-zone pf-studio-zone-profile pf-studio-zone-compact">
                <div className="pf-studio-profile-top">
                  <input
                    className="pf-cell-input pf-studio-title-input"
                    value={selected.name}
                    onChange={(e) => patchSelected({ name: e.target.value })}
                    placeholder="巡检业务名称"
                  />
                  <div className="pf-studio-editor-actions">
                    {!newWorkIds.has(selected.work_id) ? (
                      <>
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm"
                          disabled={trackingBusy || dirty}
                          onClick={() => void handleToggleTrackingPublish()}
                        >
                          {trackingPublished ? "下架" : "发布"}
                        </button>
                        <button
                          type="button"
                          className={`pf-btn pf-btn-sm pf-studio-report-btn${reportTemplateBinding?.enabled && reportTemplateBinding.template_name ? " is-bound" : ""}`}
                          onClick={() => setReportTemplateOpen(true)}
                          title={
                            reportTemplateBinding?.enabled && reportTemplateBinding.template_name
                              ? `报告模版：${reportTemplateBinding.template_name}`
                              : "配置报告模版"
                          }
                        >
                          {reportTemplateButtonLabel}
                        </button>
                      </>
                    ) : null}
                    {selected.schedule_mode === "manual" &&
                    !dirty &&
                    !newWorkIds.has(selected.work_id) ? (
                      <button
                        type="button"
                        className="pf-btn pf-btn-sm pf-btn-trigger-work"
                        disabled={triggering || selected.work_status === "offline" || !trackingPublished}
                        title={!trackingPublished ? "请先发布业务到业务追踪" : undefined}
                        onClick={handleTriggerRun}
                      >
                        {triggering ? "执行中…" : "触发业务"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={`pf-btn pf-btn-sm pf-btn-primary${dirty ? " pf-studio-save-pulse" : ""}`}
                      disabled={!dirty}
                      onClick={handleSave}
                    >
                      {dirty ? "保存更改" : "已同步"}
                    </button>
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm pf-btn-danger-text"
                      onClick={handleDelete}
                    >
                      删除
                    </button>
                  </div>
                </div>
                <div className="pf-studio-editor-meta pf-studio-profile-meta">
                  {dirty ? <span className="pf-studio-unsaved">未保存</span> : null}
                  <span className="pf-studio-editor-id">ID · {selected.work_id}</span>
                  <button
                    type="button"
                    className={`pf-studio-filter-chip pf-studio-status-chip${selected.work_status === "offline" ? " is-offline" : " is-online"}`}
                    onClick={() =>
                      patchSelected({
                        work_status: selected.work_status === "offline" ? "online" : "offline",
                      })
                    }
                  >
                    {selected.work_status === "offline" ? "已下线" : "运行中"}
                  </button>
                </div>
                <textarea
                  className="pf-cell-textarea pf-studio-desc pf-studio-desc-compact"
                  value={selected.desc}
                  onChange={(e) => patchSelected({ desc: e.target.value })}
                  placeholder="巡检业务说明（可选）…"
                  rows={1}
                />
                {selected.ai_generation_trace ? (
                  <AiGenerationTracePanel trace={selected.ai_generation_trace} />
                ) : null}
              </section>

              <section className="pf-studio-zone pf-studio-zone-runtime pf-studio-zone-compact">
                <div className="pf-studio-runtime-row">
                  <div className="pf-studio-runtime-field pf-studio-runtime-region">
                    <span className="pf-studio-runtime-label">区域选择</span>
                    <RegionScopePicker
                      regionRows={regionRows}
                      deviceCountFor={equipCountFor}
                      selectedIds={selectedRegionIds}
                      onChange={patchSelectedRegions}
                      disabled={regionRows.length === 0}
                      placeholder="选择作用区域"
                    />
                  </div>
                  <div className="pf-studio-runtime-field pf-studio-runtime-schedule">
                    <span className="pf-studio-runtime-label">运行周期</span>
                    <div className="pf-studio-schedule-chips" role="radiogroup" aria-label="检查时间方式">
                      {SCHEDULE_MODE_OPTIONS.map((o) => (
                        <button
                          key={o.id}
                          type="button"
                          role="radio"
                          aria-checked={selected.schedule_mode === o.id}
                          className={`pf-studio-filter-chip${selected.schedule_mode === o.id ? " is-active" : ""}`}
                          onClick={() =>
                            patchSelected({
                              schedule_mode: o.id,
                              schedule_interval:
                                o.id === "periodic"
                                  ? selected.schedule_interval ?? "每日"
                                  : o.id === "continuous"
                                    ? CONTINUOUS_CHECK_INTERVAL_LABEL
                                    : undefined,
                              schedule_times: o.id === "scheduled" ? selected.schedule_times ?? "08:00" : undefined,
                            })
                          }
                        >
                          {o.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="pf-studio-schedule-detail pf-studio-schedule-detail-compact">
                  {selected.schedule_mode === "periodic" ? (
                    <label className="pf-studio-schedule-detail-field">
                      <span>周期间隔</span>
                      <select
                        className="pf-select"
                        value={selected.schedule_interval ?? "每日"}
                        onChange={(e) => patchSelected({ schedule_interval: e.target.value })}
                      >
                        {PERIODIC_INTERVAL_OPTIONS.map((x) => (
                          <option key={x} value={x}>
                            {x}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  {selected.schedule_mode === "scheduled" ? (
                    <label className="pf-studio-schedule-detail-field pf-studio-schedule-detail-field-grow">
                      <span>触发时刻</span>
                      <input
                        className="pf-cell-input"
                        value={selected.schedule_times ?? ""}
                        onChange={(e) => patchSelected({ schedule_times: e.target.value })}
                        placeholder="如 08:00, 14:00, 18:00"
                      />
                    </label>
                  ) : null}
                  {selected.schedule_mode === "continuous" ? (
                    <div className="pf-studio-schedule-detail-field pf-studio-schedule-continuous">
                      <span>检查间隔</span>
                      <strong>{CONTINUOUS_CHECK_INTERVAL_LABEL}</strong>
                      <span className="pf-studio-schedule-detail-note">
                        内置周期：每 {CONTINUOUS_ANALYSIS_WINDOW_SEC} 秒分析前{" "}
                        {CONTINUOUS_ANALYSIS_WINDOW_SEC} 秒摄像头/录像画面
                      </span>
                    </div>
                  ) : null}
                  {selected.schedule_mode === "manual" ? (
                    <span className="pf-studio-schedule-detail-note">无需额外调度参数</span>
                  ) : null}
                </div>
              </section>

              <section className="pf-studio-zone pf-studio-zone-run-rules pf-studio-zone-resources">
                <div className="pf-studio-zone-head pf-studio-zone-head-compact pf-studio-zone-run-rules-head">
                  <h4>运行规则</h4>
                  <p>规范、算法与设备编排</p>
                </div>
                <div className="pf-studio-pipeline pf-studio-pipeline-tabs" role="tablist" aria-label="运行规则配置">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={resourceTab === "rules"}
                    className={`pf-studio-pipe-step pf-studio-pipe-tab${selectedRuleIds.length ? " is-filled" : ""}${resourceTab === "rules" ? " is-active" : ""}`}
                    onClick={() => setResourceTab("rules")}
                  >
                    <span className="pf-studio-pipe-icon">📋</span>
                    <span>规范</span>
                    <strong>{selectedRuleIds.length}</strong>
                  </button>
                  <span className="pf-studio-pipe-arrow" aria-hidden />
                  <button
                    type="button"
                    role="tab"
                    aria-selected={resourceTab === "algos"}
                    className={`pf-studio-pipe-step pf-studio-pipe-tab${selectedAlgoIds.length ? " is-filled" : ""}${resourceTab === "algos" ? " is-active" : ""}`}
                    onClick={() => setResourceTab("algos")}
                  >
                    <span className="pf-studio-pipe-icon">🧠</span>
                    <span>算法</span>
                    <strong>{selectedAlgoIds.length}</strong>
                  </button>
                  <span className="pf-studio-pipe-arrow" aria-hidden />
                  <button
                    type="button"
                    role="tab"
                    aria-selected={resourceTab === "equip"}
                    className={`pf-studio-pipe-step pf-studio-pipe-tab${selectedEquipIds.length ? " is-filled" : ""}${resourceTab === "equip" ? " is-active" : ""}`}
                    onClick={() => setResourceTab("equip")}
                  >
                    <span className="pf-studio-pipe-icon">📡</span>
                    <span>设备</span>
                    <strong>{selectedEquipIds.length}</strong>
                  </button>
                </div>

                {resourceTab === "rules" ? (
                  <div className="pf-studio-resource-pane" role="tabpanel">
                    <div className="pf-studio-resource-block pf-studio-block-rules">
                      <div className="pf-studio-resource-toolbar">
                        <input
                          type="search"
                          className="pf-cell-input pf-studio-resource-search"
                          placeholder="关键词筛选：名称、场景、要求…"
                          value={ruleKeyword}
                          onChange={(e) => setRuleKeyword(e.target.value)}
                        />
                        {ruleKeyword.trim() ? (
                          <button
                            type="button"
                            className="pf-btn pf-btn-sm"
                            onClick={() => setRuleKeyword("")}
                          >
                            清除
                          </button>
                        ) : null}
                        <span className="pf-studio-resource-filter-meta">
                          已选 {selectedRuleIds.length}/{publishedRules.length}
                          {ruleKeyword.trim() ? ` · 匹配 ${filteredPublishedRules.length}` : ""}
                        </span>
                      </div>
                      <div className="pf-studio-resource-cards pf-studio-resource-cards-list">
                        {filteredPublishedRules.length === 0 ? (
                          <p className="pf-studio-resource-empty">
                            {publishedRules.length === 0
                              ? "暂无已发布规范，请先在知识库审核并发布"
                              : "无匹配规范，请调整关键词"}
                          </p>
                        ) : (
                          filteredPublishedRules.map((r) => (
                            <ResourceCard
                              key={r.id}
                              accent="purple"
                              icon="§"
                              title={r.name}
                              subtitle={r.scenario}
                              selected={selectedRuleIds.includes(r.id)}
                              onToggle={() => {
                                const next = toggleId(selectedRuleIds, r.id);
                                patchSelected({ rule_set: rebuildRuleSet(next, publishedRules) });
                              }}
                            />
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}

                {resourceTab === "algos" ? (
                  <div className="pf-studio-resource-pane" role="tabpanel">
                    <div className="pf-studio-resource-block pf-studio-block-algos">
                      <div className="pf-studio-resource-cards pf-studio-resource-cards-list">
                        {algorithms.length === 0 ? (
                          <p className="pf-studio-resource-empty">算法目录为空，请先在算法管理页导入</p>
                        ) : (
                          algorithms.map((a) => (
                            <ResourceCard
                              key={a.id}
                              accent="orange"
                              icon="◈"
                              title={a.name}
                              subtitle={a.description.slice(0, 80) || a.id}
                              selected={selectedAlgoIds.includes(a.id)}
                              onToggle={() => {
                                const next = toggleId(selectedAlgoIds, a.id);
                                patchSelected({ algorithm_set: rebuildAlgoSet(next, algorithms) });
                              }}
                            />
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}

                {resourceTab === "equip" && selected ? (
                  <div className="pf-studio-resource-pane" role="tabpanel">
                    <div className="pf-studio-resource-block pf-studio-block-equip">
                      <div className="pf-studio-equip-config-bar">
                        <span>已选 {selectedEquipIds.length} 台设备</span>
                        <span className="pf-studio-equip-config-bar-hint">
                          选中后在右侧横向浏览各算法状态，数量多时可左右滑动；点击「配置」调整参数并预览画面
                        </span>
                      </div>
                      <div className="pf-studio-equip-list">
                        {editorCameras.length === 0 && editorSensors.length === 0 ? (
                          <p className="pf-studio-resource-empty">
                            {editorScopeRegionIds
                              ? "当前所选区域范围内暂无设备，请调整区域或在区域配置中添加"
                              : "暂无设备，请先在区域配置中导入"}
                          </p>
                        ) : null}
                        {editorCameras.map((c) => (
                          <EquipmentSelectRow
                            key={c.id}
                            work={selected}
                            deviceId={c.id}
                            accent="blue"
                            icon="📹"
                            name={c.name}
                            subtitle={`${c.regionName} · ${c.online ? "在线" : "离线"}`}
                            selected={selectedEquipIds.includes(c.id)}
                            onToggle={() => {
                              const next = toggleId(selectedEquipIds, c.id);
                              patchEquipment(next);
                            }}
                            onConfigure={() => setConfigEquipId(c.id)}
                          />
                        ))}
                        {editorSensors.map((s) => (
                          <EquipmentSelectRow
                            key={s.id}
                            work={selected}
                            deviceId={s.id}
                            accent="green"
                            icon="📊"
                            name={s.name}
                            subtitle={`${s.regionName} · ${s.dataType}`}
                            selected={selectedEquipIds.includes(s.id)}
                            onToggle={() => {
                              const next = toggleId(selectedEquipIds, s.id);
                              patchEquipment(next);
                            }}
                            onConfigure={() => setConfigEquipId(s.id)}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                ) : null}
              </section>
            </div>
          )}
        </section>
        </div>
      </div>

      {toast ? <div className="pf-studio-toast">{toast}</div> : null}

      <AiWorkComposerModal
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        onImport={handleAiImport}
        regions={regionRows}
        rules={publishedRules}
        algorithms={algorithms}
        cameras={cameras}
        sensors={sensors}
      />

      {selected ? (
        <WorkReportTemplateBindModal
          open={reportTemplateOpen}
          onClose={() => setReportTemplateOpen(false)}
          workId={selected.work_id}
          workName={selected.name}
          workSaved={!newWorkIds.has(selected.work_id)}
          onBindingChange={setReportTemplateBinding}
          onSaved={(_binding, message) => showToast(message)}
        />
      ) : null}

      <WorkTrackingModal open={trackingOpen} onClose={() => setTrackingOpen(false)} />

      <ReportPushModal
        open={reportPushOpen}
        onClose={() => setReportPushOpen(false)}
        works={works}
        onSaved={(message) => showToast(message)}
      />

      {selected && configEquipId ? (
        <EquipmentAlgoConfigModal
          open={Boolean(configEquipId)}
          work={selected}
          equipmentId={configEquipId}
          cameras={cameras}
          sensors={sensors}
          equipmentName={
            selected.equipment_set.find((e) => e.equipment_id === configEquipId)?.name ??
            configEquipId
          }
          equipmentRole={selected.equipment_set.find((e) => e.equipment_id === configEquipId)?.role}
          onClose={() => setConfigEquipId(null)}
          onSave={(params) => {
            patchSelected({ equipment_algo_params: params });
            setConfigEquipId(null);
            const name =
              selected.equipment_set.find((e) => e.equipment_id === configEquipId)?.name ?? "设备";
            showToast(`已保存「${name}」的算法参数`);
          }}
        />
      ) : null}
    </div>  );
}
