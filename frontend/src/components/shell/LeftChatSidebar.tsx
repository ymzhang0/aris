import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  Bell,
  ChevronDown,
  Folder,
  FolderInput,
  MessageSquare,
  Moon,
  MoreHorizontal,
  Plus,
  Search,
  SquarePen,
  Sun,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { ChatProject, ChatSessionSummary } from "@/types/aiida";

type ProjectDraft = {
  name: string;
  rootPath: string;
  pythonInterpreterPath?: string;
  aiidaProfile?: string;
};

export type LeftChatSidebarProps = {
  projects: ChatProject[];
  sessions: ChatSessionSummary[];
  activeProjectId: string | null;
  activeSessionId: string | null;
  isBusy: boolean;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onActivateSession: (sessionId: string) => void;
  onCreateProject: (payload: ProjectDraft) => void;
  onBrowseProjectFolder: () => Promise<string | null>;
  onOpenProjectWorkspace: (projectId: string) => void;
  onNewConversation: (projectId?: string) => void;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
};

export function LeftChatSidebar(props: LeftChatSidebarProps) {
  const [dialogMode, setDialogMode] = useState<"create" | "load" | null>(null);
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [pythonInterpreterPath, setPythonInterpreterPath] = useState("");
  const [aiidaProfile, setAiidaProfile] = useState("");
  const [query, setQuery] = useState("");
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [isBrowsing, setIsBrowsing] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const sessionsByProject = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const grouped = new Map<string, ChatSessionSummary[]>();
    props.sessions
      .filter((session) => !needle || session.title.toLowerCase().includes(needle))
      .forEach((session) => {
        const projectSessions = grouped.get(session.project_id) ?? [];
        projectSessions.push(session);
        grouped.set(session.project_id, projectSessions);
      });
    grouped.forEach((sessions) => sessions.sort((left, right) => right.updated_at.localeCompare(left.updated_at)));
    return grouped;
  }, [props.sessions, query]);

  const openDialog = (mode: "create" | "load") => {
    setProjectMenuOpen(false);
    setDialogMode(mode);
    setName("");
    setRootPath("");
    setPythonInterpreterPath("");
    setAiidaProfile("");
  };

  const browseForFolder = async (mode: "create" | "load") => {
    setIsBrowsing(true);
    try {
      const selectedPath = await props.onBrowseProjectFolder();
      if (!selectedPath) return;
      const fallbackName = selectedPath.split(/[\\/]/).filter(Boolean).at(-1) || "Project";
      if (mode === "load") {
        props.onCreateProject({ name: fallbackName, rootPath: selectedPath });
        setProjectMenuOpen(false);
        return;
      }
      setDialogMode("create");
      setName(fallbackName);
      setRootPath(selectedPath);
      setProjectMenuOpen(false);
    } finally {
      setIsBrowsing(false);
    }
  };

  const submitProject = () => {
    const cleanPath = rootPath.trim();
    if (!cleanPath) return;
    const fallbackName = cleanPath.split(/[\\/]/).filter(Boolean).at(-1) || "Project";
    props.onCreateProject({
      name: name.trim() || fallbackName,
      rootPath: cleanPath,
      pythonInterpreterPath: pythonInterpreterPath.trim() || undefined,
      aiidaProfile: aiidaProfile.trim() || undefined,
    });
    setDialogMode(null);
  };

  if (!props.expanded) {
    return (
      <aside className="flex h-full w-12 flex-col items-center bg-[#f7f7f7] dark:bg-zinc-900">
        <RailButton label="New chat" onClick={() => props.onNewConversation()}><SquarePen /></RailButton>
        <RailButton label="Projects" onClick={() => props.onExpandedChange(true)}><Folder /></RailButton>
        <RailButton label="Recent chats" onClick={() => props.onExpandedChange(true)}><MessageSquare /></RailButton>
        <div className="mt-auto">
          <RailButton label="Toggle theme" onClick={props.onToggleTheme}>{props.theme === "dark" ? <Sun /> : <Moon />}</RailButton>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-[260px] flex-col bg-[#f7f7f7] text-zinc-900 dark:bg-zinc-900 dark:text-zinc-100">
      <div className="flex h-14 shrink-0 items-center px-4">
        <button className="flex items-center gap-1 text-[20px] font-semibold tracking-[-0.03em]" title="ARIS menu">ARIS <ChevronDown className="mt-0.5 h-4 w-4 text-zinc-500" /></button>
        <button className="ml-auto grid h-9 w-9 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-200/70 dark:hover:bg-zinc-800" onClick={() => searchInputRef.current?.focus()} title="Search"><Search className="h-[18px] w-[18px]" /></button>
        <button className="grid h-9 w-9 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-200/70 dark:hover:bg-zinc-800" title="Notifications"><Bell className="h-[18px] w-[18px]" /></button>
      </div>

      <div className="px-3">
        <button className="flex h-12 w-full items-center gap-3 rounded-lg px-2 text-[15px] font-medium hover:bg-zinc-200/70 dark:hover:bg-zinc-800" onClick={() => props.onNewConversation()} disabled={props.isBusy}>
          <SquarePen className="h-5 w-5" /> New chat
        </button>
        <label className="mt-1 flex h-9 items-center gap-2 rounded-lg px-2 text-zinc-500 focus-within:bg-white dark:focus-within:bg-zinc-950">
          <Search className="h-4 w-4" />
          <input ref={searchInputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search chats" className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-zinc-400" />
        </label>
      </div>

      <div className="relative mt-4 flex items-center px-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>Projects</span>
        <button className="ml-auto rounded p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800" onClick={() => setProjectMenuOpen((current) => !current)} title="Project actions"><Plus className="h-3.5 w-3.5" /></button>
        {projectMenuOpen && <div className="absolute right-2 top-7 z-30 w-52 rounded-xl border border-zinc-200 bg-white p-1.5 text-sm font-normal normal-case tracking-normal shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
          <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800" onClick={() => openDialog("create")}><Plus className="h-4 w-4" />New project</button>
          <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800" disabled={isBrowsing} onClick={() => void browseForFolder("load")}><FolderInput className="h-4 w-4" />Import from folder</button>
        </div>}
      </div>
      <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {props.projects.map((project) => {
          const projectSessions = sessionsByProject.get(project.id) ?? [];
          return (
            <div key={project.id} className="mb-1">
              <div className={cn("group flex h-9 items-center rounded-lg hover:bg-zinc-200/70 dark:hover:bg-zinc-800", project.id === props.activeProjectId && "bg-zinc-200/70 font-medium dark:bg-zinc-800")}>
                <button className="flex h-full min-w-0 flex-1 items-center gap-2 px-2 text-left text-sm" onClick={() => props.onOpenProjectWorkspace(project.id)}>
                  <Folder className="h-4 w-4 shrink-0 text-zinc-500" />
                  <span className="min-w-0 flex-1 truncate">{project.name}</span>
                </button>
                <button className="mr-1 grid h-7 w-7 shrink-0 place-items-center rounded-md text-zinc-400 opacity-0 hover:bg-zinc-300/70 hover:text-zinc-800 group-hover:opacity-100 dark:hover:bg-zinc-700 dark:hover:text-zinc-100" onClick={() => props.onNewConversation(project.id)} title={`New chat in ${project.name}`} aria-label={`New chat in ${project.name}`}>
                  <SquarePen className="h-3.5 w-3.5" />
                </button>
              </div>
              {projectSessions.map((session) => (
                <button key={session.id} className={cn("group ml-5 flex w-[calc(100%-1.25rem)] items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] text-zinc-600 hover:bg-zinc-200/70 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100", session.id === props.activeSessionId && "bg-zinc-200/70 font-medium text-zinc-950 dark:bg-zinc-800 dark:text-zinc-100")} onClick={() => props.onActivateSession(session.id)}>
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                  <span className="min-w-0 flex-1 truncate">{session.title}</span>
                  <MoreHorizontal className="h-3.5 w-3.5 opacity-0 group-hover:opacity-100" />
                </button>
              ))}
            </div>
          );
        })}
        {!props.projects.length && <p className="px-2 py-3 text-xs text-zinc-500">No projects yet</p>}
      </div>

      <button className="flex h-11 items-center gap-3 border-t border-zinc-200 px-4 text-xs text-zinc-500 hover:bg-zinc-100 dark:border-zinc-800 dark:hover:bg-zinc-800" onClick={props.onToggleTheme}>
        {props.theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        {props.theme === "dark" ? "Light appearance" : "Dark appearance"}
      </button>

      {dialogMode && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4" onMouseDown={() => setDialogMode(null)}>
          <div className="w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-5 shadow-2xl dark:border-zinc-700 dark:bg-zinc-900" onMouseDown={(event) => event.stopPropagation()}>
            <div className="flex items-center"><h2 className="text-base font-semibold">{dialogMode === "create" ? "Create project" : "Load project folder"}</h2><button className="ml-auto rounded-lg p-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800" onClick={() => setDialogMode(null)}><X className="h-4 w-4" /></button></div>
            <p className="mt-1 text-sm text-zinc-500">The project stays linked to this local folder.</p>
            {dialogMode === "create" && <label className="mt-5 block text-xs font-medium text-zinc-600 dark:text-zinc-300">Project name<input autoFocus value={name} onChange={(event) => setName(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-zinc-300 bg-transparent px-3 text-sm outline-none focus:border-zinc-500 dark:border-zinc-700" placeholder="Silicon EOS" /></label>}
            <label className="mt-4 block text-xs font-medium text-zinc-600 dark:text-zinc-300">Local folder<div className="mt-1.5 flex gap-2"><input autoFocus={dialogMode === "load"} value={rootPath} onChange={(event) => setRootPath(event.target.value)} onKeyDown={(event) => event.key === "Enter" && submitProject()} className="h-10 min-w-0 flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 font-mono text-xs outline-none focus:border-zinc-500 dark:border-zinc-700" placeholder="/Users/me/Projects/my-project" /><button type="button" className="rounded-lg border border-zinc-300 px-3 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800" disabled={isBrowsing} onClick={() => void browseForFolder(dialogMode)}>Browse</button></div></label>
            {dialogMode === "create" && <>
              <label className="mt-4 block text-xs font-medium text-zinc-600 dark:text-zinc-300">Project Python<input value={pythonInterpreterPath} onChange={(event) => setPythonInterpreterPath(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-zinc-300 bg-transparent px-3 font-mono text-xs outline-none focus:border-zinc-500 dark:border-zinc-700" placeholder="/path/to/project/.venv/bin/python" /></label>
              <label className="mt-4 block text-xs font-medium text-zinc-600 dark:text-zinc-300">AiiDA profile <span className="font-normal text-zinc-400">(optional)</span><input value={aiidaProfile} onChange={(event) => setAiidaProfile(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-zinc-300 bg-transparent px-3 text-sm outline-none focus:border-zinc-500 dark:border-zinc-700" placeholder="dev" /></label>
              <p className="mt-2 text-xs text-zinc-500">ARIS will run this project's worker with exactly this Python and profile.</p>
            </>}
            <div className="mt-5 flex justify-end gap-2"><button className="rounded-lg px-3 py-2 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800" onClick={() => setDialogMode(null)}>Cancel</button><button className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900" disabled={!rootPath.trim() || (dialogMode === "create" && !pythonInterpreterPath.trim())} onClick={submitProject}>{dialogMode === "create" ? "Create" : "Load"}</button></div>
          </div>
        </div>
      )}
    </aside>
  );
}

function RailButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return <button className="mb-1 grid h-9 w-9 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-200/70 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100 [&_svg]:h-4 [&_svg]:w-4" onClick={onClick} title={label} aria-label={label}>{children}</button>;
}
