import { useMemo, useState } from "react";
import { Badge } from "../components/Badge";
import { Modal } from "../components/Modal";
import { postInspectionWorkGenerate, readApiError } from "../../api";
import type { RegionRow } from "../regionApi";
import { apiRowToInspectionWork } from "../inspectionWorkApi";
import { parseAiGenerationTrace, AiGenerationTracePanel } from "./AiGenerationTracePanel";
import type { AlgorithmItem, CameraDevice, KnowledgeRule, InspectionScheduleMode, InspectionWorkEntity, SensorDevice } from "../types";
import {
  CONTINUOUS_ANALYSIS_WINDOW_SEC,
  CONTINUOUS_CHECK_INTERVAL_LABEL,
  PERIODIC_INTERVAL_OPTIONS,
  SCHEDULE_MODE_OPTIONS,
  scheduleModeLabel,
} from "../inspectionWorkUtils";

const INSPECTION_PURPOSE_EXAMPLES = [
  {
    id: "daily",
    title: "全园区日常巡检",
    text: "对写字楼公区、商业裙楼、地库及外围已接入摄像头与传感器开展日常物业服务巡检，覆盖制服工牌、消防通道与设备在线情况。",
  },
  {
    id: "badge",
    title: "门岗形象合规专项",
    text: "聚焦东门岗与大堂入口，检查制服工牌佩戴情况，匹配视频分析算法与门岗摄像头。",
  },
  {
    id: "sensor",
    title: "环境与设备监测",
    text: "结合大堂温湿度、地库 CO、外围噪声等传感数据，按物业规范监测是否超限并生成告警巡检业务。",
  },
  {
    id: "parking",
    title: "地库秩序管理",
    text: "针对地下停车场消防通道与车行通道，强化违停识别、通道占用检测，保障疏散畅通。",
  },
  {
    id: "mep",
    title: "设备机房专项",
    text: "覆盖配电间、水泵房等限制区域，关注烟雾、入侵与设备温升异常。",
  },
];

type Props = {
  open: boolean;
  onClose: () => void;
  onImport: (works: InspectionWorkEntity[]) => void;
  regions: RegionRow[];
  rules: KnowledgeRule[];
  algorithms: AlgorithmItem[];
  cameras: CameraDevice[];
  sensors: SensorDevice[];
};

function mapGeneratedWork(
  row: Record<string, unknown>,
  index: number,
  regionNames: Record<string, string>,
  fallbackTrace?: ReturnType<typeof parseAiGenerationTrace>,
): InspectionWorkEntity {
  const mapped = apiRowToInspectionWork(row);
  const trace =
    parseAiGenerationTrace(row.ai_generation_trace) ??
    fallbackTrace ??
    undefined;
  const regionIds =
    mapped.region_ids.length > 0
      ? mapped.region_ids
      : mapped.region_id
        ? [mapped.region_id]
        : [];
  const region_name =
    regionIds.map((id) => regionNames[id] || id).join("、") ||
    mapped.region_name ||
    mapped.region_id;
  return {
    ...mapped,
    work_id: mapped.work_id || `iw-ai-${Date.now()}-${index}`,
    region_name,
    source: "ai",
    ai_generation_trace: trace,
    schedule_mode: "manual",
    schedule_interval: undefined,
    schedule_times: undefined,
    updated_at: new Date().toISOString().slice(0, 16).replace("T", " "),
  };
}

function patchGeneratedWork(
  list: InspectionWorkEntity[],
  workId: string,
  patch: Partial<Pick<InspectionWorkEntity, "schedule_mode" | "schedule_interval" | "schedule_times">>,
): InspectionWorkEntity[] {
  return list.map((w) => (w.work_id === workId ? { ...w, ...patch } : w));
}

export function AiWorkComposerModal({
  open,
  onClose,
  onImport,
  regions,
  rules,
  algorithms,
  cameras,
  sensors,
}: Props) {
  const regionNames = useMemo(
    () => Object.fromEntries(regions.map((r) => [r.id, r.name])),
    [regions],
  );
  const [prompt, setPrompt] = useState(INSPECTION_PURPOSE_EXAMPLES[0].text);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [generated, setGenerated] = useState<InspectionWorkEntity[]>([]);
  const [phase, setPhase] = useState<"compose" | "preview">("compose");

  const effectivePrompt = prompt.trim();

  const publishedRules = useMemo(() => rules.filter((r) => r.status === "published"), [rules]);

  const reset = () => {
    setError("");
    setGenerated([]);
    setPhase("compose");
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const runGenerate = async () => {
    if (!effectivePrompt) {
      setError("请描述巡检目的、关注规范或设备范围");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await postInspectionWorkGenerate({
        topic: effectivePrompt,
        persist: false,
        algorithm_limit: 40,
      });
      if (!res.ok) {
        setError(await readApiError(res));
        return;
      }
      const out = (await res.json()) as {
        works?: Record<string, unknown>[];
        retrieval_trace?: unknown;
      };
      const trace = parseAiGenerationTrace(out.retrieval_trace);
      const list = (out.works ?? []).map((row, i) => mapGeneratedWork(row, i, regionNames, trace));
      if (list.length === 0) {
        setError("未生成有效巡检业务，请确认知识库已有已发布规范且算法/设备已入库");
        return;
      }
      setGenerated(list);
      setPhase("preview");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleImport = () => {
    if (generated.length === 0) return;
    onImport(generated);
    handleClose();
  };

  const updateScheduleMode = (workId: string, mode: InspectionScheduleMode) => {
    setGenerated((list) =>
      patchGeneratedWork(list, workId, {
        schedule_mode: mode,
        schedule_interval:
          mode === "periodic"
            ? list.find((w) => w.work_id === workId)?.schedule_interval ?? "每日"
            : mode === "continuous"
              ? CONTINUOUS_CHECK_INTERVAL_LABEL
              : undefined,
        schedule_times: mode === "scheduled" ? list.find((w) => w.work_id === workId)?.schedule_times ?? "08:00" : undefined,
      }),
    );
  };

  return (
    <Modal
      open={open}
      title="AI 巡检业务生成"
      onClose={handleClose}
      closeOnBackdrop={false}
      modalClassName="pf-modal-ai-composer"
      footer={
        phase === "compose" ? (
          <>
            <button type="button" className="pf-btn pf-btn-sm" onClick={handleClose}>
              取消
            </button>
            <button
              type="button"
              className={`pf-btn pf-btn-sm pf-btn-primary pf-studio-ai-btn${loading ? " is-loading" : ""}`}
              disabled={loading || !effectivePrompt}
              onClick={() => void runGenerate()}
            >
              {loading ? "AI 生成中…" : "开始生成"}
            </button>
          </>
        ) : (
          <>
            <button type="button" className="pf-btn pf-btn-sm" onClick={() => setPhase("compose")}>
              返回编辑
            </button>
            <button type="button" className="pf-btn pf-btn-sm pf-btn-primary" onClick={handleImport}>
              导入巡检业务
            </button>
          </>
        )
      }
    >
      <div className="pf-ai-compose">
        <div className="pf-ai-compose-hero">
          <div className="pf-ai-compose-hero-main">
            <span className="pf-ai-compose-spark" aria-hidden>✦</span>
            <div>
              <strong>智能生成</strong>
              <p>描述巡检诉求，系统将检索知识库规范并匹配算法与设备，生成可执行巡检业务。</p>
            </div>
          </div>
          <div className="pf-ai-compose-stats">
            <span className="pf-ai-compose-stat"><strong>{publishedRules.length}</strong> 规范</span>
            <span className="pf-ai-compose-stat"><strong>{algorithms.length}</strong> 算法</span>
            <span className="pf-ai-compose-stat"><strong>{cameras.length + sensors.length}</strong> 设备</span>
          </div>
        </div>

        {phase === "compose" ? (
          <div className="pf-ai-compose-body">
            <section className="pf-ai-compose-input-panel">
              <div className="pf-ai-compose-panel-head">
                <h3>用户输入</h3>
              </div>
              <textarea
                className="pf-cell-textarea pf-studio-ai-textarea pf-ai-compose-textarea"
                rows={5}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="描述巡检目的、关注规范或设备范围…"
              />
              {error ? <p className="pf-studio-ai-error">{error}</p> : null}
            </section>

            <section className="pf-ai-compose-examples-panel">
              <div className="pf-ai-compose-panel-head">
                <h3>参考示例</h3>
                <span className="pf-ai-compose-panel-hint">点击填入左侧</span>
              </div>
              <ul className="pf-ai-compose-example-grid">
                {INSPECTION_PURPOSE_EXAMPLES.map((ex) => (
                  <li key={ex.id}>
                    <button
                      type="button"
                      className={`pf-ai-compose-example${prompt === ex.text ? " is-active" : ""}`}
                      onClick={() => setPrompt(ex.text)}
                    >
                      <strong>{ex.title}</strong>
                      <span>{ex.text}</span>
                    </button>
                  </li>
                ))}
              </ul>

              <div className="pf-ai-compose-hints">
                <div className="pf-ai-compose-hint-card">
                  <h4>生成策略</h4>
                  <ul>
                    <li>读取区域下全部规范规则</li>
                    <li>结合巡检诉求匹配算法目录</li>
                    <li>自动编组 rule / algorithm / equipment</li>
                    <li>导入后需逐条保存</li>
                  </ul>
                </div>
                <div className="pf-ai-compose-hint-card">
                  <h4>前置条件</h4>
                  <ul>
                    <li>区域已有规范规则（规范流程或知识库）</li>
                    <li>算法目录已导入</li>
                    <li>生成可能较慢，请耐心等待</li>
                  </ul>
                </div>
              </div>
            </section>
          </div>
        ) : (
          <div className="pf-ai-compose-preview">
            <div className="pf-ai-compose-preview-head">
              <strong>已生成 1 条巡检业务</strong>
              <span>确认运行方式后导入到巡检业务列表并保存</span>
            </div>
            <ul className="pf-ai-compose-preview-list">
              {generated.map((w) => (
                <li key={w.work_id} className="pf-ai-compose-preview-item">
                  <div className="pf-ai-compose-preview-top">
                    <strong>{w.name}</strong>
                    <Badge tone="info">{scheduleModeLabel(w.schedule_mode)}</Badge>
                  </div>
                  <p>{w.desc}</p>
                  {w.ai_generation_trace ? (
                    <AiGenerationTracePanel trace={w.ai_generation_trace} />
                  ) : null}
                  <div className="pf-ai-compose-preview-meta">
                    <span>{w.region_name || "未绑定区域"}</span>
                    <span>{w.rule_set.length} 规范</span>
                    <span>{w.algorithm_set.length} 算法</span>
                    <span>{w.equipment_set.length} 设备</span>
                  </div>
                  <div className="pf-ai-compose-preview-schedule">
                    <div className="pf-studio-schedule-chips" role="radiogroup" aria-label="运行方式">
                      {SCHEDULE_MODE_OPTIONS.map((o) => (
                        <button
                          key={o.id}
                          type="button"
                          role="radio"
                          aria-checked={w.schedule_mode === o.id}
                          className={`pf-studio-filter-chip${w.schedule_mode === o.id ? " is-active" : ""}`}
                          onClick={() => updateScheduleMode(w.work_id, o.id)}
                        >
                          {o.label}
                        </button>
                      ))}
                    </div>
                    {w.schedule_mode === "periodic" ? (
                      <select
                        className="pf-select"
                        value={w.schedule_interval ?? "每日"}
                        onChange={(e) =>
                          setGenerated((list) =>
                            patchGeneratedWork(list, w.work_id, { schedule_interval: e.target.value }),
                          )
                        }
                      >
                        {PERIODIC_INTERVAL_OPTIONS.map((x) => (
                          <option key={x} value={x}>{x}</option>
                        ))}
                      </select>
                    ) : null}
                    {w.schedule_mode === "scheduled" ? (
                      <input
                        className="pf-cell-input"
                        value={w.schedule_times ?? ""}
                        placeholder="如 08:00, 14:00"
                        onChange={(e) =>
                          setGenerated((list) =>
                            patchGeneratedWork(list, w.work_id, { schedule_times: e.target.value }),
                          )
                        }
                      />
                    ) : null}
                    {w.schedule_mode === "continuous" ? (
                      <span className="pf-studio-schedule-detail-note">
                        {CONTINUOUS_CHECK_INTERVAL_LABEL} · 分析前 {CONTINUOUS_ANALYSIS_WINDOW_SEC} 秒
                      </span>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  );
}
