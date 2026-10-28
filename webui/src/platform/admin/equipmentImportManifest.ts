/** 与后端 equipment/builtin_seed.json 一致的导入预览（仅用于弹窗展示） */
export type EquipmentImportPreviewRow = {
  id: string;
  kind: "camera" | "sensor";
  name: string;
  regionId: string;
  regionName: string;
  online: boolean;
};

export const EQUIPMENT_IMPORT_MANIFEST = {
  packageName: "物业演示设备包",
  description: "预置摄像头与传感器，已按园区区域绑定 region_id，导入后可在左侧区域树中直接查看。",
  cameras: 10,
  sensors: 8,
  total: 18,
  rows: [
    { id: "cam-001", kind: "camera", name: "A座大堂主入口", regionId: "r1a", regionName: "A座大堂与公区", online: true },
    { id: "cam-002", kind: "camera", name: "A座电梯厅", regionId: "r1a", regionName: "A座大堂与公区", online: true },
    { id: "sen-001", kind: "sensor", name: "A座大堂温湿度", regionId: "r1a", regionName: "A座大堂与公区", online: true },
    { id: "cam-003", kind: "camera", name: "A座配电间", regionId: "r1b", regionName: "A座设备夹层", online: true },
    { id: "cam-010", kind: "camera", name: "A座屋面设备区", regionId: "r1b", regionName: "A座设备夹层", online: false },
    { id: "sen-002", kind: "sensor", name: "配电间烟雾", regionId: "r1b", regionName: "A座设备夹层", online: true },
    { id: "sen-007", kind: "sensor", name: "水泵房管网压力", regionId: "r1b", regionName: "A座设备夹层", online: true },
    { id: "sen-008", kind: "sensor", name: "屋面水箱液位", regionId: "r1b", regionName: "A座设备夹层", online: true },
    { id: "cam-004", kind: "camera", name: "B座一层中庭", regionId: "r2", regionName: "B座商业裙楼", online: true },
    { id: "cam-005", kind: "camera", name: "B座卸货平台", regionId: "r2", regionName: "B座商业裙楼", online: true },
    { id: "sen-005", kind: "sensor", name: "B座餐厨油烟", regionId: "r2", regionName: "B座商业裙楼", online: true },
    { id: "cam-006", kind: "camera", name: "地库B1入口", regionId: "r3", regionName: "地下停车场", online: true },
    { id: "cam-007", kind: "camera", name: "地库B2消防通道", regionId: "r3", regionName: "地下停车场", online: true },
    { id: "sen-003", kind: "sensor", name: "地库CO浓度", regionId: "r3", regionName: "地下停车场", online: true },
    { id: "sen-004", kind: "sensor", name: "地库照度", regionId: "r3", regionName: "地下停车场", online: true },
    { id: "cam-008", kind: "camera", name: "园区东门岗", regionId: "r4", regionName: "园区外围与卸货区", online: true },
    { id: "cam-009", kind: "camera", name: "卸货区月台", regionId: "r4", regionName: "园区外围与卸货区", online: true },
    { id: "sen-006", kind: "sensor", name: "园区边界噪声", regionId: "r4", regionName: "园区外围与卸货区", online: true },
  ] as EquipmentImportPreviewRow[],
};

export function groupImportPreviewByRegion(rows: EquipmentImportPreviewRow[]) {
  const map = new Map<string, { regionName: string; cameras: number; sensors: number; items: EquipmentImportPreviewRow[] }>();
  for (const row of rows) {
    let group = map.get(row.regionId);
    if (!group) {
      group = { regionName: row.regionName, cameras: 0, sensors: 0, items: [] };
      map.set(row.regionId, group);
    }
    if (row.kind === "camera") group.cameras += 1;
    else group.sensors += 1;
    group.items.push(row);
  }
  return [...map.entries()].map(([regionId, g]) => ({ regionId, ...g }));
}
