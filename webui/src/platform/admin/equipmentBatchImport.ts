/** 批量设备导入：CSV 解析与模板生成（区域配置模块） */

export type EquipmentBatchRow = {
  id?: string;
  name: string;
  kind: string;
  description: string;
  region_id: string;
};

const HEADER_MAP: Record<string, keyof EquipmentBatchRow> = {
  id: "id",
  "设备id": "id",
  "设备编号": "id",
  "名称": "name",
  "设备名称": "name",
  name: "name",
  "类型": "kind",
  "设备类型": "kind",
  kind: "kind",
  "描述": "description",
  "说明": "description",
  description: "description",
  "所属区域id": "region_id",
  "所属区域": "region_id",
  "区域id": "region_id",
  region_id: "region_id",
};

export function normalizeEquipmentKind(raw: string): "camera" | "sensor" {
  const s = raw.trim().toLowerCase();
  if (s === "sensor" || s === "传感器" || s === "传感") return "sensor";
  return "camera";
}

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (ch === "," && !inQuotes) {
      out.push(cur.trim());
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur.trim());
  return out;
}

export function parseEquipmentCsv(
  text: string,
  defaultRegionId = "",
): { rows: EquipmentBatchRow[]; errors: string[] } {
  const errors: string[] = [];
  const normalized = text.replace(/^\uFEFF/, "").trim();
  if (!normalized) {
    return { rows: [], errors: ["文件内容为空"] };
  }
  const lines = normalized.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) {
    return { rows: [], errors: ["至少需要表头与一行数据"] };
  }
  const headerCells = splitCsvLine(lines[0]).map((h) => h.trim().toLowerCase());
  const colKeys: Array<keyof EquipmentBatchRow | null> = headerCells.map((h) => HEADER_MAP[h] ?? null);
  if (!colKeys.includes("name")) {
    return { rows: [], errors: ["缺少「设备名称」列（或 name）"] };
  }
  const rows: EquipmentBatchRow[] = [];
  for (let li = 1; li < lines.length; li += 1) {
    const cells = splitCsvLine(lines[li]);
    if (cells.every((c) => !c.trim())) continue;
    const row: EquipmentBatchRow = {
      name: "",
      kind: "camera",
      description: "",
      region_id: defaultRegionId,
    };
    colKeys.forEach((key, idx) => {
      if (!key) return;
      const val = (cells[idx] ?? "").trim();
      if (key === "kind") row.kind = normalizeEquipmentKind(val || "camera");
      else if (key === "id") row.id = val || undefined;
      else row[key] = val;
    });
    if (!row.name) {
      errors.push(`第 ${li + 1} 行：设备名称不能为空`);
      continue;
    }
    if (!row.region_id) {
      errors.push(`第 ${li + 1} 行：所属区域 id 不能为空`);
      continue;
    }
    rows.push(row);
  }
  return { rows, errors };
}

export const EQUIPMENT_IMPORT_TEMPLATE_CSV = `id,设备名称,类型,描述,所属区域id
,东门岗摄像头01,摄像头,园区东门岗全景画面,r4
,地库温感01,传感器,B1卸货口温度监测,r3`;

export function downloadEquipmentImportTemplate(filename = "equipment-import-template.csv") {
  const blob = new Blob(["\uFEFF", EQUIPMENT_IMPORT_TEMPLATE_CSV], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
