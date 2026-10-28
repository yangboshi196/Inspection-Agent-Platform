import type { AlgorithmItem, CameraDevice, KnowledgeRule, Region, SensorDevice } from "./types";
import {
  MOCK_ALGORITHMS,
  MOCK_CAMERAS,
  MOCK_REGIONS,
  MOCK_RULES,
  MOCK_SENSORS,
} from "./mockData";

export function getOperableRegions(): Region[] {
  return MOCK_REGIONS.filter((r) => r.id !== "r0");
}

export function getRegionById(regionId: string): Region | undefined {
  return MOCK_REGIONS.find((r) => r.id === regionId);
}

/** 规范是否适用于该区域（MVP：已发布规范全局可用，区域由巡检业务设备推导） */
export function ruleAppliesToRegion(rule: KnowledgeRule, _regionId: string): boolean {
  return rule.status === "published";
}

export function getRegionRules(_regionId: string): KnowledgeRule[] {
  return MOCK_RULES.filter((r) => r.status === "published");
}

export function getRegionCameras(regionId: string): CameraDevice[] {
  return MOCK_CAMERAS.filter((c) => c.regionId === regionId);
}

export function getRegionSensors(regionId: string): SensorDevice[] {
  return MOCK_SENSORS.filter((s) => s.regionId === regionId);
}

/** 平台算法目录；标记本区域规范是否推荐 */
export function getRegionAlgorithms(regionId: string): Array<
  AlgorithmItem & { recommended: boolean; recommendedBy: string[] }
> {
  const rules = getRegionRules(regionId).filter((r) => r.status === "published");
  return MOCK_ALGORITHMS.map((algo) => {
    const recommendedBy = rules
      .filter((r) => r.recommendedAlgorithms.some((n) => n === algo.name || algo.name.includes(n) || n.includes(algo.name)))
      .map((r) => r.name);
    return { ...algo, recommended: recommendedBy.length > 0, recommendedBy };
  });
}

export type RegionConfigSnapshot = {
  region: Region;
  rules: KnowledgeRule[];
  publishedRuleCount: number;
  cameras: CameraDevice[];
  sensors: SensorDevice[];
  onlineDeviceCount: number;
  algorithms: ReturnType<typeof getRegionAlgorithms>;
  recommendedAlgoCount: number;
};

export function getRegionConfigSnapshot(regionId: string): RegionConfigSnapshot | null {
  const region = getRegionById(regionId);
  if (!region) return null;
  const rules = getRegionRules(regionId);
  const cameras = getRegionCameras(regionId);
  const sensors = getRegionSensors(regionId);
  const algorithms = getRegionAlgorithms(regionId);
  return {
    region,
    rules,
    publishedRuleCount: rules.filter((r) => r.status === "published").length,
    cameras,
    sensors,
    onlineDeviceCount:
      cameras.filter((c) => c.online).length + sensors.filter((s) => s.online).length,
    algorithms,
    recommendedAlgoCount: algorithms.filter((a) => a.recommended).length,
  };
}
