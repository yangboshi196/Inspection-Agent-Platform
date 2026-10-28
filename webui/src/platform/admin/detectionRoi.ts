export type RoiPoint = { x: number; y: number };

export type DetectionShape = {
  id: string;
  type: "rect" | "polygon" | "line";
  points: RoiPoint[];
};

export type DetectionRoiBundle = {
  detection: DetectionShape[];
  inverse: DetectionShape[];
};

export type DrawTool = "rect" | "polygon" | "line" | "inverse-polygon" | null;

const ROI_KEYS = {
  detection: "detection_roi",
  inverse: "inverse_detection_roi",
  defence: "defence",
} as const;

export type VaioDefencePoint = { x: number; y: number };

export type VaioDefenceZone = {
  areaattr: 0 | 8 | 9;
  points: VaioDefencePoint[];
};

const DEFAULT_FULLSCREEN_DEFENCE: VaioDefenceZone[] = [
  {
    areaattr: 0,
    points: [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ],
  },
];

function toIntPercent(value: number) {
  return Math.round(clampPercent(value));
}

function shapeToPolygonPoints(shape: DetectionShape): RoiPoint[] {
  if (shape.type === "rect" && shape.points.length >= 2) {
    const rect = rectFromPoints(shape.points);
    return [
      { x: rect.x, y: rect.y },
      { x: rect.x + rect.width, y: rect.y },
      { x: rect.x + rect.width, y: rect.y + rect.height },
      { x: rect.x, y: rect.y + rect.height },
    ];
  }
  return shape.points;
}

/** 将画布 ROI 转为 vaio C++ 所需的 config.defence（坐标 0–100 整数百分比）。 */
export function detectionRoiToVaioDefence(bundle: DetectionRoiBundle): VaioDefenceZone[] {
  const out: VaioDefenceZone[] = [];

  for (const shape of bundle.detection) {
    if (shape.type === "line") {
      const points = shape.points.slice(0, 2);
      if (points.length < 2) continue;
      out.push({
        areaattr: 8,
        points: points.map((p) => ({ x: toIntPercent(p.x), y: toIntPercent(p.y) })),
      });
      continue;
    }

    const points = shapeToPolygonPoints(shape);
    if (points.length < 3) continue;
    out.push({
      areaattr: 0,
      points: points.map((p) => ({ x: toIntPercent(p.x), y: toIntPercent(p.y) })),
    });
  }

  for (const shape of bundle.inverse) {
    const points = shapeToPolygonPoints(shape);
    if (points.length < 3) continue;
    out.push({
      areaattr: 9,
      points: points.map((p) => ({ x: toIntPercent(p.x), y: toIntPercent(p.y) })),
    });
  }

  return out.length > 0 ? out : DEFAULT_FULLSCREEN_DEFENCE;
}

export function newShapeId() {
  return `roi-${Math.random().toString(36).slice(2, 9)}`;
}

export function defaultDetectionRoi(algorithmId: string): DetectionRoiBundle {
  if (algorithmId === "algo-2") {
    return {
      detection: [
        {
          id: "roi-smoke",
          type: "rect",
          points: [
            { x: 52, y: 38 },
            { x: 86, y: 74 },
          ],
        },
      ],
      inverse: [
        {
          id: "roi-inverse",
          type: "polygon",
          points: [
            { x: 8, y: 12 },
            { x: 28, y: 10 },
            { x: 32, y: 28 },
            { x: 10, y: 30 },
          ],
        },
      ],
    };
  }

  if (algorithmId === "algo-3") {
    return {
      detection: [
        {
          id: "roi-line",
          type: "line",
          points: [
            { x: 18, y: 62 },
            { x: 82, y: 58 },
          ],
        },
        {
          id: "roi-zone",
          type: "polygon",
          points: [
            { x: 20, y: 40 },
            { x: 78, y: 36 },
            { x: 80, y: 78 },
            { x: 22, y: 82 },
          ],
        },
      ],
      inverse: [],
    };
  }

  return {
    detection: [
      {
        id: "roi-default",
        type: "rect",
        points: [
          { x: 24, y: 28 },
          { x: 76, y: 72 },
        ],
      },
    ],
    inverse: [],
  };
}

function parseShapeList(raw: unknown): DetectionShape[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is DetectionShape => {
      if (!item || typeof item !== "object") return false;
      const shape = item as DetectionShape;
      return (
        typeof shape.id === "string" &&
        (shape.type === "rect" || shape.type === "polygon" || shape.type === "line") &&
        Array.isArray(shape.points)
      );
    })
    .map((shape) => ({
      id: shape.id,
      type: shape.type,
      points: shape.points.map((p) => ({
        x: clampPercent(p.x),
        y: clampPercent(p.y),
      })),
    }));
}

export function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

export function parseDetectionRoi(
  detectionRaw: unknown,
  inverseRaw: unknown,
  algorithmId: string,
): DetectionRoiBundle {
  const fallback = defaultDetectionRoi(algorithmId);
  const detectionProvided = detectionRaw !== undefined && detectionRaw !== "";
  const inverseProvided = inverseRaw !== undefined && inverseRaw !== "";

  const detection = parseShapeList(
    typeof detectionRaw === "string" ? safeJsonParse(detectionRaw) : detectionRaw,
  );
  const inverse = parseShapeList(
    typeof inverseRaw === "string" ? safeJsonParse(inverseRaw) : inverseRaw,
  );

  return {
    detection: detectionProvided ? detection : fallback.detection,
    inverse: inverseProvided ? inverse : fallback.inverse,
  };
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function serializeDetectionRoi(bundle: DetectionRoiBundle) {
  const defence = detectionRoiToVaioDefence(bundle);
  return {
    [ROI_KEYS.detection]: JSON.stringify(bundle.detection),
    [ROI_KEYS.inverse]: JSON.stringify(bundle.inverse),
    [ROI_KEYS.defence]: JSON.stringify(defence),
  };
}

export function readDetectionRoiFromParams(
  params: Record<string, string | number | boolean>,
  algorithmId: string,
): DetectionRoiBundle {
  return parseDetectionRoi(params[ROI_KEYS.detection], params[ROI_KEYS.inverse], algorithmId);
}

export function rectFromPoints(points: RoiPoint[]) {
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const x1 = Math.min(...xs);
  const x2 = Math.max(...xs);
  const y1 = Math.min(...ys);
  const y2 = Math.max(...ys);
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

export function normalizeRectShape(shape: DetectionShape): DetectionShape {
  if (shape.type !== "rect" || shape.points.length < 2) return shape;
  const rect = rectFromPoints(shape.points);
  return {
    ...shape,
    points: [
      { x: rect.x, y: rect.y },
      { x: rect.x + rect.width, y: rect.y + rect.height },
    ],
  };
}
