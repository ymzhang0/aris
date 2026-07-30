import { type ReactNode, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

const RIG_STATE_STORAGE_KEY = "aris.shell.rig_expanded";

type AppShellProps = {
  leftSidebar: ReactNode;
  mainContent: ReactNode;
  rightSidebar?: ReactNode;
};

export function AppShell({
  leftSidebar,
  mainContent,
  rightSidebar,
}: AppShellProps) {
  const [rigExpanded, setRigExpanded] = useState<boolean>(() => {
    const saved = window.localStorage.getItem(RIG_STATE_STORAGE_KEY);
    return saved !== "false";
  });

  useEffect(() => {
    window.localStorage.setItem(RIG_STATE_STORAGE_KEY, String(rigExpanded));
  }, [rigExpanded]);

  return (
    <div className="grid h-screen w-full grid-cols-[auto_1fr_auto] overflow-hidden bg-white dark:bg-zinc-950">
      <aside className="relative flex h-full w-[360px] flex-shrink-0 flex-col overflow-hidden border-r border-zinc-200/80 dark:border-zinc-800">
        {leftSidebar}
      </aside>

      <main className="relative flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        {mainContent}
      </main>

      {rightSidebar && (
        <aside
          className={cn(
            "relative flex h-full flex-shrink-0 flex-col overflow-hidden border-l border-zinc-200/80 transition-all duration-300 ease-in-out dark:border-zinc-800",
            rigExpanded ? "w-[400px]" : "w-12",
          )}
        >
          <div className="flex h-12 w-full items-center justify-start border-b border-zinc-200/80 px-2 dark:border-zinc-800">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              onClick={() => setRigExpanded(!rigExpanded)}
              aria-label={rigExpanded ? "Collapse Rig" : "Expand Rig"}
            >
              {rigExpanded ? (
                <PanelRightClose className="h-4 w-4" />
              ) : (
                <PanelRightOpen className="h-4 w-4" />
              )}
            </Button>
            {rigExpanded && (
              <span className="ml-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Rig
              </span>
            )}
          </div>
          <div
            className={cn(
              "flex flex-1 flex-col overflow-hidden",
              !rigExpanded && "hidden",
            )}
          >
            {rightSidebar}
          </div>
        </aside>
      )}
    </div>
  );
}
