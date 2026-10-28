import { listRegions, postRegion, readApiError, deleteRegion as apiDeleteRegion } from "../api";
import { getAuthToken } from "./auth";
import {
  getCachedRegions,
  normalizeRegionRows,
  setCachedRegions,
  type RegionRow,
} from "./regionCache";
import { fetchSessionBootstrap } from "./sessionBootstrap";

const DEMO_REGIONS: Array<{
  id: string;
  name: string;
  desc: string;
  parent_id: string;
  sort_order: number;
}> = [
  {
    id: "r0",
    name: "星河智慧物业 · 示范园区",
    desc: "物业服务根区域，下辖写字楼、商业、地库及外围子区域。",
    parent_id: "",
    sort_order: 0,
  },
  {
    id: "r1",
    name: "A座写字楼",
    desc: "甲级写字楼主体，含大堂公区、电梯厅与设备夹层。",
    parent_id: "r0",
    sort_order: 1,
  },
  {
    id: "r1a",
    name: "A座大堂与公区",
    desc: "访客接待、前台、电梯厅及公共走廊。",
    parent_id: "r1",
    sort_order: 1,
  },
  {
    id: "r1b",
    name: "A座设备夹层",
    desc: "配电间、水泵房、屋面设备与强弱电机房。",
    parent_id: "r1",
    sort_order: 2,
  },
  {
    id: "r2",
    name: "B座商业裙楼",
    desc: "餐饮零售、中庭活动区及卸货平台。",
    parent_id: "r0",
    sort_order: 2,
  },
  {
    id: "r3",
    name: "地下停车场",
    desc: "B1/B2 停车层、车行通道与出入口。",
    parent_id: "r0",
    sort_order: 3,
  },
  {
    id: "r4",
    name: "园区外围与卸货区",
    desc: "东门岗、园区道路、卸货月台及绿化带。",
    parent_id: "r0",
    sort_order: 4,
  },
];

let regionsInflight: Promise<RegionRow[]> | null = null;

export type { RegionRow };

export async function loadRegions(options?: { seedIfEmpty?: boolean; force?: boolean }): Promise<RegionRow[]> {
  if (!options?.force) {
    const cached = getCachedRegions();
    if (cached?.length) return cached;
  }
  if (!regionsInflight) {
    regionsInflight = loadRegionsInner(options).finally(() => {
      regionsInflight = null;
    });
  }
  return regionsInflight;
}

async function loadRegionsInner(options?: { seedIfEmpty?: boolean; force?: boolean }): Promise<RegionRow[]> {
  if (!options?.force && getAuthToken()) {
    try {
      const boot = await fetchSessionBootstrap();
      if (boot.regions.length) return boot.regions;
    } catch {
      /* 回退到 /region/ */
    }
  }

  const res = await listRegions();
  if (!res.ok) throw new Error(await readApiError(res));
  let rows = (await res.json()) as RegionRow[];
  if (rows.length === 0 && options?.seedIfEmpty !== false) {
    await Promise.all(
      DEMO_REGIONS.map(async (r) => {
        const createRes = await postRegion({
          id: r.id,
          name: r.name,
          desc: r.desc,
          parent_id: r.parent_id,
          sort_order: r.sort_order,
        });
        if (createRes.ok || createRes.status === 409) return;
      }),
    );
    const again = await listRegions();
    if (!again.ok) throw new Error(await readApiError(again));
    rows = (await again.json()) as RegionRow[];
  }
  const normalized = normalizeRegionRows(rows);
  setCachedRegions(normalized);
  return normalized;
}

export function regionNameMap(rows: RegionRow[]): Record<string, string> {
  return Object.fromEntries(rows.map((r) => [r.id, r.name]));
}

export async function removeRegion(regionId: string): Promise<void> {
  const res = await apiDeleteRegion(regionId);
  if (!res.ok && res.status !== 204) {
    throw new Error(await readApiError(res));
  }
}
