import type { ReactNode } from "react";
import { Database, Files, X } from "lucide-react";

export type RightTool = "files" | "aiida";

type RightToolSidebarProps = {
  expanded: boolean;
  openTools: RightTool[];
  activeTool: RightTool | null;
  filesContent: ReactNode;
  aiidaContent: ReactNode;
  onToolOpen: (tool: RightTool) => void;
  onToolClose: (tool: RightTool) => void;
};

const tools = [
  { id: "files" as const, label: "Files", shortcut: "⌘P", icon: Files },
  { id: "aiida" as const, label: "Database", shortcut: "⌘D", icon: Database },
];

export function RightToolSidebar(props: RightToolSidebarProps) {
  if (!props.expanded) return null;

  const availableTools = tools.filter((tool) => !props.openTools.includes(tool.id));

  return (
    <aside className="flex h-full w-[360px] flex-col border-l border-zinc-200/70 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100">
      {props.openTools.length > 0 ? (
        <div className="flex h-11 shrink-0 items-end gap-1 border-b border-zinc-200/70 bg-zinc-50 px-2 dark:border-zinc-800 dark:bg-zinc-900/60">
          <div className="flex min-w-0 flex-1 items-end gap-1 overflow-x-auto">
            {props.openTools.map((toolId) => {
              const tool = tools.find((item) => item.id === toolId)!;
              const Icon = tool.icon;
              const isActive = props.activeTool === toolId;
              return (
                <div
                  key={tool.id}
                  className={isActive
                    ? "flex h-9 min-w-0 max-w-[150px] items-center rounded-t-lg border border-b-white border-zinc-200 bg-white dark:border-zinc-700 dark:border-b-zinc-950 dark:bg-zinc-950"
                    : "flex h-8 min-w-0 max-w-[150px] items-center rounded-lg text-zinc-500 hover:bg-zinc-200/70 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"}
                >
                  <button
                    className="flex h-full min-w-0 flex-1 items-center gap-2 px-3 text-left text-xs font-medium"
                    onClick={() => props.onToolOpen(tool.id)}
                    title={tool.label}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{tool.label}</span>
                  </button>
                  <button
                    className="mr-1 grid h-6 w-6 shrink-0 place-items-center rounded-md text-zinc-400 hover:bg-zinc-200 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                    onClick={() => props.onToolClose(tool.id)}
                    title={`Close ${tool.label}`}
                    aria-label={`Close ${tool.label}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
          {availableTools.map((tool) => {
            const Icon = tool.icon;
            return (
              <button
                key={tool.id}
                className="mb-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-200 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-white"
                onClick={() => props.onToolOpen(tool.id)}
                title={`Open ${tool.label}`}
                aria-label={`Open ${tool.label}`}
              >
                <Icon className="h-4 w-4" />
              </button>
            );
          })}
        </div>
      ) : null}

      {props.activeTool === null ? (
        <div className="flex min-h-0 flex-1 items-center px-5 pb-[12vh]">
          <nav className="w-full space-y-2" aria-label="Workspace tools">
            {tools.map((tool) => {
              const Icon = tool.icon;
              return (
                <button
                  key={tool.id}
                  className="flex h-14 w-full items-center gap-4 rounded-2xl px-4 text-left text-[17px] text-zinc-700 transition-colors hover:bg-zinc-100 hover:text-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900 dark:hover:text-white"
                  onClick={() => props.onToolOpen(tool.id)}
                >
                  <Icon className="h-5 w-5 shrink-0 text-zinc-500" />
                  <span className="min-w-0 flex-1">{tool.label}</span>
                  <kbd className="rounded-full bg-zinc-100 px-2.5 py-1 font-sans text-xs font-normal text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">{tool.shortcut}</kbd>
                </button>
              );
            })}
          </nav>
        </div>
      ) : (
        <div className="minimal-scrollbar min-h-0 flex-1 overflow-auto">
          {props.activeTool === "files" ? props.filesContent : props.aiidaContent}
        </div>
      )}
    </aside>
  );
}
