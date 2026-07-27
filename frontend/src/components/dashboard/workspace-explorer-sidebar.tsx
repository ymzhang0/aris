import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Loader2 } from "lucide-react";

import { FileExplorer, type FileExplorerNode } from "@/components/dashboard/FileExplorer";
import { SidebarPageHeader } from "@/components/dashboard/sidebar-page-header";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { getChatProjectWorkspace } from "@/lib/api";
import type { ChatProject, ChatProjectWorkspaceResponse, WorkspaceEntry } from "@/types/aiida";

type WorkspaceExplorerSidebarProps = {
  project: ChatProject | null;
  onOpenFile?: (payload: WorkspaceExplorerFileSelection) => void;
};

export type WorkspaceExplorerFileSelection = {
  projectId: string;
  projectName: string;
  path: string;
  relativePath: string;
};

function normalizeRelativePath(value?: string | null): string {
  return String(value ?? "")
    .trim()
    .replace(/^\/+/, "")
    .replace(/\/+$/, "");
}

function sortEntries(entries: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...entries].sort((left, right) => {
    if (left.is_dir !== right.is_dir) {
      return left.is_dir ? -1 : 1;
    }

    return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
  });
}

function buildExplorerNodes(
  entries: WorkspaceEntry[],
  workspaceByPath: Record<string, ChatProjectWorkspaceResponse>,
  loadingPaths: Set<string>,
): FileExplorerNode[] {
  return sortEntries(entries).map((entry) => {
    const normalizedPath = normalizeRelativePath(entry.relative_path);
    const childWorkspace = entry.is_dir ? workspaceByPath[normalizedPath] : undefined;

    return {
      id: entry.path || normalizedPath || entry.name,
      name: entry.name,
      type: entry.is_dir ? "directory" : "file",
      path: entry.path,
      relativePath: normalizedPath,
      isLoading: entry.is_dir ? loadingPaths.has(normalizedPath) : false,
      children: entry.is_dir ? buildExplorerNodes(childWorkspace?.entries ?? [], workspaceByPath, loadingPaths) : undefined,
    };
  });
}

export function WorkspaceExplorerSidebar({ project, onOpenFile }: WorkspaceExplorerSidebarProps) {
  const [workspaceByPath, setWorkspaceByPath] = useState<Record<string, ChatProjectWorkspaceResponse>>({});
  const [loadingPaths, setLoadingPaths] = useState<string[]>([]);
  const [failedPaths, setFailedPaths] = useState<Record<string, string>>({});
  const activeProjectIdRef = useRef<string | null>(null);
  const workspaceByPathRef = useRef<Record<string, ChatProjectWorkspaceResponse>>({});
  const loadingPathSetRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    activeProjectIdRef.current = project?.id ?? null;
  }, [project?.id]);

  useEffect(() => {
    workspaceByPathRef.current = workspaceByPath;
  }, [workspaceByPath]);

  const loadDirectory = useCallback(
    async (relativePath?: string, force = false) => {
      if (!project?.id) {
        return;
      }

      const normalizedPath = normalizeRelativePath(relativePath);
      if (!force && workspaceByPathRef.current[normalizedPath]) {
        return;
      }
      if (loadingPathSetRef.current.has(normalizedPath)) {
        return;
      }

      loadingPathSetRef.current.add(normalizedPath);
      setLoadingPaths((current) => (current.includes(normalizedPath) ? current : [...current, normalizedPath]));
      setFailedPaths((current) => {
        if (!current[normalizedPath]) {
          return current;
        }

        const next = { ...current };
        delete next[normalizedPath];
        return next;
      });

      try {
        const response = await getChatProjectWorkspace(project.id, normalizedPath || undefined);
        if (activeProjectIdRef.current !== project.id) {
          return;
        }

        const responsePath = normalizeRelativePath(response.relative_path);
        setWorkspaceByPath((current) => ({
          ...current,
          [responsePath]: response,
        }));
      } catch (error) {
        console.error("Failed to load workspace directory", error);
        if (activeProjectIdRef.current !== project.id) {
          return;
        }

        setFailedPaths((current) => ({
          ...current,
          [normalizedPath]: "Failed to load directory.",
        }));
      } finally {
        loadingPathSetRef.current.delete(normalizedPath);
        setLoadingPaths((current) => current.filter((path) => path !== normalizedPath));
      }
    },
    [project?.id],
  );

  const refreshWorkspace = useCallback(() => {
    workspaceByPathRef.current = {};
    loadingPathSetRef.current.clear();
    setWorkspaceByPath({});
    setLoadingPaths([]);
    setFailedPaths({});

    if (project?.id) {
      void loadDirectory("", true);
    }
  }, [loadDirectory, project?.id]);

  useEffect(() => {
    refreshWorkspace();
  }, [refreshWorkspace]);

  const rootWorkspace = workspaceByPath[""] ?? null;
  const loadingPathLookup = useMemo(() => new Set(loadingPaths), [loadingPaths]);
  const treeData = useMemo(
    () => buildExplorerNodes(rootWorkspace?.entries ?? [], workspaceByPath, loadingPathLookup),
    [loadingPathLookup, rootWorkspace?.entries, workspaceByPath],
  );

  const rootPathLabel = rootWorkspace?.workspace_path ?? project?.root_path ?? "";
  const rootIsLoading = loadingPaths.includes("");
  const rootError = failedPaths[""];

  return (
    <aside className="flex h-full min-h-0 w-full flex-col">
      <Panel className="flex min-h-0 flex-1 flex-col gap-3 border-zinc-100/90 p-3 dark:border-zinc-800/80">
        <SidebarPageHeader
          title="Workspace"
          subtitle={project ? (
            <span title={rootPathLabel || project.name}>
              {project.name}
              {rootPathLabel ? ` · ${rootPathLabel}` : ""}
            </span>
          ) : "Open a project to browse its files"}
        />

        {!project ? (
          <div className="flex h-full min-h-0 items-center justify-center px-1 py-6 text-center text-sm text-zinc-500 dark:text-zinc-400">
            Open a project from the Projects view, then its workspace tree will stay here.
          </div>
        ) : (
          <>
            {rootError && !rootWorkspace ? (
              <div className="space-y-3 border-t border-red-200 px-0 py-3 text-sm text-red-700 dark:border-red-900/80 dark:text-red-300">
                <p>{rootError}</p>
                <div>
                  <Button
                    variant="ghost"
                    className="h-8 rounded-none px-3"
                    onClick={() => {
                      refreshWorkspace();
                    }}
                  >
                    Retry
                  </Button>
                </div>
              </div>
            ) : null}

            <div className="min-h-0 flex-1">
              <FileExplorer
                projectName={project.name}
                rootPath={rootPathLabel}
                data={treeData}
                isLoading={rootIsLoading && !rootWorkspace}
                emptyState="Workspace is empty."
                compactHeader
                onRefresh={refreshWorkspace}
                onSelectFile={(node) => {
                  onOpenFile?.({
                    projectId: project.id,
                    projectName: project.name,
                    path: node.path,
                    relativePath: node.relativePath,
                  });
                }}
                onToggleDirectory={(node) => {
                  void loadDirectory(node.relativePath);
                }}
                onContextAction={({ action, node }) => {
                  if (action === "copy-path") {
                    return;
                  }

                  console.info("Workspace explorer action is not wired yet.", {
                    action,
                    path: node.path,
                    relativePath: node.relativePath,
                  });
                }}
              />
            </div>

            {rootIsLoading && rootWorkspace ? (
              <div className="flex items-center gap-2 px-1 text-xs text-zinc-500 dark:text-zinc-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Refreshing workspace tree...
              </div>
            ) : null}
          </>
        )}
      </Panel>
    </aside>
  );
}
