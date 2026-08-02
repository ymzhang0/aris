import type { ReactNode } from "react";
import { ListFilter, PanelBottom, PanelLeft, PanelRight } from "lucide-react";

import { cn } from "@/lib/utils";

type AppShellProps = {
  leftSidebar: ReactNode;
  mainContent: ReactNode;
  rightSidebar: ReactNode;
  bottomPanel: ReactNode;
  bottomStatusBar: ReactNode;
  leftExpanded: boolean;
  rightExpanded: boolean;
  bottomExpanded: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
  onToggleBottom: () => void;
  pinnedSummaryExpanded: boolean;
  showPinnedSummaryToggle: boolean;
  onTogglePinnedSummary: () => void;
};

const toolbarButton =
  "app-no-drag grid h-9 w-9 place-items-center rounded-xl text-zinc-500 transition-colors hover:bg-zinc-200/70 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100";

export function AppShell(props: AppShellProps) {
  return (
    <div
      className={cn(
        "grid h-[100dvh] w-full overflow-hidden bg-white text-zinc-950 dark:bg-zinc-950 dark:text-zinc-100",
        props.bottomExpanded
          ? "grid-rows-[auto_minmax(0,1fr)_minmax(160px,28vh)_28px]"
          : "grid-rows-[auto_minmax(0,1fr)_0_28px]",
      )}
      style={{
        gridTemplateColumns: `${props.leftExpanded ? "260px" : "48px"} minmax(0,1fr) ${props.rightExpanded ? "360px" : "0px"}`,
      }}
    >
      <div className="window-toolbar-row app-no-drag relative col-span-3 border-b border-zinc-200/70 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <div className="window-drag-surface absolute inset-x-0 bottom-0" aria-hidden="true" />
        <div className="window-left-controls absolute flex items-center">
          <button className={toolbarButton} onClick={props.onToggleLeft} title={props.leftExpanded ? "Collapse sidebar" : "Expand sidebar"} aria-label={props.leftExpanded ? "Collapse sidebar" : "Expand sidebar"}>
            <PanelLeft className="h-[18px] w-[18px]" />
          </button>
        </div>
        <div className="window-right-controls absolute flex items-center justify-end gap-1">
          {props.showPinnedSummaryToggle ? (
            <button
              className={cn(toolbarButton, props.pinnedSummaryExpanded && "bg-zinc-100 text-zinc-950 dark:bg-zinc-900 dark:text-white")}
              onClick={props.onTogglePinnedSummary}
              title="Toggle pinned summary"
              aria-label="Toggle pinned summary"
              aria-pressed={props.pinnedSummaryExpanded}
            >
              <ListFilter className="h-[18px] w-[18px]" />
            </button>
          ) : null}
          <button className={cn(toolbarButton, props.bottomExpanded && "bg-zinc-100 dark:bg-zinc-900")} onClick={props.onToggleBottom} title="Toggle bottom panel" aria-label="Toggle bottom panel">
            <PanelBottom className="h-[18px] w-[18px]" />
          </button>
          <button className={cn(toolbarButton, props.rightExpanded && "bg-zinc-100 dark:bg-zinc-900")} onClick={props.onToggleRight} title={props.rightExpanded ? "Collapse tools" : "Expand tools"} aria-label={props.rightExpanded ? "Collapse tools" : "Expand tools"}>
            <PanelRight className="h-[18px] w-[18px]" />
          </button>
        </div>
      </div>

      <div className="min-h-0 overflow-hidden">{props.leftSidebar}</div>
      <div className="min-h-0 min-w-0 overflow-hidden">{props.mainContent}</div>
      <div className="min-h-0 overflow-hidden">{props.rightSidebar}</div>
      <div className="col-start-2 col-span-2 min-h-0 overflow-hidden border-t border-zinc-800 bg-zinc-950">
        {props.bottomExpanded ? props.bottomPanel : null}
      </div>
      <div className="col-span-3 min-w-0">{props.bottomStatusBar}</div>
    </div>
  );
}
