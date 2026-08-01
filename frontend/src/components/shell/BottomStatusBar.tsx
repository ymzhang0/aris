import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Activity, Box, Database, Folder, GitBranch, Terminal } from "lucide-react";

import { aiidaClient } from "@/api";
import { useEnvironmentActions, useEnvironmentStore } from "@/store/EnvironmentStore";
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
  const { setPythonPath, setUseWorkerDefault, resetPythonPath } = useEnvironmentActions();
  const [pythonMenuOpen, setPythonMenuOpen] = useState(false);
  const [pythonDraft, setPythonDraft] = useState(environment.pythonPath ?? "");
  const pythonMenuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => setPythonDraft(environment.pythonPath ?? ""), [environment.pythonPath]);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!pythonMenuRef.current?.contains(event.target as Node)) setPythonMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
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
      <div ref={pythonMenuRef} className="relative h-full">
        <StatusButton title={python || "Python selected automatically"} onClick={() => setPythonMenuOpen((open) => !open)}><Terminal />{shortPath(python)}</StatusButton>
        {pythonMenuOpen && <div className="absolute bottom-8 left-0 z-50 w-[360px] rounded-xl border border-zinc-200 bg-white p-4 text-zinc-800 shadow-2xl dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100">
          <div className="text-sm font-semibold">Python environment</div>
          <p className="mt-1 text-xs text-zinc-500">Choose the runtime used by this project.</p>
          <label className="mt-4 flex items-center gap-2 text-xs"><input type="checkbox" checked={!environment.useWorkerDefault} onChange={(event) => setUseWorkerDefault(!event.target.checked)} />Use a custom interpreter</label>
          <input className="mt-3 h-9 w-full rounded-lg border border-zinc-300 bg-transparent px-3 font-mono text-[11px] outline-none disabled:opacity-45 dark:border-zinc-700" value={pythonDraft} onChange={(event) => setPythonDraft(event.target.value)} disabled={environment.useWorkerDefault} placeholder="/path/to/.venv/bin/python" />
          <div className="mt-3 flex justify-end gap-2"><button className="rounded-lg px-3 py-1.5 text-xs hover:bg-zinc-100 disabled:opacity-40 dark:hover:bg-zinc-800" disabled={environment.useWorkerDefault} onClick={resetPythonPath}>Auto detect</button><button className="rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900" disabled={environment.useWorkerDefault || !pythonDraft.trim()} onClick={() => { setPythonPath(pythonDraft); setPythonMenuOpen(false); }}>Apply</button></div>
        </div>}
      </div>
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
