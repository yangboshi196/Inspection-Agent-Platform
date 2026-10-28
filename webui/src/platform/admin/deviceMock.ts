import { MOCK_REGIONS, MOCK_INSPECTION_WORKS } from "../mockData";
import type { CameraDevice, SensorDevice } from "../types";

export const DEVICE_REGIONS = MOCK_REGIONS.filter((r) => r.id !== "r0");

export type DeviceKind = "camera" | "sensor";

export type DeviceListItem = {
  id: string;
  kind: DeviceKind;
  name: string;
  description: string;
  regionId: string;
  regionName: string;
  online: boolean;
  subLabel: string;
};

export function regionNameOf(regionId: string) {
  return DEVICE_REGIONS.find((r) => r.id === regionId)?.name ?? regionId;
}

export function toDeviceList(cameras: CameraDevice[], sensors: SensorDevice[]): DeviceListItem[] {
  const cams = cameras.map((c) => ({
    id: c.id,
    kind: "camera" as const,
    name: c.name,
    description: c.description,
    regionId: c.regionId,
    regionName: c.regionName,
    online: c.online,
    subLabel: "视频流",
  }));
  const sens = sensors.map((s) => ({
    id: s.id,
    kind: "sensor" as const,
    name: s.name,
    description: s.description,
    regionId: s.regionId,
    regionName: s.regionName,
    online: s.online,
    subLabel: s.dataType,
  }));
  return [...cams, ...sens];
}

export function deviceStats(cameras: CameraDevice[], sensors: SensorDevice[]) {
  const all = [...cameras, ...sensors];
  return {
    total: all.length,
    cameras: cameras.length,
    sensors: sensors.length,
    online: all.filter((d) => d.online).length,
    offline: all.filter((d) => !d.online).length,
  };
}

export function kindLabel(kind: DeviceKind) {
  return kind === "camera" ? "摄像头" : "传感器";
}

export function regionDeviceCount(
  cameras: CameraDevice[],
  sensors: SensorDevice[],
  regionId: string,
) {
  if (regionId === "all") return cameras.length + sensors.length;
  return cameras.filter((c) => c.regionId === regionId).length + sensors.filter((s) => s.regionId === regionId).length;
}

export function linkedInspectionWorks(deviceId: string) {
  return MOCK_INSPECTION_WORKS.filter((w) => w.equipment_set.some((e) => e.equipment_id === deviceId));
}
