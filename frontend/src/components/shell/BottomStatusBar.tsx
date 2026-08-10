import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Activity, Box, Database, Folder, GitBranch, Terminal } from "lucide-react";

import { aiidaClient } from "@/api";
import { useEnvironmentStore } from "@/store/EnvironmentStore";
import type { ChatProject } from "@/types/aiida";
import type { RightTool } from "./RightToolSidebar";

type BottomStatusBarProps = {
  project: ChatProject | null;
  onOpenTool: (tool: RightTool) => void;
  terminalOpen: boolean;
  onToggleTerminal: () => void;
};

function shortPath(path: string | null | undefined) {
  if (!path) return "Auto Python";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.slice(-3).join("/");
}

export function BottomStatusBar({ project, onOpenTool, terminalOpen, onToggleTerminal }: BottomStatusBarProps) {
  const environment = useEnvironmentStore((state) => state);
  const statusQuery = useQuery({
    queryKey: ["aiida-bridge-status"],
    queryFn: () => aiidaClient.getWorkerStatus(),
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    staleTime: 2_000,
  });
  const resourcesQuery = useQuery({
    queryKey: ["aiida-bridge-resources"],
    queryFn: () => aiidaClient.getWorkerResources(),
    enabled: statusQuery.data?.status === "online",
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
  });
  const online = statusQuery.data?.status === "online";
  const profile = environment.inspection?.profile || statusQuery.data?.profile || "No profile";
  const computer = environment.availableComputers[0]?.label || resourcesQuery.data?.computers[0]?.label || "No computer";
  const python = environment.pythonPath || environment.inspection?.python_path || null;

  return (
    <footer className="relative flex h-7 items-center border-t border-zinc-200 bg-zinc-100 px-2 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
      <StatusButton title={project?.root_path || "No active project"} onClick={() => onOpenTool("files")}><Folder />{project?.name || "No project"}</StatusButton>
      <span className="mx-1 text-zinc-300 dark:text-zinc-700">|</span>
      <StatusButton title={`AiiDA profile: ${profile}`} onClick={() => onOpenTool("aiida")}><Database />{profile}</StatusButton>
      <StatusButton title={`Computer: ${computer}`} onClick={() => onOpenTool("aiida")}><Box />{computer}</StatusButton>
      <StatusButton title={python || "Configure project Python"} onClick={() => onOpenTool("packages")}><Terminal />{shortPath(python)}</StatusButton>
      <div className="ml-auto flex min-w-0 items-center gap-1.5 px-2" title={online ? "AiiDA worker is ready over stdio RPC" : "AiiDA worker is unavailable"}>
        <span className={`h-1.5 w-1.5 rounded-full ${online ? "bg-emerald-500" : statusQuery.isPending ? "bg-amber-400" : "bg-rose-500"}`} />
        <Activity className="h-3 w-3" />
        <span>{online ? "Worker ready" : statusQuery.isPending ? "Connecting" : "Worker unavailable"}</span>
      </div>
      <div className="hidden items-center gap-1 px-2 lg:flex" title="ARIS local workspace"><GitBranch className="h-3 w-3" /> local</div>
      <StatusButton title="Toggle terminal" onClick={onToggleTerminal}><Terminal />{terminalOpen ? "Hide terminal" : "Terminal"}</StatusButton>
    </footer>
  );
}

function StatusButton({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
  return <button className="flex h-full min-w-0 max-w-[230px] items-center gap-1.5 rounded px-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 [&_svg]:h-3 [&_svg]:w-3 [&_svg]:shrink-0" title={title} onClick={onClick}>{children}</button>;
}
