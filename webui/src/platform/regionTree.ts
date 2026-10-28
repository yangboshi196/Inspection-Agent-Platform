import type { RegionRow } from "./regionApi";

export type RegionTreeNode = RegionRow & {
  depth: number;
  deviceCount: number;
  subtreeDeviceCount: number;
  childCount: number;
  children: RegionTreeNode[];
};

export function buildRegionTree(
  rows: RegionRow[],
  deviceCountFor: (id: string) => number,
): RegionTreeNode[] {
  const map = new Map<string, RegionTreeNode>();
  for (const row of rows) {
    map.set(row.id, {
      ...row,
      parent_id: row.parent_id ?? "",
      sort_order: row.sort_order ?? 0,
      depth: 0,
      deviceCount: deviceCountFor(row.id),
      subtreeDeviceCount: 0,
      childCount: 0,
      children: [],
    });
  }

  const roots: RegionTreeNode[] = [];
  for (const node of map.values()) {
    const parentId = node.parent_id.trim();
    const parent = parentId ? map.get(parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }

  const sortNodes = (list: RegionTreeNode[]) => {
    list.sort(
      (a, b) =>
        (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
        a.name.localeCompare(b.name, "zh-CN") ||
        a.id.localeCompare(b.id),
    );
    for (const child of list) sortNodes(child.children);
  };
  sortNodes(roots);

  const assignDepth = (nodes: RegionTreeNode[], depth: number) => {
    for (const node of nodes) {
      node.depth = depth;
      node.childCount = node.children.length;
      assignDepth(node.children, depth + 1);
    }
  };
  assignDepth(roots, 0);

  const computeSubtree = (node: RegionTreeNode): number => {
    node.subtreeDeviceCount =
      node.deviceCount + node.children.reduce((sum, child) => sum + computeSubtree(child), 0);
    return node.subtreeDeviceCount;
  };
  for (const root of roots) computeSubtree(root);

  return roots;
}

export function flattenRegionTree(roots: RegionTreeNode[]): RegionTreeNode[] {
  const out: RegionTreeNode[] = [];
  const walk = (nodes: RegionTreeNode[]) => {
    for (const node of nodes) {
      out.push(node);
      walk(node.children);
    }
  };
  walk(roots);
  return out;
}

/** 按折叠状态展开树：collapsedIds 中的节点不展示其子孙 */
export function flattenRegionTreeWithCollapse(
  roots: RegionTreeNode[],
  collapsedIds: ReadonlySet<string>,
): RegionTreeNode[] {
  const out: RegionTreeNode[] = [];
  const walk = (nodes: RegionTreeNode[]) => {
    for (const node of nodes) {
      out.push(node);
      if (node.children.length > 0 && !collapsedIds.has(node.id)) {
        walk(node.children);
      }
    }
  };
  walk(roots);
  return out;
}

export function findRegionTreeNode(roots: RegionTreeNode[], regionId: string): RegionTreeNode | null {
  for (const node of flattenRegionTree(roots)) {
    if (node.id === regionId) return node;
  }
  return null;
}

/** 选中区域及其全部下级区域 id（用于汇总展示设备） */
export function collectRegionScopeIds(node: RegionTreeNode | null): string[] {
  if (!node) return [];
  const ids: string[] = [];
  const walk = (current: RegionTreeNode) => {
    ids.push(current.id);
    for (const child of current.children) walk(child);
  };
  walk(node);
  return ids;
}

export function parentRegionName(rows: RegionRow[], parentId: string | undefined): string {
  const pid = parentId?.trim();
  if (!pid) return "顶级区域";
  return rows.find((r) => r.id === pid)?.name ?? pid;
}
