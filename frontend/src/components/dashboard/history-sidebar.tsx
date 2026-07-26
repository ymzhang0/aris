import { ChevronDown, ChevronRight, MoreVertical, Plus, Search, Sparkles, Square, SquareCheck, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { CommandPaletteSelect } from "@/components/ui/command-palette-select";
import { Panel } from "@/components/ui/panel";
import { cn } from "@/lib/utils";
import type { ChatProject, ChatSessionSummary } from "@/types/aiida";

type HistorySidebarProps = {
  projects: ChatProject[];
  sessions: ChatSessionSummary[];
  activeProjectId: string | null;
  activeSessionId: string | null;
  isBusy: boolean;
  canDeleteItems: boolean;
  onActivateSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, title: string) => void;
  onCreateProject: (payload: { name: string; rootPath: string }) => void;
  onDeleteItems: (payload: { projectIds?: string[]; sessionIds?: string[] }) => void;
  onOpenProjectWorkspace: (projectId: string) => void;
};

const DEFAULT_SESSION_TITLE = "New Conversation";

type HistoryContextMenuState =
  | {
      kind: "project";
      id: string;
      x: number;
      y: number;
    }
  | {
      kind: "session";
      id: string;
      x: number;
      y: number;
    };

function formatSessionTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Unknown";
  }
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function HistorySidebar({
  projects,
  sessions,
  activeProjectId,
  activeSessionId,
  isBusy,
  canDeleteItems,
  onActivateSession,
  onRenameSession,
  onCreateProject,
  onDeleteItems,
  onOpenProjectWorkspace,
}: HistorySidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("all");
  const [isProjectFormOpen, setIsProjectFormOpen] = useState(false);
  const [projectNameDraft, setProjectNameDraft] = useState("");
  const [projectPathDraft, setProjectPathDraft] = useState("");
  const [expandedProjects, setExpandedProjects] = useState<Record<string, boolean>>({});
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set());
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(new Set());
  const [contextMenu, setContextMenu] = useState<HistoryContextMenuState | null>(null);
  const renameModeRef = useRef<"commit" | "cancel">("commit");
  const contextMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!activeProjectId) {
      return;
    }
    setExpandedProjects((current) => ({ ...current, [activeProjectId]: true }));
  }, [activeProjectId]);

  useEffect(() => {
    if (!renamingSessionId) {
      return;
    }
    const exists = sessions.some((session) => session.id === renamingSessionId);
    if (!exists) {
      setRenamingSessionId(null);
      setRenameDraft("");
    }
  }, [renamingSessionId, sessions]);

  useEffect(() => {
    const availableProjectIds = new Set(projects.map((project) => project.id));
    setSelectedProjectIds((current) => {
      const next = new Set([...current].filter((projectId) => availableProjectIds.has(projectId)));
      if (next.size === current.size) {
        return current;
      }
      return next;
    });
  }, [projects]);

  useEffect(() => {
    const availableSessionIds = new Set(sessions.map((session) => session.id));
    setSelectedSessionIds((current) => {
      const next = new Set([...current].filter((sessionId) => availableSessionIds.has(sessionId)));
      if (next.size === current.size) {
        return current;
      }
      return next;
    });
  }, [sessions]);

  useEffect(() => {
    if (selectedProjectIds.size > 0 || selectedSessionIds.size > 0) {
      return;
    }
    setSelectionMode(false);
  }, [selectedProjectIds, selectedSessionIds]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!contextMenuRef.current || !(event.target instanceof Node)) {
        setContextMenu(null);
        return;
      }
      if (!contextMenuRef.current.contains(event.target)) {
        setContextMenu(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setContextMenu(null);
      }
    };
    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, []);

  const availableTags = useMemo(
    () =>
      [...new Set(sessions.flatMap((session) => session.tags))]
        .filter(Boolean)
        .sort((left, right) => left.localeCompare(right)),
    [sessions],
  );

  const filteredSessions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return sessions.filter((session) => {
      if (tagFilter !== "all" && !session.tags.includes(tagFilter)) {
        return false;
      }
      if (!query) {
        return true;
      }
      return [session.title, session.preview, session.project_label ?? "", session.tags.join(" "), session.workspace_path]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [searchQuery, sessions, tagFilter]);

  const projectGroups = useMemo(() => {
    const hasFilters = Boolean(searchQuery.trim()) || tagFilter !== "all";
    const sessionsByProject = new Map<string, ChatSessionSummary[]>();
    filteredSessions.forEach((session) => {
      const bucket = sessionsByProject.get(session.project_id) ?? [];
      bucket.push(session);
      sessionsByProject.set(session.project_id, bucket);
    });

    return projects
      .map((project) => ({
        project,
        sessions:
          (sessionsByProject.get(project.id) ?? []).sort((left, right) =>
            right.updated_at.localeCompare(left.updated_at),
          ),
      }))
      .filter(({ sessions: groupSessions }) => !hasFilters || groupSessions.length > 0);
  }, [filteredSessions, projects, searchQuery, tagFilter]);

  const selectedProjectCount = selectedProjectIds.size;
  const selectedSessionCount = selectedSessionIds.size;
  const totalSelectedCount = selectedProjectCount + selectedSessionCount;

  const contextMenuProject = useMemo(
    () =>
      contextMenu?.kind === "project"
        ? projects.find((project) => project.id === contextMenu.id) ?? null
        : null,
    [contextMenu, projects],
  );
  const contextMenuSession = useMemo(
    () =>
      contextMenu?.kind === "session"
        ? sessions.find((session) => session.id === contextMenu.id) ?? null
        : null,
    [contextMenu, sessions],
  );

  const clampMenuPosition = (x: number, y: number) => {
    if (typeof window === "undefined") {
      return { x, y };
    }
    const width = 208;
    const height = 132;
    return {
      x: Math.min(x, Math.max(8, window.innerWidth - width - 8)),
      y: Math.min(y, Math.max(8, window.innerHeight - height - 8)),
    };
  };

  const openProjectContextMenu = (projectId: string, x: number, y: number) => {
    const position = clampMenuPosition(x, y);
    setContextMenu({ kind: "project", id: projectId, ...position });
  };

  const openSessionContextMenu = (sessionId: string, x: number, y: number) => {
    const position = clampMenuPosition(x, y);
    setContextMenu({ kind: "session", id: sessionId, ...position });
  };

  const toggleProjectExpansion = (projectId: string, projectIsActive: boolean) => {
    setExpandedProjects((current) => ({
      ...current,
      [projectId]: !(current[projectId] ?? (projectId === activeProjectId || projectIsActive)),
    }));
  };

  const toggleProjectSelection = (projectId: string) => {
    setSelectionMode(true);
    setSelectedProjectIds((current) => {
      const next = new Set(current);
      if (next.has(projectId)) {
        next.delete(projectId);
      } else {
        next.add(projectId);
      }
      return next;
    });
  };

  const toggleSessionSelection = (sessionId: string) => {
    setSelectionMode(true);
    setSelectedSessionIds((current) => {
      const next = new Set(current);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };

  const clearSelection = () => {
    setSelectionMode(false);
    setSelectedProjectIds(new Set());
    setSelectedSessionIds(new Set());
    setContextMenu(null);
  };

  const submitDeleteSelection = (projectIds: string[], sessionIds: string[]) => {
    if (!canDeleteItems) {
      return;
    }
    onDeleteItems({ projectIds, sessionIds });
    setContextMenu(null);
  };

  const handleCreateProject = () => {
    const cleanedName = projectNameDraft.trim();
    if (!cleanedName) {
      return;
    }
    onCreateProject({ name: cleanedName, rootPath: projectPathDraft.trim() });
    setProjectNameDraft("");
    setProjectPathDraft("");
    setIsProjectFormOpen(false);
  };

  const tagFilterOptions = useMemo(
    () => [
      { value: "all", label: "All Tags" },
      ...availableTags.map((tag) => ({
        value: tag,
        label: tag,
        keywords: [tag.replace(/^#/, "")],
      })),
    ],
    [availableTags],
  );

  const beginRenameSession = (session: ChatSessionSummary) => {
    renameModeRef.current = "commit";
    setRenamingSessionId(session.id);
    setRenameDraft(session.title === DEFAULT_SESSION_TITLE ? "" : session.title);
  };

  const cancelRenameSession = () => {
    renameModeRef.current = "cancel";
    setRenamingSessionId(null);
    setRenameDraft("");
  };

  const commitRenameSession = () => {
    if (renameModeRef.current === "cancel") {
      renameModeRef.current = "commit";
      return;
    }
    if (!renamingSessionId) {
      return;
    }
    onRenameSession(renamingSessionId, renameDraft.trim());
    setRenamingSessionId(null);
    setRenameDraft("");
    renameModeRef.current = "commit";
  };

  return (
    <aside className="flex h-full min-h-0 w-full flex-col gap-2 font-sans tracking-tight">
      <Panel className="flex min-h-0 flex-1 flex-col gap-3 border-zinc-100/90 p-3 dark:border-zinc-800/80">
        <div className="space-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              placeholder="Search projects, sessions, tags..."
              className="h-9 w-full border-0 border-b border-zinc-200 bg-transparent pl-9 pr-3 text-sm text-zinc-700 outline-none transition-colors focus:border-zinc-400 dark:border-zinc-800 dark:text-zinc-200 dark:focus:border-zinc-600"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>

          <div className="flex items-center gap-2 border-b border-zinc-100 pb-1 dark:border-zinc-800">
            <Button
              variant={selectionMode ? "default" : "outline"}
              className="h-9 rounded-none px-3"
              onClick={() => {
                if (selectionMode || totalSelectedCount > 0) {
                  clearSelection();
                  return;
                }
                setSelectionMode(true);
              }}
            >
              {selectionMode || totalSelectedCount > 0 ? "Done" : "Select"}
            </Button>
            <CommandPaletteSelect
              value={tagFilter}
              options={tagFilterOptions}
              label="Tag"
              ariaLabel="Filter by tag"
              searchable={availableTags.length > 6}
              className="flex-1"
              triggerClassName="flex w-full items-center justify-between rounded-none px-2.5 py-2 text-sm"
              onChange={setTagFilter}
            />
            <Button
              variant={isProjectFormOpen ? "outline" : "default"}
              size="icon"
              className="h-9 w-9 shrink-0 rounded-none"
              onClick={() => setIsProjectFormOpen((value) => !value)}
              title="Create a new project"
              aria-label="Create a new project"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>

          {isProjectFormOpen ? (
            <div className="space-y-3 border-t border-zinc-100 px-0 py-3 dark:border-zinc-800">
              <input
                type="text"
                placeholder="Project name"
                className="h-9 w-full border-0 border-b border-zinc-200 bg-transparent px-0 text-sm text-zinc-700 outline-none transition-colors focus:border-zinc-400 dark:border-zinc-800 dark:text-zinc-200 dark:focus:border-zinc-600"
                value={projectNameDraft}
                onChange={(event) => setProjectNameDraft(event.target.value)}
              />
              <input
                type="text"
                placeholder="Disk path (optional, server-side absolute or relative path)"
                className="h-9 w-full border-0 border-b border-zinc-200 bg-transparent px-0 text-sm text-zinc-700 outline-none transition-colors focus:border-zinc-400 dark:border-zinc-800 dark:text-zinc-200 dark:focus:border-zinc-600"
                value={projectPathDraft}
                onChange={(event) => setProjectPathDraft(event.target.value)}
              />
              <div className="flex items-center justify-end gap-2">
                <Button variant="ghost" className="h-8 rounded-none px-3" onClick={() => setIsProjectFormOpen(false)}>
                  Cancel
                </Button>
                <Button className="h-8 rounded-none px-3" onClick={handleCreateProject} disabled={isBusy || !projectNameDraft.trim()}>
                  Create
                </Button>
              </div>
            </div>
          ) : null}
        </div>

        {selectionMode || totalSelectedCount > 0 ? (
          <section className="border-t border-zinc-100 px-0 py-3 dark:border-zinc-800">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500 dark:text-zinc-400">
                  Batch Delete
                </p>
                <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-200">
                  {selectedProjectCount} project{selectedProjectCount === 1 ? "" : "s"} and {selectedSessionCount} session{selectedSessionCount === 1 ? "" : "s"} selected
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  className="h-8 rounded-none px-3"
                  onClick={clearSelection}
                >
                  <X className="h-4 w-4" />
                  Clear
                </Button>
                <Button
                  className="h-8 rounded-none px-3"
                  onClick={() => submitDeleteSelection([...selectedProjectIds], [...selectedSessionIds])}
                  disabled={isBusy || totalSelectedCount === 0 || !canDeleteItems}
                  title={!canDeleteItems ? "Your current role cannot delete projects or sessions." : undefined}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete Selected
                </Button>
              </div>
            </div>
          </section>
        ) : null}

        <div className="minimal-scrollbar min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {projectGroups.length === 0 ? (
            <p className="border-t border-zinc-100 px-0 py-3 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              No project sessions match the current filters.
            </p>
          ) : (
            projectGroups.map(({ project, sessions: groupSessions }) => {
              const defaultExpanded = Boolean(searchQuery.trim()) || project.id === activeProjectId || project.active;
              const isExpanded = expandedProjects[project.id] ?? defaultExpanded;
              const isProjectSelected = selectedProjectIds.has(project.id);
              return (
                <section
                  key={project.id}
                  className={cn(
                    "overflow-hidden border-t border-zinc-200/75 bg-white dark:border-zinc-800/80 dark:bg-zinc-950/35",
                    isProjectSelected && "border-blue-300/90 bg-blue-50/30 dark:border-blue-700/80 dark:bg-blue-950/12",
                  )}
                >
                  <div
                    role="button"
                    tabIndex={0}
                    className="flex w-full items-start justify-between gap-3 px-1 py-3 text-left"
                    onContextMenu={(event) => {
                      event.preventDefault();
                      openProjectContextMenu(project.id, event.clientX, event.clientY);
                    }}
                    onClick={() => {
                      if (selectionMode) {
                        toggleProjectSelection(project.id);
                        return;
                      }
                      onOpenProjectWorkspace(project.id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        if (selectionMode) {
                          toggleProjectSelection(project.id);
                          return;
                        }
                        onOpenProjectWorkspace(project.id);
                      }
                    }}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        {selectionMode || isProjectSelected ? (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              toggleProjectSelection(project.id);
                            }}
                            className="shrink-0 text-zinc-400 hover:text-zinc-700 dark:text-zinc-500 dark:hover:text-zinc-300"
                            aria-label={isProjectSelected ? `Deselect project ${project.name}` : `Select project ${project.name}`}
                          >
                            {isProjectSelected ? <SquareCheck className="h-4 w-4 text-blue-500" /> : <Square className="h-4 w-4" />}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            toggleProjectExpansion(project.id, project.active);
                          }}
                          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-none text-zinc-500 transition-colors hover:text-zinc-800 dark:hover:text-zinc-100"
                          aria-label={isExpanded ? `Collapse project ${project.name}` : `Expand project ${project.name}`}
                        >
                          {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                        <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{project.name}</p>
                      </div>
                      <p className="mt-1 truncate pl-6 text-xs text-zinc-500 dark:text-zinc-400">{project.root_path}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="rounded-full bg-zinc-100 px-2 py-1 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                        {groupSessions.length}
                      </span>
                      <button
                        type="button"
                        onMouseDown={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                        }}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          const rect = event.currentTarget.getBoundingClientRect();
                          openProjectContextMenu(project.id, rect.right - 196, rect.bottom + 6);
                        }}
                        className="rounded-none p-1 text-zinc-400 transition-colors hover:text-zinc-700 dark:hover:text-zinc-200"
                        aria-label={`Open menu for project ${project.name}`}
                      >
                        <MoreVertical className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {isExpanded ? (
                    <div className="space-y-0 border-t border-zinc-200/70 px-0 py-1 dark:border-zinc-800/70">
                      {groupSessions.length === 0 ? (
                        <p className="px-1 py-3 text-sm text-zinc-500 dark:text-zinc-400">
                          No sessions in this project yet.
                        </p>
                      ) : (
                        groupSessions.map((session) => {
                          const isActive = session.id === activeSessionId;
                          const isRenaming = session.id === renamingSessionId;
                          const isTitlePending = session.title_state === "pending";
                          const showPendingSkeleton = isTitlePending && session.title === DEFAULT_SESSION_TITLE;
                          const isSessionSelected = selectedSessionIds.has(session.id);
                          return (
                            <div
                              key={session.id}
                              role="button"
                              tabIndex={0}
                              onContextMenu={(event) => {
                                event.preventDefault();
                                openSessionContextMenu(session.id, event.clientX, event.clientY);
                              }}
                              onClick={() => {
                                if (selectionMode) {
                                  toggleSessionSelection(session.id);
                                  return;
                                }
                                if (isRenaming || isBusy || isActive) {
                                  return;
                                }
                                onActivateSession(session.id);
                              }}
                              onKeyDown={(event) => {
                                if (selectionMode) {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    toggleSessionSelection(session.id);
                                  }
                                  return;
                                }
                                if (isRenaming || isBusy || isActive) {
                                  return;
                                }
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  onActivateSession(session.id);
                                }
                              }}
                              className={cn(
                                "w-full border-b px-4 py-3 text-left transition-colors",
                                "cursor-pointer focus:outline-none focus:bg-zinc-50 dark:focus:bg-zinc-900/45",
                                "border-zinc-100 bg-white hover:bg-zinc-50/70 dark:border-zinc-900 dark:bg-transparent dark:hover:bg-zinc-900/40",
                                isActive && "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/55",
                                isSessionSelected && "border-blue-200 bg-blue-50/40 dark:border-blue-800/70 dark:bg-blue-950/18",
                              )}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div
                                    className="flex min-w-0 items-start gap-2"
                                    onDoubleClick={(event) => {
                                      event.stopPropagation();
                                      beginRenameSession(session);
                                    }}
                                  >
                                    {selectionMode || isSessionSelected ? (
                                      <button
                                        type="button"
                                        onClick={(event) => {
                                          event.preventDefault();
                                          event.stopPropagation();
                                          toggleSessionSelection(session.id);
                                        }}
                                        className="mt-0.5 shrink-0 text-zinc-400 hover:text-zinc-700 dark:text-zinc-500 dark:hover:text-zinc-300"
                                        aria-label={isSessionSelected ? `Deselect session ${session.title}` : `Select session ${session.title}`}
                                      >
                                        {isSessionSelected ? <SquareCheck className="h-4 w-4 text-blue-500" /> : <Square className="h-4 w-4" />}
                                      </button>
                                    ) : null}
                                    {isRenaming ? (
                                      <input
                                        autoFocus
                                        type="text"
                                        value={renameDraft}
                                        onChange={(event) => setRenameDraft(event.target.value)}
                                        onClick={(event) => event.stopPropagation()}
                                        onBlur={commitRenameSession}
                                        onKeyDown={(event) => {
                                          event.stopPropagation();
                                          if (event.key === "Enter") {
                                            event.preventDefault();
                                            event.currentTarget.blur();
                                          }
                                          if (event.key === "Escape") {
                                            event.preventDefault();
                                            cancelRenameSession();
                                          }
                                        }}
                                        className="h-8 w-full border-0 border-b border-zinc-300 bg-transparent px-0 text-sm font-semibold text-zinc-900 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:text-zinc-100 dark:focus:border-zinc-500"
                                        placeholder="Rename session"
                                      />
                                    ) : showPendingSkeleton ? (
                                      <div className="flex items-center gap-2">
                                        <Sparkles className="h-3.5 w-3.5 shrink-0 animate-pulse text-amber-500" />
                                        <div className="h-3 w-24 rounded-full bg-zinc-200/90 dark:bg-zinc-700/80" />
                                      </div>
                                    ) : (
                                      <div className="flex items-center gap-2">
                                        {isTitlePending ? (
                                          <Sparkles className="h-3.5 w-3.5 shrink-0 animate-pulse text-amber-500" />
                                        ) : null}
                                        <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                                          {session.title}
                                        </p>
                                      </div>
                                    )}
                                  </div>
                                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{formatSessionTime(session.updated_at)}</p>
                                </div>
                                <div className="flex shrink-0 items-center gap-2">
                                  <span className="rounded-full bg-zinc-100 px-2 py-1 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                                    {session.message_count} msgs
                                  </span>
                                  <button
                                    type="button"
                                    onMouseDown={(event) => {
                                      event.preventDefault();
                                      event.stopPropagation();
                                    }}
                                    onClick={(event) => {
                                      event.preventDefault();
                                      event.stopPropagation();
                                      const rect = event.currentTarget.getBoundingClientRect();
                                      openSessionContextMenu(session.id, rect.right - 196, rect.bottom + 6);
                                    }}
                                    className="rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                                    aria-label={`Open menu for session ${session.title}`}
                                  >
                                    <MoreVertical className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </div>

                              <p className="mt-2 max-h-10 overflow-hidden text-sm text-zinc-600 dark:text-zinc-300">
                                {session.preview || "No messages yet."}
                              </p>

                              <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px]">
                                <span className="rounded-full border border-zinc-200/80 bg-zinc-50 px-2 py-1 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-950/40 dark:text-zinc-300">
                                  {session.node_count} nodes
                                </span>
                                {session.is_archived ? (
                                  <span className="rounded-full border border-amber-200/80 bg-amber-50 px-2 py-1 text-amber-700 dark:border-amber-900/80 dark:bg-amber-950/40 dark:text-amber-300">
                                    Archived
                                  </span>
                                ) : null}
                                {session.tags.map((tag) => (
                                  <span
                                    key={`${session.id}-${tag}`}
                                    className="rounded-full border border-zinc-200/80 bg-white px-2 py-1 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-950/60 dark:text-zinc-300"
                                  >
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  ) : null}
                </section>
              );
            })
          )}
        </div>

        {contextMenu ? (
          <div
            ref={contextMenuRef}
            className="fixed z-50 min-w-[196px] rounded-xl border border-zinc-200/85 bg-white/95 p-1.5 shadow-xl backdrop-blur dark:border-zinc-800/85 dark:bg-zinc-950/95"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            {contextMenu.kind === "project" && contextMenuProject ? (
              <>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-zinc-700 transition-colors hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-900"
                  onClick={() => {
                    toggleProjectSelection(contextMenuProject.id);
                    setContextMenu(null);
                  }}
                >
                  <span>{selectedProjectIds.has(contextMenuProject.id) ? "Deselect Project" : "Select Project"}</span>
                  {selectedProjectIds.has(contextMenuProject.id) ? <SquareCheck className="h-4 w-4 text-blue-500" /> : <Square className="h-4 w-4" />}
                </button>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-950/40"
                  onClick={() => submitDeleteSelection([contextMenuProject.id], [])}
                  disabled={!canDeleteItems}
                  title={!canDeleteItems ? "Permission required" : undefined}
                >
                  <span>Delete Project</span>
                  <Trash2 className="h-4 w-4" />
                </button>
              </>
            ) : null}
            {contextMenu.kind === "session" && contextMenuSession ? (
              <>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-zinc-700 transition-colors hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-900"
                  onClick={() => {
                    toggleSessionSelection(contextMenuSession.id);
                    setContextMenu(null);
                  }}
                >
                  <span>{selectedSessionIds.has(contextMenuSession.id) ? "Deselect Session" : "Select Session"}</span>
                  {selectedSessionIds.has(contextMenuSession.id) ? <SquareCheck className="h-4 w-4 text-blue-500" /> : <Square className="h-4 w-4" />}
                </button>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-950/40"
                  onClick={() => submitDeleteSelection([], [contextMenuSession.id])}
                  disabled={!canDeleteItems}
                  title={!canDeleteItems ? "Permission required" : undefined}
                >
                  <span>Delete Session</span>
                  <Trash2 className="h-4 w-4" />
                </button>
              </>
            ) : null}
          </div>
        ) : null}
      </Panel>
    </aside>
  );
}
