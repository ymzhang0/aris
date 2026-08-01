import type { ReactNode } from "react";
import { PanelBottom, PanelLeft, PanelRight } from "lucide-react";

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
      <div className="app-drag-region window-toolbar-row col-span-3 grid border-b border-zinc-200/70 bg-white dark:border-zinc-800 dark:bg-zinc-950" style={{ gridTemplateColumns: "subgrid" }}>
        <div className="window-left-controls flex items-center justify-start px-2">
          <button className={toolbarButton} onClick={props.onToggleLeft} title={props.leftExpanded ? "Collapse sidebar" : "Expand sidebar"} aria-label={props.leftExpanded ? "Collapse sidebar" : "Expand sidebar"}>
            <PanelLeft className="h-[18px] w-[18px]" />
          </button>
        </div>
        <div className="min-w-0" />
        <div className="flex items-center justify-end gap-1 px-2">
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
      <div className="col-start-2 col-span-2 min-h-0 overflow-hidden border-t border-zinc-200 bg-zinc-950 dark:border-zinc-800">
        {props.bottomExpanded ? props.bottomPanel : null}
      </div>
      <div className="col-span-3 min-w-0">{props.bottomStatusBar}</div>
    </div>
  );
}
