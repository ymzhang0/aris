import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, FolderOpen, PackagePlus, RefreshCw, Trash2 } from "lucide-react";

import {
  getProjectPackages,
  installProjectPackage,
  setupProjectEnvironment,
  uninstallProjectPackage,
} from "@/api";
import type { ChatProject, ProjectPackagesResponse } from "@/types/aiida";

type Props = {
  project: ChatProject | null;
  onBrowseDirectory: () => Promise<string | null>;
};

function errorMessage(error: unknown): string {
  if (!error || typeof error !== "object") return "Package operation failed.";
  const response = (error as { response?: { data?: { detail?: { reason?: string; error?: string } } } }).response;
  return response?.data?.detail?.reason
    || response?.data?.detail?.error
    || (error as Error).message
    || "Package operation failed.";
}

export function ProjectPackagesSidebar({ project, onBrowseDirectory }: Props) {
  const queryClient = useQueryClient();
  const projectId = project?.id ?? null;
  const queryKey = ["project-packages", projectId] as const;
  const [requirement, setRequirement] = useState("");
  const [editablePath, setEditablePath] = useState("");
  const [existingPython, setExistingPython] = useState("");
  const [profile, setProfile] = useState(project?.aiida_profile ?? "");
  const [operationError, setOperationError] = useState<string | null>(null);

  useEffect(() => {
    setExistingPython(project?.python_interpreter_path ?? "");
    setProfile(project?.aiida_profile ?? "");
    setOperationError(null);
  }, [project?.aiida_profile, project?.id, project?.python_interpreter_path]);

  const packagesQuery = useQuery({
    queryKey,
    queryFn: () => getProjectPackages(projectId!),
    enabled: Boolean(projectId),
    refetchOnWindowFocus: false,
  });

  const applyResponse = (response: ProjectPackagesResponse) => {
    queryClient.setQueryData(queryKey, response);
    setOperationError(null);
    void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    void queryClient.invalidateQueries({ queryKey: ["aiida-bridge-status"] });
    void queryClient.invalidateQueries({ queryKey: ["aiida-bridge-resources"] });
  };

  const environmentMutation = useMutation({
    mutationFn: (payload: { mode: "managed" | "existing"; python_interpreter_path?: string; aiida_profile?: string }) =>
      setupProjectEnvironment(projectId!, payload),
    onSuccess: applyResponse,
    onError: (error) => setOperationError(errorMessage(error)),
  });
  const installMutation = useMutation({
    mutationFn: (payload: { kind: "registry"; requirement: string } | { kind: "editable"; source_path: string }) =>
      installProjectPackage(projectId!, payload),
    onSuccess: (response) => {
      applyResponse(response);
      setRequirement("");
      setEditablePath("");
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });
  const uninstallMutation = useMutation({
    mutationFn: (name: string) => uninstallProjectPackage(projectId!, name),
    onSuccess: applyResponse,
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const data = packagesQuery.data;
  const busy = environmentMutation.isPending || installMutation.isPending || uninstallMutation.isPending;
  const installedPackages = useMemo(() => data?.packages ?? [], [data?.packages]);
  const displayedError = operationError || (packagesQuery.error ? errorMessage(packagesQuery.error) : null);

  if (!project) {
    return <div className="p-5 text-sm text-zinc-500">Open a project to manage its Python environment.</div>;
  }

  return (
    <section className="space-y-5 p-4">
      <header>
        <div className="flex items-center gap-2"><Box className="h-4 w-4" /><h2 className="text-sm font-semibold">Project packages</h2></div>
        <p className="mt-1 truncate text-xs text-zinc-500" title={project.root_path}>{project.name}</p>
      </header>

      {displayedError ? <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">{displayedError}</div> : null}

      <div className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Python environment</div>
        {data?.configured ? <>
          <p className="mt-2 break-all font-mono text-[11px] text-zinc-700 dark:text-zinc-300">{data.python_interpreter_path}</p>
          <div className="mt-2 flex items-center gap-2 text-xs"><span className={`h-2 w-2 rounded-full ${data.runtime_ready ? "bg-emerald-500" : "bg-amber-500"}`} />{data.runtime_ready ? "AiiDA runtime ready" : "aiida-core or worker dependencies are missing"}</div>
        </> : <p className="mt-2 text-xs text-zinc-500">This project does not have a configured Python runtime.</p>}
        <label className="mt-4 block text-xs text-zinc-500">AiiDA profile<input value={profile} onChange={(event) => setProfile(event.target.value)} placeholder="dev (optional)" className="mt-1.5 h-9 w-full rounded-lg border border-zinc-300 bg-transparent px-3 text-xs outline-none dark:border-zinc-700" /></label>
        <button disabled={busy} onClick={() => environmentMutation.mutate({ mode: "managed", aiida_profile: profile.trim() || undefined })} className="mt-3 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-zinc-900 px-3 text-xs font-medium text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900"><PackagePlus className="h-4 w-4" />{data?.configured ? "Create or repair managed .venv" : "Create managed .venv"}</button>
        <div className="my-3 flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-400"><span className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />or attach existing<span className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" /></div>
        <input value={existingPython} onChange={(event) => setExistingPython(event.target.value)} placeholder="/path/to/.venv/bin/python" className="h-9 w-full rounded-lg border border-zinc-300 bg-transparent px-3 font-mono text-[11px] outline-none dark:border-zinc-700" />
        <button disabled={busy || !existingPython.trim()} onClick={() => environmentMutation.mutate({ mode: "existing", python_interpreter_path: existingPython.trim(), aiida_profile: profile.trim() || undefined })} className="mt-2 h-8 w-full rounded-lg border border-zinc-300 text-xs disabled:opacity-40 dark:border-zinc-700">Use this interpreter</button>
      </div>

      {data?.configured ? <>
        <div className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Install from package index</div>
          <input value={requirement} onChange={(event) => setRequirement(event.target.value)} placeholder="aiida-quantumespresso>=4.16" className="mt-3 h-9 w-full rounded-lg border border-zinc-300 bg-transparent px-3 font-mono text-[11px] outline-none dark:border-zinc-700" />
          <button disabled={busy || !requirement.trim()} onClick={() => installMutation.mutate({ kind: "registry", requirement: requirement.trim() })} className="mt-2 h-8 w-full rounded-lg border border-zinc-300 text-xs disabled:opacity-40 dark:border-zinc-700">Install requirement</button>
        </div>

        <div className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Install local development package</div>
          <div className="mt-3 flex gap-2"><input value={editablePath} onChange={(event) => setEditablePath(event.target.value)} placeholder="/path/to/local/aiida-plugin" className="h-9 min-w-0 flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 font-mono text-[11px] outline-none dark:border-zinc-700" /><button disabled={busy} onClick={() => void onBrowseDirectory().then((path) => path && setEditablePath(path))} title="Browse" className="grid h-9 w-9 place-items-center rounded-lg border border-zinc-300 dark:border-zinc-700"><FolderOpen className="h-4 w-4" /></button></div>
          <button disabled={busy || !editablePath.trim()} onClick={() => installMutation.mutate({ kind: "editable", source_path: editablePath.trim() })} className="mt-2 h-8 w-full rounded-lg border border-zinc-300 text-xs disabled:opacity-40 dark:border-zinc-700">Install editable</button>
        </div>
      </> : null}

      <div>
        <div className="mb-2 flex items-center"><div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Installed ({installedPackages.length})</div><button disabled={packagesQuery.isFetching} onClick={() => void packagesQuery.refetch()} className="ml-auto rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-900" title="Refresh"><RefreshCw className={`h-3.5 w-3.5 ${packagesQuery.isFetching ? "animate-spin" : ""}`} /></button></div>
        <div className="space-y-1">
          {installedPackages.map((item) => {
            const protectedPackage = ["aiida-core", "pydantic"].includes(item.name.toLowerCase().replace(/_/g, "-"));
            return <div key={item.name} className="group flex items-center gap-2 rounded-xl px-3 py-2 hover:bg-zinc-100 dark:hover:bg-zinc-900"><div className="min-w-0 flex-1"><div className="truncate text-xs font-medium">{item.name}</div><div className="truncate text-[10px] text-zinc-500">{item.version}{item.editable ? " · editable" : ""}</div></div>{!protectedPackage ? <button disabled={busy} onClick={() => { if (window.confirm(`Uninstall ${item.name} from this project environment?`)) uninstallMutation.mutate(item.name); }} className="rounded-lg p-1.5 text-zinc-400 opacity-0 hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 dark:hover:bg-red-950/40" title={`Uninstall ${item.name}`}><Trash2 className="h-3.5 w-3.5" /></button> : null}</div>;
          })}
          {!packagesQuery.isPending && installedPackages.length === 0 ? <p className="py-4 text-center text-xs text-zinc-500">No packages found.</p> : null}
        </div>
      </div>
    </section>
  );
}
