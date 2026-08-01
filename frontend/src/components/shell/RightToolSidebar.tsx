import type { ReactNode } from "react";
import { ArrowLeft, Database, Files } from "lucide-react";

export type RightTool = "files" | "aiida";

type RightToolSidebarProps = {
  expanded: boolean;
  activeTool: RightTool | null;
  filesContent: ReactNode;
  aiidaContent: ReactNode;
  onToolChange: (tool: RightTool | null) => void;
};

const tools = [
  { id: "files" as const, label: "Files", shortcut: "⌘P", icon: Files },
  { id: "aiida" as const, label: "Database", shortcut: "⌘D", icon: Database },
];

export function RightToolSidebar(props: RightToolSidebarProps) {
  if (!props.expanded) return null;

  return (
    <aside className="flex h-full w-[360px] flex-col border-l border-zinc-200/70 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100">
      {props.activeTool === null ? (
        <div className="flex min-h-0 flex-1 items-center px-5 pb-[12vh]">
          <nav className="w-full space-y-2" aria-label="Workspace tools">
            {tools.map((tool) => {
              const Icon = tool.icon;
              return (
                <button
                  key={tool.id}
                  className="flex h-14 w-full items-center gap-4 rounded-2xl px-4 text-left text-[17px] text-zinc-700 transition-colors hover:bg-zinc-100 hover:text-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900 dark:hover:text-white"
                  onClick={() => props.onToolChange(tool.id)}
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
        <>
          <div className="flex h-12 shrink-0 items-center px-3">
            <button className="grid h-9 w-9 place-items-center rounded-xl text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-900 dark:hover:text-white" onClick={() => props.onToolChange(null)} title="Back to tools" aria-label="Back to tools">
              <ArrowLeft className="h-[18px] w-[18px]" />
            </button>
          </div>
          <div className="minimal-scrollbar min-h-0 flex-1 overflow-auto">
            {props.activeTool === "files" ? props.filesContent : props.aiidaContent}
          </div>
        </>
      )}
    </aside>
  );
}
