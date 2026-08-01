import { AlertTriangle, Check, ChevronRight, CircleStop, Clock3, Cpu, Database, Layers3, Loader2, Play, Server } from "lucide-react";

import type { SubmissionDraftPayload, SubmissionModalState } from "./submission-modal";

type RunReviewProps = {
  draft: SubmissionDraftPayload;
  state: SubmissionModalState;
  disabled: boolean;
  onReview: () => void;
  onRun: () => void;
  onCancel: () => void;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  const record = asRecord(value);
  if (record && "value" in record) return valueText(record.value);
  if (Array.isArray(value)) return value.slice(0, 4).map(valueText).filter(Boolean).join(", ");
  return record ? Object.values(record).slice(0, 3).map(valueText).filter(Boolean).join(" · ") : "";
}

export function RunReview({ draft, state, disabled, onReview, onRun, onCancel }: RunReviewProps) {
  const rawSubmit = draft.meta.draft;
  const jobCount = Number(draft.meta.job_count || (Array.isArray(rawSubmit) ? rawSubmit.length : 1));
  const batch = jobCount > 1 || draft.meta.preview_mode === "batch";
  const validation = draft.meta.validation_summary;
  const errorCount = validation?.errors?.length ?? 0;
  const warningCount = validation?.warnings?.length ?? 0;
  const parameters = Object.entries(asRecord(draft.primary_inputs) ?? {})
    .map(([label, value]) => ({ label: label.replace(/_/g, " "), value: valueText(value) }))
    .filter((item) => item.value)
    .slice(0, 4);
  const actionable = state.status === "idle";

  return (
    <section className="mt-3 overflow-hidden rounded-2xl border border-zinc-200/90 bg-zinc-50/80 dark:border-zinc-800 dark:bg-zinc-900/55">
      <div className="flex items-start gap-3 px-4 py-3.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-300">{batch ? <Layers3 className="h-[18px] w-[18px]" /> : <Cpu className="h-[18px] w-[18px]" />}</span>
        <div className="min-w-0 flex-1"><p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-zinc-500">Ready to run</p><h3 className="mt-0.5 truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{draft.process_label}</h3><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500"><span className="inline-flex items-center gap-1"><Database className="h-3 w-3" />{jobCount} {jobCount === 1 ? "task" : "tasks"}</span>{draft.meta.target_computer && <span className="inline-flex items-center gap-1"><Server className="h-3 w-3" />{draft.meta.target_computer}</span>}<span className="inline-flex items-center gap-1"><Clock3 className="h-3 w-3" />{valueText(draft.meta.estimated_runtime) || "Estimate unavailable"}</span></div></div>
        <RunState status={state.status} />
      </div>

      {parameters.length > 0 && <div className="grid grid-cols-2 gap-px border-y border-zinc-200/70 bg-zinc-200/70 dark:border-zinc-800 dark:bg-zinc-800 lg:grid-cols-4">{parameters.map((item) => <div key={item.label} className="min-w-0 bg-white px-3 py-2.5 dark:bg-zinc-950"><p className="truncate text-[10px] capitalize text-zinc-400">{item.label}</p><p className="mt-0.5 truncate text-xs font-medium" title={item.value}>{item.value}</p></div>)}</div>}

      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        {errorCount > 0 ? <span className="inline-flex items-center gap-1 text-xs text-rose-600 dark:text-rose-300"><AlertTriangle className="h-3.5 w-3.5" />{errorCount} blocking issues</span> : <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-300"><Check className="h-3.5 w-3.5" />Builder validated</span>}
        {warningCount > 0 && <span className="text-xs text-amber-600 dark:text-amber-300">{warningCount} warnings</span>}
        <div className="ml-auto flex items-center gap-2">
          {actionable && <button className="rounded-lg px-3 py-1.5 text-xs text-zinc-500 hover:bg-zinc-200/70 dark:hover:bg-zinc-800" onClick={onCancel}><CircleStop className="mr-1 inline h-3.5 w-3.5" />Cancel</button>}
          <button className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-950 dark:hover:bg-zinc-800" onClick={onReview}>Review details <ChevronRight className="ml-1 inline h-3.5 w-3.5" /></button>
          {actionable && <button className="rounded-lg bg-zinc-900 px-3.5 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-40 dark:bg-white dark:text-zinc-900" disabled={disabled || errorCount > 0} onClick={onRun}><Play className="mr-1 inline h-3.5 w-3.5" />{batch ? `Run ${jobCount} tasks` : "Run task"}</button>}
        </div>
      </div>
    </section>
  );
}

function RunState({ status }: { status: SubmissionModalState["status"] }) {
  if (status === "submitting") return <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-[10px] text-blue-600 dark:bg-blue-950/50 dark:text-blue-300"><Loader2 className="h-3 w-3 animate-spin" />Submitting</span>;
  if (status === "submitted") return <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-300">Submitted</span>;
  if (status === "cancelled") return <span className="rounded-full bg-zinc-200 px-2 py-1 text-[10px] text-zinc-500 dark:bg-zinc-800">Cancelled</span>;
  if (status === "error") return <span className="rounded-full bg-rose-50 px-2 py-1 text-[10px] text-rose-600 dark:bg-rose-950/50 dark:text-rose-300">Failed</span>;
  return null;
}
