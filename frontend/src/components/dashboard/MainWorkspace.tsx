import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { CodeViewer } from "./CodeViewer";
import type { WorkspaceExplorerFileSelection } from "./workspace-explorer-sidebar";

type MainWorkspaceProps = {
  activeView: "CHAT" | "EDITOR";
  viewerFile: WorkspaceExplorerFileSelection | null;
  theme: "light" | "dark";
  onCloseViewer: () => void;
  chatContent: ReactNode;
  terminalContent: ReactNode;
};

export function MainWorkspace({
  activeView,
  viewerFile,
  theme,
  onCloseViewer,
  chatContent,
  terminalContent,
}: MainWorkspaceProps) {
  return (
    <section className="relative flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {chatContent}
      {terminalContent}

      {viewerFile ? (
        <div
          className={cn(
            "absolute inset-0 z-20 transition-all duration-200 ease-out",
            activeView === "EDITOR"
              ? "pointer-events-auto translate-y-0 opacity-100"
              : "pointer-events-none translate-y-2 opacity-0",
          )}
          aria-hidden={activeView !== "EDITOR"}
        >
          <CodeViewer
            key={`${viewerFile.projectId}:${viewerFile.relativePath}`}
            file={viewerFile}
            theme={theme}
            onClose={onCloseViewer}
          />
        </div>
      ) : null}
    </section>
  );
}
