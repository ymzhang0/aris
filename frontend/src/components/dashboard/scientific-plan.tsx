import { useState } from "react";
import { Check, ChevronDown, Circle, FlaskConical, Loader2, Pin, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ResearchPlan, ResearchPlanStageStatus } from "@/lib/research-plan";

export function ScientificPlan({ plan }: { plan: ResearchPlan }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <section className="mx-5 mt-3 shrink-0 rounded-2xl border border-zinc-200/80 bg-white/95 shadow-sm dark:border-zinc-800 dark:bg-zinc-950/95 md:mx-8">
      <button className="flex w-full items-center gap-3 px-4 py-3 text-left" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
        <span className="grid h-8 w-8 place-items-center rounded-xl bg-violet-50 text-violet-600 dark:bg-violet-950/50 dark:text-violet-300"><FlaskConical className="h-4 w-4" /></span>
        <span className="min-w-0 flex-1"><span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.13em] text-zinc-500"><Pin className="h-3 w-3" />Scientific plan</span><span className="mt-0.5 block truncate text-sm font-semibold">{plan.title}</span></span>
        <span className="hidden max-w-[38%] truncate text-xs text-zinc-500 lg:block">{plan.objective}</span>
        <ChevronDown className={cn("h-4 w-4 text-zinc-400 transition-transform", expanded && "rotate-180")} />
      </button>
      {expanded && <div className="grid gap-5 border-t border-zinc-100 px-4 py-4 dark:border-zinc-800 lg:grid-cols-[1.2fr_1fr]">
        <div><p className="text-sm leading-5 text-zinc-700 dark:text-zinc-200">{plan.objective}</p><ol className="mt-3 space-y-2">{plan.stages.map((stage) => <li key={stage.id} className="flex items-center gap-2 text-xs"><StageIcon status={stage.status} /><span className={cn(stage.status === "completed" && "text-zinc-400 line-through", stage.status === "blocked" && "text-rose-600 dark:text-rose-300")}>{stage.label}</span><span className="ml-auto capitalize text-[10px] text-zinc-400">{stage.status}</span></li>)}</ol></div>
        <div className="space-y-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">Key assumptions</p><div className="mt-2 flex flex-wrap gap-1.5">{plan.assumptions.length ? plan.assumptions.map((item) => <span key={`${item.label}-${item.value}`} className="rounded-full bg-zinc-100 px-2.5 py-1 text-[11px] dark:bg-zinc-900" title={`${item.label} · ${item.source}`}>{item.label}: <strong>{item.value}</strong></span>) : <span className="text-xs text-zinc-400">No explicit assumptions yet</span>}</div></div>{plan.outputs.length > 0 && <div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">Expected outputs</p><p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">{plan.outputs.join(" · ")}</p></div>}</div>
      </div>}
    </section>
  );
}

function StageIcon({ status }: { status: ResearchPlanStageStatus }) {
  if (status === "completed") return <Check className="h-3.5 w-3.5 text-emerald-500" />;
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />;
  if (status === "blocked") return <TriangleAlert className="h-3.5 w-3.5 text-rose-500" />;
  return <Circle className={cn("h-3.5 w-3.5", status === "ready" ? "fill-amber-400 text-amber-400" : "text-zinc-300 dark:text-zinc-700")} />;
}
