import {
  type CSSProperties,
  type ReactNode,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import type { NodeRendererProps } from "react-arborist";
import { Tree } from "react-arborist";
import { ChevronRight, Copy, FilePlus2, Loader2, RefreshCw, Search, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { getExplorerNodeIcon, type ExplorerIconNode } from "./file-explorer-icons";

const INDENT_SIZE = 18;
const ROW_HEIGHT = 28;
const CONTEXT_MENU_WIDTH = 176;
const CONTEXT_MENU_HEIGHT = 112;

export type FileExplorerNode = ExplorerIconNode & {
  id: string;
  path: string;
  relativePath: string;
  children?: FileExplorerNode[];
  isLoading?: boolean;
};

export type FileExplorerContextAction = "new-file" | "delete" | "copy-path";

type FileExplorerProps = {
  projectName: string;
  rootPath?: string | null;
  data: FileExplorerNode[];
  isLoading?: boolean;
  onRefresh?: () => void;
  onSelectFile?: (node: FileExplorerNode) => void;
  onToggleDirectory?: (node: FileExplorerNode) => void | Promise<void>;
  onContextAction?: (payload: { action: FileExplorerContextAction; node: FileExplorerNode }) => void | Promise<void>;
  selectedPath?: string | null;
  emptyState?: string;
  className?: string;
};

type ContextMenuState = {
  x: number;
  y: number;
  node: FileExplorerNode;
};

function parsePaddingLeft(style: CSSProperties): number {
  const value = style.paddingLeft;
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function clampMenuPosition(x: number, y: number) {
  if (typeof window === "undefined") {
    return { x, y };
  }

  return {
    x: Math.min(x, window.innerWidth - CONTEXT_MENU_WIDTH - 12),
    y: Math.min(y, window.innerHeight - CONTEXT_MENU_HEIGHT - 12),
  };
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  const normalized = String(text ?? "");
  if (!normalized) {
    return false;
  }

  if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
    return false;
  }
  try {
    await navigator.clipboard.writeText(normalized);
    return true;
  } catch {
    return false;
  }
}

function treeHasMatches(nodes: FileExplorerNode[], term: string): boolean {
  const normalizedTerm = term.trim().toLowerCase();
  if (!normalizedTerm) {
    return nodes.length > 0;
  }

  return nodes.some((node) =>
    node.name.toLowerCase().includes(normalizedTerm) ||
    (Array.isArray(node.children) && treeHasMatches(node.children, normalizedTerm)),
  );
}

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }

      const nextWidth = Math.floor(entry.contentRect.width);
      const nextHeight = Math.floor(entry.contentRect.height);
      setSize((current) => {
        if (current.width === nextWidth && current.height === nextHeight) {
          return current;
        }
        return { width: nextWidth, height: nextHeight };
      });
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, size] as const;
}

type ExplorerNodeRendererProps = NodeRendererProps<FileExplorerNode> & {
  activeSelectedPath: string | null;
  onSelectFile?: (node: FileExplorerNode) => void;
  onToggleDirectory?: (node: FileExplorerNode) => void | Promise<void>;
  setSelectedPath: (path: string) => void;
  setContextMenu: (value: ContextMenuState | null) => void;
};

function ExplorerNode({
  node,
  style,
  dragHandle,
  activeSelectedPath,
  onSelectFile,
  onToggleDirectory,
  setSelectedPath,
  setContextMenu,
}: ExplorerNodeRendererProps) {
  const isDirectory = node.data.type === "directory";
  const isSelectedFile = node.data.type === "file" && node.data.path === activeSelectedPath;
  const depth = Math.max(0, Math.round(parsePaddingLeft(style) / INDENT_SIZE));
  const paddingLeft = 12 + depth * INDENT_SIZE;

  const handlePrimaryAction = () => {
    if (isDirectory) {
      const shouldOpen = !node.isOpen;
      node.toggle();
      if (shouldOpen) {
        void onToggleDirectory?.(node.data);
      }
      return;
    }

    setSelectedPath(node.data.path);
    node.select();
    onSelectFile?.(node.data);
  };

  return (
    <div style={style} className="group">
      <div ref={dragHandle} className="relative h-full">
        {Array.from({ length: depth }, (_, index) => (
          <span
            key={`${node.id}-guide-${index}`}
            className="pointer-events-none absolute inset-y-1 border-l border-slate-700/80"
            style={{ left: `${12 + index * INDENT_SIZE}px` }}
          />
        ))}

        <button
          type="button"
          className={cn(
            "relative flex h-full w-full items-center gap-1.5 rounded-sm border-l-2 border-transparent pr-2 text-left text-[13px] text-slate-700 transition-colors",
            "hover:bg-slate-200/70 dark:text-[#cccccc] dark:hover:bg-white/6",
            isSelectedFile && "border-l-2 border-blue-500 bg-blue-500/10 text-slate-900 dark:bg-[#094771] dark:text-white",
          )}
          style={{ paddingLeft: `${paddingLeft}px` }}
          onClick={handlePrimaryAction}
          onContextMenu={(event) => {
            event.preventDefault();
            if (!isDirectory) {
              setSelectedPath(node.data.path);
              node.select();
              onSelectFile?.(node.data);
            }
            const position = clampMenuPosition(event.clientX, event.clientY);
            setContextMenu({ ...position, node: node.data });
          }}
        >
          <span className="flex h-4 w-4 shrink-0 items-center justify-center text-[#8c8c8c]">
            {isDirectory ? (
              <ChevronRight
                className={cn("h-3.5 w-3.5 transition-transform duration-150", node.isOpen && "rotate-90")}
                strokeWidth={1.75}
              />
            ) : (
              <span className="h-3.5 w-3.5" />
            )}
          </span>

          <span className="flex h-4 w-4 shrink-0 items-center justify-center">
            {getExplorerNodeIcon(node.data, isDirectory && node.isOpen)}
          </span>

          <span className="min-w-0 flex-1 truncate">{node.data.name}</span>

          {isDirectory && node.data.isLoading ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-slate-400 dark:text-slate-500" />
          ) : null}
        </button>
      </div>
    </div>
  );
}

function ContextMenu({
  anchor,
  onClose,
  onSelect,
}: {
  anchor: ContextMenuState;
  onClose: () => void;
  onSelect: (action: FileExplorerContextAction, node: FileExplorerNode) => void;
}) {
  const actions: Array<{ action: FileExplorerContextAction; label: string; icon: ReactNode }> = [
    { action: "new-file", label: "New File", icon: <FilePlus2 className="h-3.5 w-3.5" /> },
    { action: "delete", label: "Delete", icon: <Trash2 className="h-3.5 w-3.5" /> },
    { action: "copy-path", label: "Copy Path", icon: <Copy className="h-3.5 w-3.5" /> },
  ];

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="absolute min-w-44 overflow-hidden rounded-md border border-black/30 bg-[#252526] p-1 text-[12px] text-[#cccccc] shadow-2xl shadow-black/40"
        style={{ left: anchor.x, top: anchor.y }}
      >
        {actions.map((item) => (
          <button
            key={item.action}
            type="button"
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left transition-colors hover:bg-[#094771]"
            onClick={() => {
              onSelect(item.action, anchor.node);
              onClose();
            }}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </div>,
    document.body,
  );
}

export function FileExplorer({
  projectName,
  rootPath,
  data,
  isLoading = false,
  onRefresh,
  onSelectFile,
  onToggleDirectory,
  onContextAction,
  selectedPath,
  emptyState = "No files found in this workspace.",
  className,
}: FileExplorerProps) {
  const [internalSelectedPath, setInternalSelectedPath] = useState<string | null>(selectedPath ?? null);
  const [searchValue, setSearchValue] = useState("");
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const deferredSearchValue = useDeferredValue(searchValue);
  const activeSelectedPath = selectedPath ?? internalSelectedPath;
  const [containerRef, size] = useElementSize<HTMLDivElement>();

  useEffect(() => {
    if (typeof selectedPath === "string") {
      setInternalSelectedPath(selectedPath);
    }
  }, [selectedPath]);

  useEffect(() => {
    if (!contextMenu) {
      return;
    }

    const close = () => setContextMenu(null);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [contextMenu]);

  const hasVisibleMatches = useMemo(
    () => treeHasMatches(data, deferredSearchValue),
    [data, deferredSearchValue],
  );

  const explorerBody = (() => {
    if (isLoading && data.length === 0) {
      return (
        <div className="flex h-full min-h-[240px] items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading workspace tree...
        </div>
      );
    }

    if (data.length === 0) {
      return (
        <div className="flex h-full min-h-[240px] items-center justify-center px-4 text-sm text-slate-500 dark:text-slate-400">
          {emptyState}
        </div>
      );
    }

    if (deferredSearchValue.trim() && !hasVisibleMatches) {
      return (
        <div className="flex h-full min-h-[240px] items-center justify-center px-4 text-sm text-slate-500 dark:text-slate-400">
          No files match "{deferredSearchValue}".
        </div>
      );
    }

    if (size.width <= 0 || size.height <= 0) {
      return null;
    }

    return (
      <Tree<FileExplorerNode>
        data={data}
        width={size.width}
        height={size.height}
        rowHeight={ROW_HEIGHT}
        indent={INDENT_SIZE}
        paddingTop={4}
        paddingBottom={8}
        overscanCount={12}
        openByDefault={false}
        disableDrag
        disableDrop
        selection={activeSelectedPath ?? undefined}
        searchTerm={deferredSearchValue.trim()}
        searchMatch={(node, term) => node.data.name.toLowerCase().includes(term.toLowerCase())}
      >
        {(props) => (
          <ExplorerNode
            {...props}
            activeSelectedPath={activeSelectedPath}
            onSelectFile={onSelectFile}
            onToggleDirectory={onToggleDirectory}
            setSelectedPath={setInternalSelectedPath}
            setContextMenu={setContextMenu}
          />
        )}
      </Tree>
    );
  })();

  return (
    <section
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden bg-white",
        "dark:bg-[#1b1b1b]",
        className,
      )}
    >
      <header className="border-b border-slate-100 px-3 py-2 dark:border-[#313131]">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-[#8c8c8c]">
              Explorer
            </p>
            <p className="truncate text-sm font-medium text-slate-900 dark:text-[#cccccc]">{projectName}</p>
          </div>

          {onRefresh ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 rounded-none text-slate-500 hover:bg-transparent hover:text-slate-900 dark:text-[#8c8c8c] dark:hover:bg-transparent dark:hover:text-white"
              onClick={onRefresh}
              aria-label="Refresh file explorer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          ) : null}
        </div>

        <p className="mt-1 truncate text-[11px] text-slate-500 dark:text-[#8c8c8c]">
          {rootPath || "Workspace path unavailable."}
        </p>

        <div className="relative mt-3">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400 dark:text-[#8c8c8c]" />
          <input
            type="text"
            value={searchValue}
            placeholder="Search files"
            className={cn(
              "h-8 w-full border-0 border-b border-slate-200 bg-transparent pl-8 pr-3 text-[13px] text-slate-800 outline-none transition",
              "placeholder:text-slate-400 focus:border-blue-500",
              "dark:border-[#313131] dark:bg-transparent dark:text-[#cccccc] dark:placeholder:text-[#8c8c8c]",
            )}
            onChange={(event) => {
              const nextValue = event.target.value;
              startTransition(() => {
                setSearchValue(nextValue);
              });
            }}
          />
        </div>
      </header>

      <div
        ref={containerRef}
        className="minimal-scrollbar flex min-h-0 flex-1 flex-col overflow-hidden px-1.5 py-2"
      >
        {explorerBody}
      </div>

      {contextMenu ? (
        <ContextMenu
          anchor={contextMenu}
          onClose={() => setContextMenu(null)}
          onSelect={(action, node) => {
            if (action === "copy-path") {
              void copyTextToClipboard(node.path);
            }
            void onContextAction?.({ action, node });
          }}
        />
      ) : null}
    </section>
  );
}
