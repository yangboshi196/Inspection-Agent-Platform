export type FlowStepId = "time" | "tasks" | "dispatch" | "process" | "progress" | "report";

export type FlowStep = {
  id: FlowStepId;
  title: string;
  desc: string;
};

export type TriggerTaskConfig = {
  propertyId: string;
  workIds: string[];
  regionIds: string[];
  ownerIds: string[];
  scheduleDate: string;
  scheduleStart: string;
  scheduleEnd: string;
  note: string;
};

export type GeneratedFlow = {
  title: string;
  summary: string;
  steps: FlowStep[];
  config: TriggerTaskConfig;
};

export type DispatchRow = {
  id: string;
  workName: string;
  regionName: string;
  ownerName: string;
  status: "pending" | "running" | "done";
  progress: number;
};

export type ProcessRow = {
  id: string;
  title: string;
  ownerName: string;
  status: "queued" | "processing" | "resolved";
  updatedAt: string;
};

export const DEMO_PROPERTIES = [
  { id: "prop-a", name: "星河湾商业综合体" },
  { id: "prop-b", name: "云栖科创园区" },
  { id: "prop-c", name: "滨江国际社区" },
] as const;

export const DEMO_WORKS = [
  { id: "iw-1", name: "A座大堂与公区秩序巡检", regions: ["r1", "r1b"] },
  { id: "iw-2", name: "地下停车场秩序巡检", regions: ["r3"] },
  { id: "iw-3", name: "B座商业运营巡检", regions: ["r2"] },
  { id: "iw-4", name: "设备机房专项巡检", regions: ["r1b"] },
  { id: "iw-5", name: "园区外围安防巡检", regions: ["r4"] },
] as const;

export const DEMO_REGIONS = [
  { id: "r1", name: "A座大堂与公区" },
  { id: "r1b", name: "A座设备夹层" },
  { id: "r2", name: "B座商业裙楼" },
  { id: "r3", name: "地下停车场" },
  { id: "r4", name: "园区外围与卸货区" },
] as const;

export const DEMO_OWNERS = [
  { id: "u-li", name: "李敏", role: "秩序主管" },
  { id: "u-zhang", name: "张工", role: "设备工程师" },
  { id: "u-wang", name: "王审计", role: "HSE 专员" },
  { id: "u-chen", name: "陈主管", role: "物业经理" },
] as const;

export const PROMPT_EXAMPLES = [
  "本周五下午对星河湾 A 座、地库做一次消防与秩序综合巡检，出周报给物业经理。",
  "明天上午园区外围安防 + 设备机房专项，指派秩序与工程各一人，当日汇总报告。",
  "月度合规巡检：商业裙楼与停车场，覆盖视频与传感告警闭环。",
];

/** 描述页快捷填入（短标签 + 完整文案） */
export const PROMPT_CHIPS: { label: string; text: string }[] = [
  { label: "周五消防秩序", text: PROMPT_EXAMPLES[0] },
  { label: "明日外围机房", text: PROMPT_EXAMPLES[1] },
  { label: "月度合规", text: PROMPT_EXAMPLES[2] },
];

const FLOW_TEMPLATE: FlowStep[] = [
  { id: "time", title: "时间", desc: "" },
  { id: "tasks", title: "任务项", desc: "" },
  { id: "dispatch", title: "分发", desc: "" },
  { id: "process", title: "处理", desc: "" },
  { id: "progress", title: "进度", desc: "" },
  { id: "report", title: "报告", desc: "" },
];

function todayIso() {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function pickWorks(text: string): string[] {
  const t = text.toLowerCase();
  if (t.includes("消防") || t.includes("秩序")) return ["iw-1", "iw-2"];
  if (t.includes("外围") || t.includes("安防")) return ["iw-5", "iw-4"];
  if (t.includes("机房") || t.includes("设备")) return ["iw-4", "iw-2"];
  if (t.includes("商业") || t.includes("裙楼")) return ["iw-3", "iw-2"];
  if (t.includes("月度") || t.includes("合规")) return ["iw-1", "iw-3", "iw-5"];
  return ["iw-1", "iw-2", "iw-5"];
}

function pickRegions(workIds: string[]): string[] {
  const set = new Set<string>();
  for (const wid of workIds) {
    const w = DEMO_WORKS.find((x) => x.id === wid);
    w?.regions.forEach((r) => set.add(r));
  }
  return [...set];
}

function pickProperty(text: string): string {
  if (text.includes("星河湾")) return "prop-a";
  if (text.includes("云栖") || text.includes("科创")) return "prop-b";
  if (text.includes("滨江") || text.includes("社区")) return "prop-c";
  return "prop-a";
}

function pickOwners(text: string): string[] {
  if (text.includes("工程") || text.includes("机房")) return ["u-zhang", "u-chen"];
  if (text.includes("hse") || text.includes("合规")) return ["u-wang", "u-chen"];
  return ["u-li", "u-wang"];
}

/** 模拟 Agent 根据自然语言生成流程草案（前端 Demo） */
export function generateFlowFromDescription(description: string): GeneratedFlow {
  const text = description.trim() || PROMPT_EXAMPLES[0];
  const workIds = pickWorks(text);
  const regionIds = pickRegions(workIds);
  const propertyId = pickProperty(text);

  let scheduleDate = todayIso();
  let scheduleStart = "09:00";
  let scheduleEnd = "18:00";
  if (text.includes("下午")) {
    scheduleStart = "14:00";
    scheduleEnd = "18:30";
  }
  if (text.includes("明天")) {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    scheduleDate = d.toISOString().slice(0, 10);
  }
  if (text.includes("周五")) {
    scheduleStart = "13:30";
  }

  const workNames = workIds
    .map((id) => DEMO_WORKS.find((w) => w.id === id)?.name)
    .filter(Boolean)
    .join("、");

  const ownerCount = pickOwners(text).length;

  return {
    title: text.includes("月度") ? "月度巡检" : "综合巡检",
    summary: `${workIds.length} 项 · ${regionIds.length} 区 · ${ownerCount} 人`,
    steps: FLOW_TEMPLATE.map((s) => {
      if (s.id === "tasks" && workNames) return { ...s, desc: workNames };
      if (s.id === "time") return { ...s, desc: `${scheduleDate.slice(5)} ${scheduleStart}–${scheduleEnd}` };
      return s;
    }),
    config: {
      propertyId,
      workIds,
      regionIds,
      ownerIds: pickOwners(text),
      scheduleDate,
      scheduleStart,
      scheduleEnd,
      note: text.slice(0, 200),
    },
  };
}

export function buildDispatchRows(config: TriggerTaskConfig): DispatchRow[] {
  const rows: DispatchRow[] = [];
  let i = 0;
  for (const wid of config.workIds) {
    const work = DEMO_WORKS.find((w) => w.id === wid);
    if (!work) continue;
    for (const rid of work.regions.filter((r) => config.regionIds.includes(r))) {
      const region = DEMO_REGIONS.find((r) => r.id === rid);
      const ownerId = config.ownerIds[i % config.ownerIds.length];
      const ownerName = DEMO_OWNERS.find((o) => o.id === ownerId)?.name ?? "待分配";
      rows.push({
        id: `${wid}-${rid}`,
        workName: work.name,
        regionName: region?.name ?? rid,
        ownerName,
        status: "pending",
        progress: 0,
      });
      i += 1;
    }
  }
  return rows;
}

export function buildProcessRows(config: TriggerTaskConfig): ProcessRow[] {
  return config.workIds.slice(0, 5).map((wid, index) => {
    const work = DEMO_WORKS.find((w) => w.id === wid);
    const owner = DEMO_OWNERS.find((o) => o.id === config.ownerIds[index % config.ownerIds.length]);
    return {
      id: `proc-${wid}`,
      title: work?.name ?? wid,
      ownerName: owner?.name ?? "—",
      status: "queued",
      updatedAt: "—",
    };
  });
}

export function defaultConfig(): TriggerTaskConfig {
  return {
    propertyId: DEMO_PROPERTIES[0].id,
    workIds: ["iw-1", "iw-2"],
    regionIds: ["r1", "r3"],
    ownerIds: ["u-li", "u-wang"],
    scheduleDate: todayIso(),
    scheduleStart: "09:00",
    scheduleEnd: "18:00",
    note: "",
  };
}
