import { listInspectionWorks, readApiError } from "../../api";
import { loadCamerasAndSensors } from "../equipmentApi";
import { apiRowToInspectionWork } from "../inspectionWorkApi";
import { loadRegions, regionNameMap } from "../regionApi";
import type { CameraDevice, InspectionWorkEntity } from "../types";
import { apiRowToWorkRuntime, loadWorkRuntimeRows } from "./inspectionEventApi";
import type { WorkRuntimeStatus } from "./dataCenterMock";
import type {
  WorkCameraBinding,
  WorkDisplayDetail,
  WorkRegionBinding,
  WorkRunPhase,
} from "./worksDisplayMock";

function buildRegions(work: InspectionWorkEntity, cameras: CameraDevice[]): WorkRegionBinding[] {
  const regionMap = new Map<string, WorkRegionBinding>();
  const cameraEquip = work.equipment_set.filter((e) => e.role === "camera" || !e.role);
  const algoIds = work.algorithm_set.map((a) => a.algorithm_id);
  const ruleIds = work.rule_set.map((r) => r.rule_id);

  for (const equip of cameraEquip) {
    const cam = cameras.find((c) => c.id === equip.equipment_id);
    if (!cam) continue;
    const binding: WorkCameraBinding = {
      cameraId: cam.id,
      cameraName: cam.name,
      regionId: cam.regionId,
      regionName: cam.regionName,
      algorithmIds: [...algoIds],
      ruleIds: [...ruleIds],
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

function inferRunPhase(
  work: InspectionWorkEntity,
  runtime: WorkRuntimeStatus,
  pendingEvents: number,
): WorkRunPhase {
  if (work.schedule_mode === "manual") return pendingEvents > 0 ? "running" : "idle";
  if (work.schedule_mode === "continuous") return "running";
  if (runtime.health === "idle") return "idle";
  return "running";
}

export async function loadWorkDisplayDetails(): Promise<WorkDisplayDetail[]> {
  const regions = await loadRegions();
  const names = regionNameMap(regions);
  const equip = await loadCamerasAndSensors((id) => names[id] || id);

  const worksRes = await listInspectionWorks(undefined, 200);
  if (!worksRes.ok) throw new Error(await readApiError(worksRes));
  const worksBody = (await worksRes.json()) as { items: Record<string, unknown>[] };
  const works = worksBody.items.map((row) => {
    const w = apiRowToInspectionWork(row);
    if (!w.region_name && w.region_id) {
      w.region_name = names[w.region_id] || w.region_id;
    }
    return w;
  });

  const runtimeRows = await loadWorkRuntimeRows();

  return works.map((work) => {
    const runtimeRow = runtimeRows.find((r) => r.work_id === work.work_id);
    const runtime: WorkRuntimeStatus =
      runtimeRow != null
        ? apiRowToWorkRuntime(runtimeRow)
        : {
            workId: work.work_id,
            name: work.name,
            regionName: work.region_name,
            scheduleMode: work.schedule_mode,
            health: work.schedule_mode === "manual" ? "idle" : "healthy",
            lastRun: work.updated_at,
            nextRun: work.schedule_mode === "continuous" ? "持续运行" : "—",
            compliance: 90,
            alerts7d: 0,
            alertResolutionRate: 100,
          };

    return {
      workId: work.work_id,
      work,
      runtime,
      runPhase: inferRunPhase(work, runtime, runtimeRow?.pending_events ?? 0),
      regions: buildRegions(work, equip.cameras),
    };
  });
}
