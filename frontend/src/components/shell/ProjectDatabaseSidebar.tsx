import { AlertCircle, Boxes, Database, FlaskConical, Plus } from "lucide-react";
import type { ReactNode } from "react";

import type { ChatProject, ProcessItem } from "@/types/aiida";
import { cn } from "@/lib/utils";

type ProjectDatabaseSidebarProps = {
  project: ChatProject | null;
  processes: ProcessItem[];
  loading?: boolean;
  onOpenProcess: (process: ProcessItem) => void;
  onAddContext: (process: ProcessItem) => void;
};

export function ProjectDatabaseSidebar(props: ProjectDatabaseSidebarProps) {
  if (!props.project) {
    return <EmptyState icon={<Database />} text="Open a project to browse its AiiDA data." />;
  }
  if (!props.project.group_label) {
    return <EmptyState icon={<AlertCircle />} text="This project is not linked to an AiiDA Group yet." />;
  }

  return (
    <div className="px-3 py-3">
      <div className="flex items-center gap-2 px-2 py-2 text-sm font-medium">
        <Boxes className="h-4 w-4 text-zinc-500" />
        <span className="min-w-0 flex-1 truncate">{props.project.group_label}</span>
        <span className="text-xs font-normal tabular-nums text-zinc-400">{props.processes.length}</span>
      </div>

      <div className="mt-1 space-y-0.5">
        {props.processes.map((process) => {
          const state = process.process_state || process.state || "stored";
          return (
            <div key={process.pk} className="group flex items-center rounded-xl pr-1 hover:bg-zinc-100 dark:hover:bg-zinc-900">
              <button className="flex min-w-0 flex-1 items-center gap-3 px-2 py-2.5 text-left" onClick={() => props.onOpenProcess(process)}>
                <FlaskConical className="h-4 w-4 shrink-0 text-zinc-400" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{process.label || process.process_label || `Node ${process.pk}`}</span>
                  <span className="mt-0.5 block truncate text-[11px] text-zinc-400">#{process.pk} · {state}</span>
                </span>
                <span className={cn("h-2 w-2 shrink-0 rounded-full", state === "finished" ? "bg-emerald-500" : state === "excepted" || state === "killed" ? "bg-rose-500" : "bg-amber-400")} />
              </button>
              <button className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-zinc-400 opacity-0 hover:bg-zinc-200 hover:text-zinc-700 group-hover:opacity-100 dark:hover:bg-zinc-800 dark:hover:text-zinc-200" onClick={() => props.onAddContext(process)} title="Add to chat context" aria-label="Add to chat context">
                <Plus className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>

      {props.loading && <p className="px-2 py-4 text-xs text-zinc-400">Loading project data…</p>}
      {!props.loading && !props.processes.length && <p className="px-2 py-6 text-sm text-zinc-400">No nodes in this project yet.</p>}
    </div>
  );
}

function EmptyState({ icon, text }: { icon: ReactNode; text: string }) {
  return <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center text-sm text-zinc-400 [&_svg]:h-5 [&_svg]:w-5">{icon}<p>{text}</p></div>;
}
