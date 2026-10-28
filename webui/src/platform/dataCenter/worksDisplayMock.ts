import { MOCK_CAMERAS, MOCK_INSPECTION_WORKS } from "../mockData";
import type { InspectionWorkEntity } from "../types";
import { DC_WORK_RUNTIME, type WorkRuntimeStatus } from "./dataCenterMock";

export type WorkRunPhase = "running" | "idle" | "paused";

export type WorkCameraBinding = {
  cameraId: string;
  cameraName: string;
  regionId: string;
  regionName: string;
  algorithmIds: string[];
  ruleIds: string[];
};

export type WorkRegionBinding = {
  regionId: string;
  regionName: string;
  cameras: WorkCameraBinding[];
};

export type WorkDisplayDetail = {
  workId: string;
  work: InspectionWorkEntity;
  runtime: WorkRuntimeStatus;
  runPhase: WorkRunPhase;
  regions: WorkRegionBinding[];
};

type CameraSeed = {
  cameraId: string;
  algorithmIds: string[];
  ruleIds: string[];
};

const CAMERA_SEEDS: Record<string, CameraSeed[]> = {
  "iw-1": [
    { cameraId: "cam-001", algorithmIds: ["algo-1"], ruleIds: ["rule-2"] },
    { cameraId: "cam-002", algorithmIds: ["algo-1", "algo-2"], ruleIds: ["rule-1", "rule-2"] },
  ],
  "iw-2": [
    { cameraId: "cam-006", algorithmIds: ["algo-5"], ruleIds: ["rule-3"] },
    { cameraId: "cam-007", algorithmIds: ["algo-2"], ruleIds: ["rule-3", "rule-4"] },
  ],
  "iw-3": [
    { cameraId: "cam-004", algorithmIds: ["algo-6", "algo-4"], ruleIds: ["rule-5"] },
  ],
  "iw-4": [
    { cameraId: "cam-003", algorithmIds: ["algo-3", "algo-7"], ruleIds: ["rule-6"] },
  ],
  "iw-5": [
    { cameraId: "cam-008", algorithmIds: ["algo-1", "algo-3"], ruleIds: ["rule-2"] },
    { cameraId: "cam-009", algorithmIds: ["algo-5"], ruleIds: ["rule-3", "rule-5"] },
  ],
};

const RUN_PHASE: Record<string, WorkRunPhase> = {
  "iw-1": "running",
  "iw-2": "running",
  "iw-3": "running",
  "iw-4": "idle",
  "iw-5": "running",
};

function buildRegions(work: InspectionWorkEntity, seeds: CameraSeed[]): WorkRegionBinding[] {
  const regionMap = new Map<string, WorkRegionBinding>();
  for (const seed of seeds) {
    const cam = MOCK_CAMERAS.find((c) => c.id === seed.cameraId);
    if (!cam) continue;
    const binding: WorkCameraBinding = {
      cameraId: cam.id,
      cameraName: cam.name,
      regionId: cam.regionId,
      regionName: cam.regionName,
      algorithmIds: [...seed.algorithmIds],
      ruleIds: [...seed.ruleIds],
    };
    let region = regionMap.get(cam.regionId);
    if (!region) {
      region = { regionId: cam.regionId, regionName: cam.regionName, cameras: [] };
      regionMap.set(cam.regionId, region);
    }
    region.cameras.push(binding);
  }
  return [...regionMap.values()];
}

export function buildWorkDisplayDetail(work: InspectionWorkEntity): WorkDisplayDetail {
  const runtime = DC_WORK_RUNTIME.find((r) => r.workId === work.work_id)!;
  const seeds =
    CAMERA_SEEDS[work.work_id] ??
    work.equipment_set
      .filter((e) => e.role === "camera")
      .map((e, i) => ({
        cameraId: e.equipment_id,
        algorithmIds: i === 0 ? work.algorithm_set.map((a) => a.algorithm_id) : [],
        ruleIds: i === 0 ? work.rule_set.map((r) => r.rule_id) : [],
      }));

  return {
    workId: work.work_id,
    work,
    runtime,
    runPhase: RUN_PHASE[work.work_id] ?? (work.schedule_mode === "continuous" ? "running" : "idle"),
    regions: buildRegions(work, seeds),
  };
}

export function initialWorkDisplayDetails(): WorkDisplayDetail[] {
  return MOCK_INSPECTION_WORKS.map(buildWorkDisplayDetail);
}

export function runPhaseLabel(phase: WorkRunPhase) {
  if (phase === "running") return "进行中";
  if (phase === "paused") return "已暂停";
  return "空闲";
}

export function runPhaseTone(phase: WorkRunPhase): "success" | "info" | "warning" | "default" {
  if (phase === "running") return "success";
  if (phase === "paused") return "warning";
  return "default";
}

export function scheduleTimeDescription(work: InspectionWorkEntity) {
  if (work.schedule_mode === "periodic") return work.schedule_interval ?? "—";
  if (work.schedule_mode === "scheduled") return work.schedule_times ?? "—";
  if (work.schedule_mode === "continuous") return "7×24 持续运行";
  return "手动触发，无固定计划";
}

export function resolveAlgoNames(work: InspectionWorkEntity, ids: string[]) {
  return ids.map((id) => ({ id, name: work.algorithm_set.find((a) => a.algorithm_id === id)?.name ?? id }));
}

export function resolveRuleNames(work: InspectionWorkEntity, ids: string[]) {
  return ids.map((id) => ({ id, name: work.rule_set.find((r) => r.rule_id === id)?.name ?? id }));
}

export function mergedWorkStats(details: WorkDisplayDetail[]) {
  const works = details.map((d) => d.work);
  return {
    total: details.length,
    periodic: works.filter((w) => w.schedule_mode === "periodic").length,
    scheduled: works.filter((w) => w.schedule_mode === "scheduled").length,
    continuous: works.filter((w) => w.schedule_mode === "continuous").length,
    manual: works.filter((w) => w.schedule_mode === "manual").length,
    ai: works.filter((w) => w.source === "ai").length,
    running: details.filter((d) => d.runPhase === "running").length,
    healthy: details.filter((d) => d.runtime.health === "healthy").length,
    warning: details.filter((d) => d.runtime.health === "warning" || d.runtime.health === "critical").length,
    idle: details.filter((d) => d.runtime.health === "idle").length,
    avgCompliance: details.length
      ? Math.round(details.reduce((a, d) => a + d.runtime.compliance, 0) / details.length)
      : 0,
  };
}
