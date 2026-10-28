export type RegionRow = {
  id: string;
  name: string;
  desc: string;
  parent_id?: string;
  sort_order?: number;
  created_at?: string;
};

const REGIONS_CACHE_KEY = "SIA_regions_cache";

export function normalizeRegionRows(rows: RegionRow[]): RegionRow[] {
  return rows.map((r) => ({
    ...r,
    parent_id: r.parent_id ?? "",
    sort_order: r.sort_order ?? 0,
  }));
}

export function getCachedRegions(): RegionRow[] | null {
  try {
    const raw = localStorage.getItem(REGIONS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as RegionRow[];
    return parsed.length ? normalizeRegionRows(parsed) : null;
  } catch {
    return null;
  }
}

export function setCachedRegions(rows: RegionRow[]): void {
  localStorage.setItem(REGIONS_CACHE_KEY, JSON.stringify(normalizeRegionRows(rows)));
}

export function clearCachedRegions(): void {
  localStorage.removeItem(REGIONS_CACHE_KEY);
}
