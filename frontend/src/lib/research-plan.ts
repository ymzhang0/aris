import type { SubmissionDraftPayload } from "@/components/dashboard/submission-modal";

export type ResearchPlanStageStatus = "planned" | "ready" | "running" | "completed" | "blocked";

export type ResearchPlan = {
  title: string;
  objective: string;
  stages: Array<{ id: string; label: string; status: ResearchPlanStageStatus }>;
  assumptions: Array<{ label: string; value: string; source: "user" | "project" | "ai" | "derived" }>;
  outputs: string[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function compactValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.slice(0, 5).map(compactValue).filter(Boolean).join(", ");
  const record = asRecord(value);
  if (!record) return "";
  if ("value" in record) return compactValue(record.value);
  return Object.entries(record).slice(0, 3).map(([key, item]) => `${key}: ${compactValue(item)}`).join(" · ");
}

export function normalizeResearchPlan(value: unknown): ResearchPlan | null {
  const record = asRecord(value);
  if (!record) return null;
  const title = cleanText(record.title);
  const objective = cleanText(record.objective);
  if (!title || !objective) return null;
  const stages = Array.isArray(record.stages) ? record.stages.flatMap((item, index) => {
    const stage = asRecord(item);
    const label = cleanText(stage?.label);
    if (!stage || !label) return [];
    const rawStatus = cleanText(stage.status).toLowerCase();
    const status: ResearchPlanStageStatus = ["planned", "ready", "running", "completed", "blocked"].includes(rawStatus)
      ? rawStatus as ResearchPlanStageStatus
      : "planned";
    return [{ id: cleanText(stage.id) || `stage-${index + 1}`, label, status }];
  }) : [];
  const assumptions = Array.isArray(record.assumptions) ? record.assumptions.flatMap((item) => {
    const assumption = asRecord(item);
    const label = cleanText(assumption?.label);
    const assumptionValue = compactValue(assumption?.value);
    if (!assumption || !label || !assumptionValue) return [];
    const rawSource = cleanText(assumption.source).toLowerCase();
    const source = ["user", "project", "ai", "derived"].includes(rawSource)
      ? rawSource as ResearchPlan["assumptions"][number]["source"]
      : "ai";
    return [{ label, value: assumptionValue, source }];
  }) : [];
  const outputs = Array.isArray(record.outputs) ? record.outputs.map(cleanText).filter(Boolean).slice(0, 6) : [];
  return { title, objective, stages: stages.slice(0, 8), assumptions: assumptions.slice(0, 8), outputs };
}

export function extractResearchPlan(payload: unknown): ResearchPlan | null {
  const root = asRecord(payload);
  if (!root) return null;
  return normalizeResearchPlan(root.research_plan)
    ?? normalizeResearchPlan(asRecord(root.data_payload)?.research_plan)
    ?? normalizeResearchPlan(asRecord(root.payload)?.research_plan);
}

export function deriveResearchPlanFromDraft(draft: SubmissionDraftPayload): ResearchPlan {
  const primary = asRecord(draft.primary_inputs) ?? {};
  const recommended = asRecord(draft.recommended_inputs) ?? {};
  const assumptions = [...Object.entries(primary), ...Object.entries(recommended)]
    .map(([label, value]) => ({ label: label.replace(/_/g, " "), value: compactValue(value), source: "derived" as const }))
    .filter((item) => item.value)
    .slice(0, 5);
  const jobCount = Number(draft.meta.job_count || (Array.isArray(draft.meta.draft) ? draft.meta.draft.length : 1));
  return {
    title: draft.process_label || "AiiDA research run",
    objective: `Prepare a validated ${jobCount > 1 ? `${jobCount}-task study` : "calculation"} and preserve its AiiDA provenance.`,
    stages: [
      { id: "prepare", label: "Prepare scientific inputs", status: "completed" },
      { id: "review", label: `Review ${jobCount > 1 ? `${jobCount} linked runs` : "the run"}`, status: "ready" },
      { id: "execute", label: "Execute with AiiDA", status: "planned" },
      { id: "analyse", label: "Inspect and compare results", status: "planned" },
    ],
    assumptions,
    outputs: ["AiiDA process provenance", "Validated calculation outputs"],
  };
}
