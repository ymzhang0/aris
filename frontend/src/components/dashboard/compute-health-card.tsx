import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, ChevronRight, Clock3, Cpu, Loader2 } from "lucide-react";

import { getComputeHealth } from "@/api";
import { cn } from "@/lib/utils";
import type { ProcessItem } from "@/types/aiida";

type ComputeHealthCardProps = {
  computerLabel: string;
  selectedProcess: ProcessItem | null;
  compact?: boolean;
};

type QueueMetricProps = {
  label: string;
  value: number;
  tone?: "default" | "running" | "warning";
  compact?: boolean;
};

function toText(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const text = value.trim();
  return text || null;
}

function getPreviewComputerLabel(process: ProcessItem | null): string | null {
  const preview = process?.preview_info;
  if (!preview || typeof preview !== "object" || Array.isArray(preview)) {
    return null;
  }
  const record = preview as Record<string, unknown>;
  return (
    toText(record.computer_label) ??
    toText(record.computer_name) ??
    toText(record.machine_label) ??
    (() => {
      const nested = record.computer;
      if (!nested || typeof nested !== "object" || Array.isArray(nested)) {
        return null;
      }
      const nestedRecord = nested as Record<string, unknown>;
      return toText(nestedRecord.label) ?? toText(nestedRecord.name) ?? toText(nestedRecord.computer_label);
    })()
  );
}

function QueueMetric({ label, value, tone = "default", compact = false }: QueueMetricProps) {
  return (
    <div
      className={cn(
        "min-w-0 border-l border-zinc-100 pl-3 first:border-l-0 first:pl-0 dark:border-zinc-800",
        compact ? "px-2.5 py-2" : "px-3 py-2",
        tone === "running" && "text-blue-600 dark:text-blue-300",
        tone === "warning" && "text-amber-600 dark:text-amber-300",
        tone === "default" && "text-zinc-600 dark:text-zinc-300",
      )}
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">{value}</p>
    </div>
  );
}

function buildSummaryText(args: {
  isPending: boolean;
  isError: boolean;
  pending: number;
  queued: number;
  running: number;
  estimateDisplay: string | null | undefined;
  congested: boolean;
}): string {
  if (args.isPending) {
    return "Sampling scheduler state...";
  }
  if (args.isError) {
    return "Temporarily unavailable";
  }
  const parts: string[] = [];
  parts.push(`${args.running} running`);
  parts.push(`${args.pending + args.queued} waiting`);
  if (args.estimateDisplay) {
    parts.push(args.estimateDisplay);
  } else {
    parts.push("No ETA yet");
  }
  if (args.congested) {
    parts.push("Queue congestion");
  }
  return parts.join(" · ");
}

export function ComputeHealthCard({ computerLabel, selectedProcess, compact = false }: ComputeHealthCardProps) {
  const [isExpanded, setIsExpanded] = useState(!compact);
  const selectedProcessComputerLabel = getPreviewComputerLabel(selectedProcess);
  const referenceProcessPk =
    selectedProcess && selectedProcessComputerLabel === computerLabel ? selectedProcess.pk : undefined;

  useEffect(() => {
    setIsExpanded(!compact);
  }, [computerLabel, compact]);

  const healthQuery = useQuery({
    queryKey: ["compute-health", computerLabel, referenceProcessPk ?? "default"],
    queryFn: () =>
      getComputeHealth({
        reference_process_pk: referenceProcessPk,
        computer_label: computerLabel,
      }),
    refetchInterval: 20_000,
    staleTime: 5_000,
    retry: 1,
  });

  const payload = healthQuery.data;
  const queue = payload?.queue;
  const estimate = payload?.estimate;
  const hasWarning = Boolean(payload?.warning_message);
  const summaryText = buildSummaryText({
    isPending: healthQuery.isPending,
    isError: healthQuery.isError,
    pending: queue?.pending ?? 0,
    queued: queue?.queued ?? 0,
    running: queue?.running ?? 0,
    estimateDisplay: estimate?.display,
    congested: Boolean(queue?.congested),
  });

  return (
    <div
      className={cn(
        "min-w-0 overflow-hidden border-t border-zinc-100 pt-3 dark:border-zinc-800",
        compact ? "p-2.5" : "p-4",
      )}
    >
      <button
        type="button"
        onClick={() => setIsExpanded((open) => !open)}
        className="flex w-full min-w-0 items-start justify-between gap-3 text-left transition-colors"
        aria-expanded={isExpanded}
      >
        <div className="min-w-0 flex items-start gap-2">
          <ChevronRight
            className={cn(
              "mt-0.5 h-4 w-4 shrink-0 text-zinc-400 transition-transform dark:text-zinc-500",
              isExpanded && "rotate-90",
            )}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
              <h2 className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">Compute Health</h2>
            </div>
            {!compact ? (
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Queue pressure and runtime estimate for the active HPC target.
              </p>
            ) : null}
            <p className="mt-1 truncate text-xs text-zinc-500 dark:text-zinc-400" title={summaryText}>
              {summaryText}
            </p>
          </div>
        </div>
        {healthQuery.isFetching ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-zinc-400 dark:text-zinc-500" />
        ) : hasWarning ? (
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
        ) : (
          <Cpu className="h-4 w-4 shrink-0 text-zinc-400 dark:text-zinc-500" />
        )}
      </button>

      {!isExpanded ? null : (
        <div className="mt-3 space-y-3">

          {hasWarning ? (
            <div className="border-t border-amber-200 px-0 py-2 text-xs text-amber-800 dark:border-amber-900/70 dark:text-amber-200 break-words">
              {payload?.warning_message}
            </div>
          ) : null}

          {healthQuery.isPending ? (
            <div className="py-3 text-sm text-zinc-500 dark:text-zinc-400">
              Sampling scheduler state...
            </div>
          ) : healthQuery.isError ? (
            <div className="py-3 text-sm text-zinc-500 dark:text-zinc-400">
              Compute health is temporarily unavailable. The panel will retry automatically.
            </div>
          ) : payload ? (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-1.5">
                <QueueMetric label="Running" value={queue?.running ?? 0} tone="running" compact={compact} />
                <QueueMetric label="Pending" value={queue?.pending ?? 0} compact={compact} />
                <QueueMetric
                  label="Queued"
                  value={queue?.queued ?? 0}
                  tone={queue?.congested ? "warning" : "default"}
                  compact={compact}
                />
              </div>

              <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-zinc-500 dark:text-zinc-400">
                {payload.computer_label ? (
                  <span className="max-w-full truncate text-blue-500 dark:text-blue-300">
                    {payload.computer_label}
                  </span>
                ) : null}
                {payload.scheduler_type ? (
                  <span>
                    {payload.scheduler_type}
                  </span>
                ) : null}
                {typeof queue?.total === "number" ? (
                  <span>
                    {queue.total} active jobs
                  </span>
                ) : null}
              </div>

              <div className="min-w-0 border-t border-zinc-100 px-0 py-3 dark:border-zinc-800">
                <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">
                  <Clock3 className="h-3.5 w-3.5" />
                  Estimated Completion
                </div>
                <p className="mt-2 break-words text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {estimate?.available && estimate.display ? estimate.display : "Select a workflow to refine the estimate."}
                </p>
                {estimate?.available ? (
                  <p className="mt-1 break-words text-xs text-zinc-500 dark:text-zinc-400">
                    {estimate.sample_size} historical match{estimate.sample_size === 1 ? "" : "es"}
                    {estimate.basis ? ` · ${estimate.basis}` : ""}
                  </p>
                ) : selectedProcess ? (
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    No comparable completed runs were found for node #{selectedProcess.pk}.
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="py-3 text-sm text-zinc-500 dark:text-zinc-400">
              No compute health data is available yet.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
