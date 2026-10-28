import type { RegionRow } from "../regionApi";

/** URL 查询参数：显式创建顶级区域（无 parent_id） */
export const REGION_PARENT_ROOT = "__root__";

/** 从列表页跳转到新建页时，带上当前选中的上级区域 id */
export function buildNewRegionPath(selectedRegionId: string | null): string {
  if (selectedRegionId) {
    return `/admin/regions/new?parent=${encodeURIComponent(selectedRegionId)}`;
  }
  return `/admin/regions/new?parent=${REGION_PARENT_ROOT}`;
}

/**
 * 解析新建页 parent 查询参数。
 * - `__root__` 或缺失且未选中 → 顶级（parent_id 为空）
 * - 合法区域 id → 作为上级
 */
export function resolveInitialParentId(
  parentQuery: string | null,
  regions: RegionRow[],
): string {
  const raw = (parentQuery ?? "").trim();
  if (!raw || raw === REGION_PARENT_ROOT) {
    return "";
  }
  if (regions.some((r) => r.id === raw)) {
    return raw;
  }
  return "";
}

/** 根据同级子区域数量建议下一个 sort_order（新建时默认值） */
export function suggestSortOrder(parentId: string, regions: RegionRow[]): number {
  const siblings = regions.filter((r) => (r.parent_id ?? "").trim() === parentId.trim());
  if (siblings.length === 0) return 0;
  return Math.max(...siblings.map((r) => r.sort_order ?? 0)) + 1;
}
