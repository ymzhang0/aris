import { aiidaClient } from "@/api";
import { useEffect, useState, type MouseEvent as ReactMouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import JsonView from "@uiw/react-json-view";
import { nordTheme } from "@uiw/react-json-view/nord";
import { vscodeTheme } from "@uiw/react-json-view/vscode";
import {
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  FileText,
  GitBranch,
  Loader2,
  X,
  Box,
  Database,
  Activity,
  FileCode,
  Table as TableIcon,
  BarChart3,
  Waves
} from "lucide-react";

import {
  getBandsPlotData,
  getRemoteFileContent,
  getRemoteFiles,
  getRepositoryFileContent,
  getRepositoryFiles,
} from "@/api";
import { cn } from "@/lib/utils";
import type {
  FocusNode,
  BandsPlotData,
  BandsPlotPath,
  BandsPlotResponse,
  NodeFileContentResponse,
  NodeFileListResponse,
  ProcessDetailResponse,
  ProcessDiagnosticsResponse,
  ProcessItem,
  ProcessLogsResponse,
  ProcessNodeLink,
  ProcessTreeNode,
  ProcessWorkgraphNode,
  ProcessWorkgraphResponse,
} from "@/types/aiida";

type ProcessDetailDrawerProps = {
  process: ProcessItem | null;
  onClose: () => void;
  onAddContextNode: (node: FocusNode) => void;
  onExplainFailure: (process: ProcessItem, diagnostics: ProcessDiagnosticsResponse | null) => void;
};

type PreviewableNode = {
  pk?: number;
  label?: string | null;
  node_type: string;
  preview_info?: Record<string, unknown> | null;
};

type InspectorLinkDirection = "input" | "output";

type InspectorTarget = {
  pk: number;
  label: string;
  nodeType: string;
  breadcrumb: string;
  relation: "root" | InspectorLinkDirection;
  previewInfo?: Record<string, unknown> | null;
};

type InspectorPanelProps = {
  target: InspectorTarget;
  fallbackPreviewNode: PreviewableNode | null;
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void;
  onAddContextNode: (node: FocusNode) => void;
  onExplainFailure: (process: ProcessItem, diagnostics: ProcessDiagnosticsResponse | null) => void;
  preferredMode?: InspectorMode;
};

type ProcessTreeNodeViewProps = {
  label: string;
  node: ProcessTreeNode;
  depth?: number;
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void;
  onAddContextNode: (node: FocusNode) => void;
};

type NodeLinksBlockProps = {
  title: string;
  links: Record<string, ProcessNodeLink>;
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void;
  onAddContextNode: (node: FocusNode) => void;
  emptyText: string;
  compact?: boolean;
  showTitle?: boolean;
};

type WorkgraphNodeCardProps = {
  node: ProcessWorkgraphNode;
  outgoingLabels: string[];
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void;
  onAddContextNode: (node: FocusNode) => void;
};

type WorkgraphViewMode = "graph" | "stage";

type WorkgraphGraphLayoutNode = {
  node: ProcessWorkgraphNode;
  levelIndex: number;
  rowIndex: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

const LOG_SNIPPET_LINE_LIMIT = 80;
const RUNNING_STATES = new Set(["running", "created", "waiting"]);
const FINISHED_STATES = new Set(["finished", "success", "completed", "ok"]);
const FAILED_STATES = new Set(["failed", "excepted", "killed", "error"]);
const WORKCHAIN_NODE_HINTS = ["workchain", "workflow"];

type InspectorMode = "overview" | "diagnostics";

const WORKGRAPH_GRAPH_NODE_WIDTH = 272;
const WORKGRAPH_GRAPH_NODE_MIN_HEIGHT = 148;
const WORKGRAPH_GRAPH_COLUMN_GAP = 132;
const WORKGRAPH_GRAPH_ROW_GAP = 30;
const WORKGRAPH_GRAPH_PADDING = 28;

type StatusTone = {
  dotClassName: string;
  textClassName: string;
};

function normalizeState(state: string | null | undefined): string {
  return String(state || "unknown").trim().replace(/_/g, " ").toLowerCase();
}

function toDisplayStatus(state: string | null | undefined): string {
  const normalized = normalizeState(state);
  if (!normalized) {
    return "Unknown";
  }
  return normalized
    .split(" ")
    .filter(Boolean)
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}

function getStatusTone(state: string | null | undefined): StatusTone {
  const normalized = normalizeState(state);
  if (FAILED_STATES.has(normalized)) {
    return {
      dotClassName: "bg-rose-500",
      textClassName: "text-rose-600 dark:text-rose-300",
    };
  }
  if (RUNNING_STATES.has(normalized)) {
    return {
      dotClassName: "bg-blue-500",
      textClassName: "text-blue-600 dark:text-blue-300",
    };
  }
  if (FINISHED_STATES.has(normalized)) {
    return {
      dotClassName: "bg-emerald-500",
      textClassName: "text-emerald-600 dark:text-emerald-300",
    };
  }
  return {
    dotClassName: "bg-zinc-400 dark:bg-zinc-500",
    textClassName: "text-zinc-500 dark:text-zinc-400",
  };
}

function parseDate(value: unknown): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "string" || typeof value === "number") {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return null;
}

function formatSeconds(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

function durationFromValue(raw: unknown): string | null {
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return formatSeconds(raw);
  }
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return null;
}

function extractProcessMeta(preview: Record<string, unknown> | null, fallbackState?: string | null): {
  state: string | null;
  duration: string | null;
} {
  const rawState = preview?.state ?? fallbackState ?? null;
  const state =
    typeof rawState === "string" && rawState.trim()
      ? toDisplayStatus(rawState)
      : fallbackState && fallbackState.trim()
        ? toDisplayStatus(fallbackState)
        : null;
  const duration = durationFromValue(
    preview?.execution_time_seconds ??
      preview?.wall_time_seconds ??
      preview?.duration ??
      preview?.elapsed ??
      null,
  );
  return { state, duration };
}

function getDurationLabel(node: ProcessTreeNode): string {
  const payload = node as Record<string, unknown>;
  const directDuration = durationFromValue(payload.duration ?? payload.elapsed ?? payload.runtime ?? payload.wall_time ?? payload.wallclock);
  if (directDuration) {
    return directDuration;
  }

  const start = parseDate(payload.ctime ?? payload.created_at ?? payload.started_at ?? payload.start_time);
  const end = parseDate(payload.mtime ?? payload.updated_at ?? payload.finished_at ?? payload.end_time);
  if (start && end && end.getTime() >= start.getTime()) {
    return formatSeconds((end.getTime() - start.getTime()) / 1000);
  }
  if (start && RUNNING_STATES.has(normalizeState(node.state))) {
    return `${formatSeconds((Date.now() - start.getTime()) / 1000)}+`;
  }
  return "\u2014";
}

function normalizePreview(node: PreviewableNode): Record<string, unknown> | null {
  const preview = node.preview_info;
  if (!preview || typeof preview !== "object" || Array.isArray(preview)) {
    return null;
  }
  return preview;
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((entry) => String(entry || "").trim()).filter(Boolean);
}

function formatPrimitivePreviewValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "undefined";
  }
  return JSON.stringify(value);
}

function StructurePreviewCard({ preview }: { preview: Record<string, unknown> }) {
  const lattice = (preview.lattice && typeof preview.lattice === "object" && !Array.isArray(preview.lattice))
    ? (preview.lattice as Record<string, number>)
    : null;
  const positions = Array.isArray(preview.positions) ? preview.positions : [];
  const symmetry =
    preview.symmetry && typeof preview.symmetry === "object" && !Array.isArray(preview.symmetry)
      ? (preview.symmetry as Record<string, unknown>)
      : null;
  const [positionMode, setPositionMode] = useState<"cartesian" | "fractional">("cartesian");
  const canShowFractional = positions.every((rawPosition) => {
    const position = rawPosition as { fractional_position?: number[] };
    return Array.isArray(position.fractional_position)
      && position.fractional_position.length === 3
      && position.fractional_position.every((value) => Number.isFinite(Number(value)));
  });

  useEffect(() => {
    if (!canShowFractional && positionMode === "fractional") {
      setPositionMode("cartesian");
    }
  }, [canShowFractional, positionMode]);

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
        <Box className="h-4 w-4 text-blue-500" />
        <h4 className="text-sm font-semibold">Structure Summary</h4>
      </div>
      <div className="grid grid-cols-2 gap-4 text-xs">
        <div>
          <p className="text-zinc-500">Formula</p>
          <p className="font-medium text-blue-600 dark:text-blue-400">{String(preview.formula || "N/A")}</p>
        </div>
        <div>
          <p className="text-zinc-500">Atoms</p>
          <p className="font-medium">{String(preview.atom_count || "N/A")}</p>
        </div>
        <div>
          <p className="text-zinc-500">Cell Volume</p>
          <p className="font-medium">{preview.cell_volume ? `${preview.cell_volume} \u00C5\u00B3` : "N/A"}</p>
        </div>
        {symmetry && symmetry.number ? (
          <div>
            <p className="text-zinc-500">Space Group</p>
            <p className="font-medium">{String(symmetry.symbol)} ({String(symmetry.number)})</p>
          </div>
        ) : null}
      </div>

      {lattice ? (
        <div className="mt-2">
          <p className="mb-1 text-[10px] uppercase tracking-wider text-zinc-500">Cell Parameters</p>
          <div className="grid grid-cols-3 gap-2 rounded-lg border border-zinc-100 bg-white p-2 dark:border-zinc-800/50 dark:bg-zinc-950">
            {(["a", "b", "c", "alpha", "beta", "gamma"] as const).map((key) => (
              <div key={key} className="text-center">
                <span className="block text-[9px] uppercase text-zinc-400">{key}</span>
                <span className="text-xs font-mono">
                  {typeof lattice[key] === "number"
                    ? `${lattice[key].toFixed(key.length === 1 ? 3 : 1)}${key.length === 1 ? "" : "\u00B0"}`
                    : "N/A"}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {positions.length > 0 ? (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between gap-3">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Atomic Positions</p>
            <div className="flex items-center gap-1 rounded-lg border border-zinc-200/70 bg-white/85 p-0.5 dark:border-zinc-800 dark:bg-zinc-950/80">
              <button
                type="button"
                onClick={() => setPositionMode("cartesian")}
                className={cn(
                  "rounded-md px-2 py-1 text-[10px] font-medium transition-colors",
                  positionMode === "cartesian"
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
                )}
              >
                Absolute
              </button>
              <button
                type="button"
                onClick={() => {
                  if (canShowFractional) {
                    setPositionMode("fractional");
                  }
                }}
                disabled={!canShowFractional}
                className={cn(
                  "rounded-md px-2 py-1 text-[10px] font-medium transition-colors",
                  positionMode === "fractional"
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
                  !canShowFractional && "cursor-not-allowed opacity-40",
                )}
              >
                Fractional
              </button>
            </div>
          </div>
          <div className="max-h-32 overflow-auto rounded-lg border border-zinc-100 bg-white p-2.5 font-mono text-[10px] dark:border-zinc-800/50 dark:bg-zinc-950">
            {positions.slice(0, 10).map((rawPosition, i) => {
              const position = rawPosition as { kind?: string; position?: number[]; fractional_position?: number[] };
              const coords = positionMode === "fractional" && canShowFractional
                ? (Array.isArray(position.fractional_position) ? position.fractional_position : [])
                : (Array.isArray(position.position) ? position.position : []);
              return (
                <div key={i} className="flex gap-4 border-b border-zinc-50 py-0.5 last:border-0 dark:border-zinc-900">
                  <span className="w-6 font-bold text-blue-600 dark:text-blue-400">{position.kind || "?"}</span>
                  <span className="text-zinc-600 dark:text-zinc-400">
                    {coords.map((coord) => Number(coord).toFixed(4)).join(",  ")}
                  </span>
                </div>
              );
            })}
            {positions.length > 10 ? (
              <p className="mt-1 text-[9px] italic text-zinc-400">... and {positions.length - 10} more sites</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StructuredValueView({
  label,
  value,
  depth = 0,
}: {
  label?: string;
  value: unknown;
  depth?: number;
}) {
  const isObject = Boolean(value) && typeof value === "object" && !Array.isArray(value);
  const isArray = Array.isArray(value);

  if (isObject) {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <div
        className={cn(
          "space-y-2 rounded-xl border border-zinc-200/80 bg-white/90 p-3 dark:border-zinc-800 dark:bg-zinc-950/80",
          depth > 0 && "bg-zinc-50/70 dark:bg-zinc-900/55",
        )}
      >
        {label ? <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">{label}</p> : null}
        {entries.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Empty object</p>
        ) : (
          entries.map(([entryKey, entryValue]) => (
            <div key={`${label || "root"}-${entryKey}`} className="space-y-1.5">
              <p className="text-xs font-medium text-zinc-700 dark:text-zinc-300">{entryKey}</p>
              <StructuredValueView value={entryValue} depth={depth + 1} />
            </div>
          ))
        )}
      </div>
    );
  }

  if (isArray) {
    const items = value as unknown[];
    return (
      <div
        className={cn(
          "space-y-2 rounded-xl border border-zinc-200/80 bg-white/90 p-3 dark:border-zinc-800 dark:bg-zinc-950/80",
          depth > 0 && "bg-zinc-50/70 dark:bg-zinc-900/55",
        )}
      >
        {label ? <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">{label}</p> : null}
        {items.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Empty list</p>
        ) : items.every((item) => typeof item !== "object" || item === null) ? (
          <div className="flex flex-wrap gap-2">
            {items.map((item, index) => (
              <span
                key={`${label || "item"}-${index}`}
                className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
              >
                {formatPrimitivePreviewValue(item)}
              </span>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((item, index) => (
              <StructuredValueView key={`${label || "item"}-${index}`} label={`Item ${index}`} value={item} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-xl border border-zinc-200/80 bg-white/90 px-3 py-2.5 text-sm text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950/80 dark:text-zinc-300",
        depth > 0 && "bg-zinc-50/70 dark:bg-zinc-900/55",
      )}
    >
      {label ? <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">{label}</p> : null}
      <p className="break-words font-mono text-[12px]">{formatPrimitivePreviewValue(value)}</p>
    </div>
  );
}

function FileBrowserPreview({
  nodePk,
  source,
  title,
  subtitle,
  locationLabel,
  initialFiles,
}: {
  nodePk: number;
  source: "remote" | "folder";
  title: string;
  subtitle?: string | null;
  locationLabel?: string | null;
  initialFiles?: string[];
}) {
  const [selectedFile, setSelectedFile] = useState<string | null>(initialFiles?.[0] ?? null);

  const filesQuery = useQuery({
    queryKey: ["node-preview-files", source, nodePk],
    queryFn: async (): Promise<NodeFileListResponse> => {
      if (source === "remote") {
        return getRemoteFiles(nodePk);
      }
      return getRepositoryFiles(nodePk, "folder");
    },
    staleTime: 8_000,
  });

  const fetchedFiles = toStringList(filesQuery.data?.files);
  const fileList = Array.from(new Set([...(initialFiles ?? []), ...fetchedFiles]));

  useEffect(() => {
    if (fileList.length === 0) {
      setSelectedFile(null);
      return;
    }
    if (!selectedFile || !fileList.includes(selectedFile)) {
      setSelectedFile(fileList[0]);
    }
  }, [fileList, selectedFile]);

  const contentQuery = useQuery({
    queryKey: ["node-preview-file-content", source, nodePk, selectedFile],
    queryFn: async (): Promise<NodeFileContentResponse> => {
      if (!selectedFile) {
        return { pk: nodePk, filename: "", content: "" };
      }
      if (source === "remote") {
        return getRemoteFileContent(nodePk, selectedFile);
      }
      return getRepositoryFileContent(nodePk, selectedFile, "folder");
    },
    enabled: Boolean(selectedFile),
    staleTime: 8_000,
  });

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
        <Database className="h-4 w-4 text-amber-500" />
        <h4 className="text-sm font-semibold">{title}</h4>
      </div>
      <div className="flex flex-wrap gap-2">
        {subtitle ? (
          <span className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
            {subtitle}
          </span>
        ) : null}
        {locationLabel ? (
          <span className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
            {locationLabel}
          </span>
        ) : null}
        <span className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
          {fileList.length} file{fileList.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-[15rem_minmax(0,1fr)]">
        <div className="rounded-xl border border-zinc-200/80 bg-white/90 p-2 dark:border-zinc-800 dark:bg-zinc-950/80">
          <div className="mb-2 flex items-center justify-between px-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">Files</p>
            {filesQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400 dark:text-zinc-500" /> : null}
          </div>
          {filesQuery.isError ? (
            <p className="px-2 py-2 text-sm text-rose-500">Failed to list files.</p>
          ) : fileList.length === 0 ? (
            <p className="px-2 py-2 text-sm text-zinc-500 dark:text-zinc-400">No files available.</p>
          ) : (
            <div className="max-h-72 space-y-1 overflow-auto pr-1">
              {fileList.map((file) => (
                <button
                  key={file}
                  type="button"
                  onClick={() => setSelectedFile(file)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
                    selectedFile === file
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950"
                      : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-900",
                  )}
                >
                  <FileText className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{file}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-zinc-200/80 bg-white/90 p-3 dark:border-zinc-800 dark:bg-zinc-950/80">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">File Content</p>
              <p className="truncate text-sm text-zinc-700 dark:text-zinc-300">{selectedFile ?? "No file selected"}</p>
            </div>
            {contentQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400 dark:text-zinc-500" /> : null}
          </div>
          {contentQuery.isError ? (
            <p className="text-sm text-rose-500">Failed to read file content.</p>
          ) : !selectedFile ? (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">Select a file to inspect its content.</p>
          ) : contentQuery.isPending ? (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading file content...</p>
          ) : (
            <pre className="max-h-[26rem] overflow-auto rounded-lg border border-zinc-200/80 bg-zinc-50/80 p-3 text-xs leading-5 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/75 dark:text-zinc-200">
              {contentQuery.data?.content || ""}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

function formatBandTickLabel(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return "";
  }
  return raw.replace(/GAMMA/gi, "Γ").replace(/\bGamma\b/g, "Γ");
}

function buildBandPolyline(pointsX: number[], pointsY: number[], dimensions: {
  width: number;
  height: number;
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}): string {
  const { width, height, xMin, xMax, yMin, yMax } = dimensions;
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;
  return pointsX
    .map((xValue, index) => {
      const yValue = pointsY[index];
      const svgX = ((xValue - xMin) / xRange) * width;
      const svgY = height - ((yValue - yMin) / yRange) * height;
      return `${svgX.toFixed(2)},${svgY.toFixed(2)}`;
    })
    .join(" ");
}

function BandsPlotPreview({
  nodePk,
  preview,
}: {
  nodePk: number;
  preview: Record<string, unknown>;
}) {
  const query = useQuery({
    queryKey: ["bands-plot", nodePk],
    queryFn: (): Promise<BandsPlotResponse> => getBandsPlotData(nodePk),
    staleTime: 15_000,
  });

  const plot = (query.data?.data ?? {}) as BandsPlotData;
  const paths = Array.isArray(plot.paths) ? plot.paths : [];
  const tickPositions = Array.isArray(plot.tick_pos) ? plot.tick_pos.filter((value): value is number => typeof value === "number" && Number.isFinite(value)) : [];
  const tickLabels = Array.isArray(plot.tick_labels) ? plot.tick_labels.map(formatBandTickLabel) : [];
  const xMin = typeof plot.x_min_lim === "number" ? plot.x_min_lim : (tickPositions[0] ?? 0);
  const xMax = typeof plot.x_max_lim === "number" ? plot.x_max_lim : (tickPositions[tickPositions.length - 1] ?? 1);
  const rawYMin = typeof plot.y_min_lim === "number" ? plot.y_min_lim : -1;
  const rawYMax = typeof plot.y_max_lim === "number" ? plot.y_max_lim : 1;
  const [energyZeroInput, setEnergyZeroInput] = useState("0.00");
  const [yMinInput, setYMinInput] = useState(rawYMin.toFixed(2));
  const [yMaxInput, setYMaxInput] = useState(rawYMax.toFixed(2));
  const [hasCustomRange, setHasCustomRange] = useState(false);
  const [hoverPoint, setHoverPoint] = useState<{ x: number; y: number; plotX: number; plotY: number } | null>(null);
  const bandTypeIdx = Array.isArray(plot.band_type_idx) ? plot.band_type_idx : [];

  useEffect(() => {
    setEnergyZeroInput("0.00");
    setYMinInput(rawYMin.toFixed(2));
    setYMaxInput(rawYMax.toFixed(2));
    setHasCustomRange(false);
  }, [nodePk, rawYMin, rawYMax]);

  const parsedEnergyZero = Number.parseFloat(energyZeroInput);
  const energyZero = Number.isFinite(parsedEnergyZero) ? parsedEnergyZero : 0;
  const autoYMin = rawYMin - energyZero;
  const autoYMax = rawYMax - energyZero;

  useEffect(() => {
    if (hasCustomRange) {
      return;
    }
    setYMinInput(autoYMin.toFixed(2));
    setYMaxInput(autoYMax.toFixed(2));
  }, [autoYMin, autoYMax, hasCustomRange]);

  const parsedYMin = Number.parseFloat(yMinInput);
  const parsedYMax = Number.parseFloat(yMaxInput);
  const hasValidCustomRange = Number.isFinite(parsedYMin) && Number.isFinite(parsedYMax) && parsedYMax > parsedYMin;
  const displayYMin = hasValidCustomRange ? parsedYMin : autoYMin;
  const displayYMax = hasValidCustomRange ? parsedYMax : autoYMax;
  const dimensions = { width: 760, height: 320, xMin, xMax, yMin: displayYMin, yMax: displayYMax };
  const xRange = dimensions.xMax - dimensions.xMin || 1;
  const yRange = dimensions.yMax - dimensions.yMin || 1;

  const renderedLines = paths.flatMap((segment: BandsPlotPath, segmentIndex) => {
    const xValues = Array.isArray(segment.x) ? segment.x.filter((value): value is number => typeof value === "number" && Number.isFinite(value)) : [];
    const valueSets = Array.isArray(segment.values) ? segment.values : [];
    return valueSets.flatMap((bandValues, bandIndex) => {
      if (!Array.isArray(bandValues) || bandValues.length === 0 || xValues.length !== bandValues.length) {
        return [];
      }
      const spinType = typeof bandTypeIdx[bandIndex] === "number" ? bandTypeIdx[bandIndex] : 0;
      const stroke = spinType === 1 ? "#0f766e" : "#2563eb";
      const shiftedValues = bandValues.map((value) => Number(value) - energyZero);
      return [{
        key: `segment-${segmentIndex}-band-${bandIndex}`,
        points: buildBandPolyline(xValues, shiftedValues, dimensions),
        stroke,
      }];
    });
  });

  const zeroAxisVisible = displayYMin <= 0 && displayYMax >= 0;
  const zeroAxisY = zeroAxisVisible ? dimensions.height - ((0 - displayYMin) / ((displayYMax - displayYMin) || 1)) * dimensions.height : null;
  const hoverTooltipWidth = 112;
  const hoverTooltipHeight = 34;
  const hoverTooltipX = hoverPoint ? Math.min(Math.max(hoverPoint.x + 12, 8), dimensions.width - hoverTooltipWidth - 8) : 0;
  const hoverTooltipY = hoverPoint ? Math.min(Math.max(hoverPoint.y - hoverTooltipHeight - 10, 8), dimensions.height - hoverTooltipHeight - 8) : 0;

  const handlePlotPointerMove = (event: ReactMouseEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) {
      return;
    }
    const bounds = svg.getBoundingClientRect();
    if (!bounds.width || !bounds.height) {
      return;
    }
    const relativeX = ((event.clientX - bounds.left) / bounds.width) * dimensions.width;
    const relativeY = ((event.clientY - bounds.top) / bounds.height) * (dimensions.height + 42);
    const plotX = Math.min(Math.max(relativeX, 0), dimensions.width);
    const plotY = Math.min(Math.max(relativeY, 0), dimensions.height);
    const xValue = dimensions.xMin + (plotX / dimensions.width) * xRange;
    const yValue = dimensions.yMax - (plotY / dimensions.height) * yRange;
    setHoverPoint({
      x: plotX,
      y: plotY,
      plotX: xValue,
      plotY: yValue,
    });
  };

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
          <Waves className="h-4 w-4 text-cyan-500" />
          <h4 className="text-sm font-semibold">Electronic Band Structure</h4>
        </div>
        {query.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400 dark:text-zinc-500" /> : null}
      </div>
      <div className="grid grid-cols-2 gap-4 text-xs">
        <div className="bg-white dark:bg-zinc-950 p-3 rounded-lg border border-zinc-100 dark:border-zinc-800 shadow-sm">
          <p className="text-zinc-500 mb-1">K-Points</p>
          <p className="text-lg font-bold text-blue-600 dark:text-blue-400">{String(preview.num_kpoints || "N/A")}</p>
        </div>
        <div className="bg-white dark:bg-zinc-950 p-3 rounded-lg border border-zinc-100 dark:border-zinc-800 shadow-sm">
          <p className="text-zinc-500 mb-1">Bands</p>
          <p className="text-lg font-bold text-emerald-600 dark:text-emerald-400">{String(preview.num_bands || "N/A")}</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 rounded-xl border border-zinc-200/80 bg-white/90 p-3 text-xs dark:border-zinc-800 dark:bg-zinc-950/80">
        <label className="space-y-1">
          <span className="block text-zinc-500">Y Min</span>
          <input
            value={yMinInput}
            onChange={(event) => {
              setHasCustomRange(true);
              setYMinInput(event.target.value);
            }}
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-2 font-mono text-zinc-700 outline-none transition focus:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:focus:border-zinc-600"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-zinc-500">Y Max</span>
          <input
            value={yMaxInput}
            onChange={(event) => {
              setHasCustomRange(true);
              setYMaxInput(event.target.value);
            }}
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-2 font-mono text-zinc-700 outline-none transition focus:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:focus:border-zinc-600"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-zinc-500">Energy Zero</span>
          <input
            value={energyZeroInput}
            onChange={(event) => setEnergyZeroInput(event.target.value)}
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-2 font-mono text-zinc-700 outline-none transition focus:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:focus:border-zinc-600"
          />
        </label>
        <div className="col-span-3 flex items-center justify-between gap-3 text-[11px] text-zinc-500 dark:text-zinc-400">
          <span>{hasCustomRange && !hasValidCustomRange ? "Y range is invalid, using automatic range." : `Zero shifted by ${energyZero.toFixed(2)} eV`}</span>
          <button
            type="button"
            onClick={() => {
              setHasCustomRange(false);
              setEnergyZeroInput("0.00");
              setYMinInput(rawYMin.toFixed(2));
              setYMaxInput(rawYMax.toFixed(2));
            }}
            className="rounded-md px-2 py-1 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100"
          >
            Reset View
          </button>
        </div>
      </div>
      {query.isError ? (
        <p className="text-sm text-rose-500">Failed to load band structure plot.</p>
      ) : query.isPending ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading band structure...</p>
      ) : renderedLines.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No plot-ready band data available.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-zinc-200/80 bg-white/95 p-3 dark:border-zinc-800 dark:bg-zinc-950/80">
          <svg viewBox={`0 0 ${dimensions.width} ${dimensions.height + 42}`} className="h-auto w-full" role="img" aria-label="Band structure plot">
            <rect x="0" y="0" width={dimensions.width} height={dimensions.height} fill="transparent" />
            {tickPositions.map((tick, index) => {
              const x = ((tick - dimensions.xMin) / xRange) * dimensions.width;
              return (
                <g key={`tick-${index}`}>
                  <line x1={x} y1={0} x2={x} y2={dimensions.height} stroke="currentColor" strokeOpacity="0.12" />
                  <text
                    x={x}
                    y={dimensions.height + 18}
                    textAnchor="middle"
                    className="fill-zinc-500 text-[11px] dark:fill-zinc-400"
                  >
                    {tickLabels[index] ?? ""}
                  </text>
                </g>
              );
            })}
            {zeroAxisY !== null ? (
              <line x1={0} y1={zeroAxisY} x2={dimensions.width} y2={zeroAxisY} stroke="#ef4444" strokeDasharray="4 4" strokeOpacity="0.45" />
            ) : null}
            {hoverPoint ? (
              <g pointerEvents="none">
                <line x1={hoverPoint.x} y1={0} x2={hoverPoint.x} y2={dimensions.height} stroke="#f97316" strokeDasharray="3 4" strokeOpacity="0.65" />
                <line x1={0} y1={hoverPoint.y} x2={dimensions.width} y2={hoverPoint.y} stroke="#f97316" strokeDasharray="3 4" strokeOpacity="0.4" />
                <circle cx={hoverPoint.x} cy={hoverPoint.y} r="3.4" fill="#f97316" fillOpacity="0.9" />
                <rect
                  x={hoverTooltipX}
                  y={hoverTooltipY}
                  width={hoverTooltipWidth}
                  height={hoverTooltipHeight}
                  rx="8"
                  fill="rgba(24, 24, 27, 0.92)"
                />
                <text x={hoverTooltipX + 10} y={hoverTooltipY + 14} className="fill-white text-[10px]">
                  {`k ${hoverPoint.plotX.toFixed(3)}`}
                </text>
                <text x={hoverTooltipX + 10} y={hoverTooltipY + 26} className="fill-white text-[10px]">
                  {`E ${hoverPoint.plotY.toFixed(3)} eV`}
                </text>
              </g>
            ) : null}
            {renderedLines.map((line) => (
              <polyline
                key={line.key}
                points={line.points}
                fill="none"
                stroke={line.stroke}
                strokeWidth="1.3"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            <text x="8" y="14" className="fill-zinc-500 text-[10px] dark:fill-zinc-400">
              {typeof displayYMax === "number" ? displayYMax.toFixed(2) : ""}
            </text>
            <text x="8" y={dimensions.height - 6} className="fill-zinc-500 text-[10px] dark:fill-zinc-400">
              {typeof displayYMin === "number" ? displayYMin.toFixed(2) : ""}
            </text>
            <rect
              x="0"
              y="0"
              width={dimensions.width}
              height={dimensions.height}
              fill="transparent"
              className="cursor-crosshair"
              onMouseMove={handlePlotPointerMove}
              onMouseLeave={() => setHoverPoint(null)}
            />
          </svg>
          <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-zinc-500 dark:text-zinc-400">
            <span>{String(plot.yaxis_label || "Energy")} {energyZero !== 0 ? "(shifted)" : ""}</span>
            <span>{hoverPoint ? `k ${hoverPoint.plotX.toFixed(3)} · E ${hoverPoint.plotY.toFixed(3)} eV` : (zeroAxisVisible ? "0 eV axis shown" : "")}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function NodePreviewContent({ node }: { node: PreviewableNode }) {
  const preview = normalizePreview(node);
  if (!preview) return null;

  const nodeType = node.node_type;

  if (isProcessLikeNodeType(nodeType)) {
    return null;
  }

  if (nodeType === "StructureData") {
    return <StructurePreviewCard preview={preview} />;
  }

  if (nodeType === "Dict") {
    const data = preview.data && typeof preview.data === "object" && !Array.isArray(preview.data)
      ? (preview.data as Record<string, unknown>)
      : null;
    const keys = toStringList(preview.keys);
    const count = typeof preview.count === "number" ? preview.count : keys.length;
    const jsonTheme =
      typeof document !== "undefined" && document.documentElement.classList.contains("dark")
        ? nordTheme
        : vscodeTheme;
    return (
      <div className="space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
        <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
          <FileCode className="h-4 w-4 text-amber-500" />
          <h4 className="text-sm font-semibold">Dictionary Overview</h4>
        </div>
        <div className="flex items-center justify-between gap-3 text-[11px] text-zinc-500 dark:text-zinc-400">
          <span>{count} key{count === 1 ? "" : "s"}</span>
          {keys.length > 0 ? <span className="truncate">Top keys: {keys.slice(0, 4).join(", ")}</span> : null}
        </div>
        {data ? (
          <div className="max-h-[420px] overflow-auto rounded-xl border border-zinc-200/80 bg-white/85 p-2 dark:border-zinc-800 dark:bg-zinc-950/70">
            <JsonView
              value={data}
              style={{
                ...jsonTheme,
                fontSize: 12,
                fontFamily: '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, monospace',
              }}
              collapsed={1}
              displayDataTypes={false}
              enableClipboard
            />
          </div>
        ) : preview.summary ? (
          <div className="rounded-xl border border-zinc-200/80 bg-white/90 p-3 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950/80 dark:text-zinc-300">
            {String(preview.summary)}
          </div>
        ) : null}
      </div>
    );
  }

  if (nodeType === "RemoteData") {
    const remotePath = String(preview.remote_path || preview.path || "").trim() || null;
    const computerName = String(preview.computer_name || preview.computer || "").trim() || null;
    return (
      <FileBrowserPreview
        nodePk={Number((node as { pk?: number }).pk ?? 0)}
        source="remote"
        title="Remote Directory"
        subtitle={computerName ? `Computer: ${computerName}` : null}
        locationLabel={remotePath ? `Path: ${remotePath}` : null}
      />
    );
  }

  if (nodeType === "FolderData") {
    const files = toStringList(preview.filenames).length > 0 ? toStringList(preview.filenames) : toStringList(preview.files);
    return (
      <FileBrowserPreview
        nodePk={Number((node as { pk?: number }).pk ?? 0)}
        source="folder"
        title="Repository Folder"
        subtitle="Stored Files"
        initialFiles={files}
      />
    );
  }

  if (nodeType === "ArrayData") {
    return (
      <div className="space-y-4 rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
        <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
          <TableIcon className="h-4 w-4 text-emerald-500" />
          <h4 className="text-sm font-semibold">Arrays ({Array.isArray(preview.arrays) ? preview.arrays.length : 0})</h4>
        </div>
        <div className="grid gap-3">
          {Array.isArray(preview.arrays) && preview.arrays.map((arr: any, i: number) => (
            <div key={i} className="rounded-lg border border-zinc-100 bg-white p-3 shadow-sm dark:border-zinc-800/50 dark:bg-zinc-950">
              <div className="flex justify-between items-center mb-1.5">
                <span className="text-xs font-bold font-mono text-blue-600 dark:text-blue-400">{arr.name}</span>
                <span className="text-[10px] bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-500">Shape: [{arr.shape?.join(", ")}]</span>
              </div>
              <div className="font-mono text-[10px] text-zinc-600 dark:text-zinc-400 bg-zinc-50/50 dark:bg-zinc-900/40 p-1.5 rounded truncate">
                {Array.isArray(arr.data) ? `[${arr.data.join(", ")}${arr.data.length >= 5 ? "..." : ""}]` : "N/A"}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (nodeType === "XyData") {
    return (
      <div className="space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
        <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
          <BarChart3 className="h-4 w-4 text-indigo-500" />
          <h4 className="text-sm font-semibold">X-Y Data Preview</h4>
        </div>
        <div className="grid grid-cols-2 gap-4 text-xs mb-2">
          <div>
            <p className="text-zinc-500">X-Axis</p>
            <p className="font-medium font-mono text-blue-600 dark:text-blue-400">{String(preview.x_label || "N/A")}</p>
          </div>
          <div>
            <p className="text-zinc-500">Y-Axes</p>
            <p className="font-medium font-mono truncate">{Array.isArray(preview.y_labels) ? preview.y_labels.join(", ") : "N/A"}</p>
          </div>
        </div>
        <div className="space-y-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">X-Sample</p>
            <div className="bg-white dark:bg-zinc-950 p-2 rounded-lg border border-zinc-100 dark:border-zinc-800 font-mono text-[10px] text-zinc-600 dark:text-zinc-400 truncate shadow-sm">
              {Array.isArray(preview.x_sample) ? `[${preview.x_sample.join(", ")}...]` : "N/A"}
            </div>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">Y-Sample (first array)</p>
            <div className="bg-white dark:bg-zinc-950 p-2 rounded-lg border border-zinc-100 dark:border-zinc-800 font-mono text-[10px] text-zinc-600 dark:text-zinc-400 truncate shadow-sm">
              {Array.isArray(preview.y_sample) ? `[${preview.y_sample.join(", ")}...]` : "N/A"}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (nodeType === "BandsData") {
    return <BandsPlotPreview nodePk={Number((node as { pk?: number }).pk ?? 0)} preview={preview} />;
  }

  return (
    <div className="rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
      <StructuredValueView value={preview} />
    </div>
  );
}

function isWorkChainType(nodeType: string | null | undefined): boolean {
  const normalized = String(nodeType || "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return WORKCHAIN_NODE_HINTS.some((hint) => normalized.includes(hint));
}

function isWorkGraphType(nodeType: string | null | undefined): boolean {
  const normalized = String(nodeType || "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return normalized.includes("workgraph");
}

function isProcessLikeNodeType(nodeType: string | null | undefined): boolean {
  const normalized = String(nodeType || "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return normalized.includes("process") || normalized.includes("calc") || normalized.includes("workflow") || normalized.includes("workchain");
}

function isProcessLikeNode(node: ProcessItem): boolean {
  if (node.process_state !== null) return true;
  return isProcessLikeNodeType(node.node_type);
}

function buildRootTarget(process: ProcessItem): InspectorTarget {
  return {
    pk: process.pk,
    label: process.label || `Node #${process.pk}`,
    nodeType: process.node_type || "Node",
    breadcrumb: `${isProcessLikeNode(process) ? "Process" : "Node"} #${process.pk}`,
    relation: "root",
    previewInfo: process.preview_info ?? null,
  };
}

function buildLinkTarget(link: ProcessNodeLink, direction: InspectorLinkDirection): InspectorTarget {
  return {
    pk: link.pk,
    label: String(link.label || link.node_type || `Node #${link.pk}`),
    nodeType: String(link.node_type || "Node"),
    breadcrumb: `${direction === "input" ? "Input" : "Output"} #${link.pk}`,
    relation: direction,
    previewInfo: link.preview_info ?? null,
  };
}

function buildProcessItemFromInspector(
  target: InspectorTarget,
  detail: ProcessDetailResponse | undefined,
): ProcessItem {
  const summary = detail?.summary;
  const state = String(summary?.state || "failed");
  return {
    pk: target.pk,
    label: String(summary?.label || target.label || `Node #${target.pk}`),
    state,
    status_color: FAILED_STATES.has(normalizeState(state)) ? "error" : "idle",
    node_type: String(summary?.node_type || summary?.type || target.nodeType || "Node"),
    process_label: summary?.process_label ?? null,
    process_state: state,
    formula: null,
    preview_info: (summary?.preview_info as Record<string, unknown> | null | undefined) ?? target.previewInfo ?? null,
  };
}

function iconForNodeType(nodeType: string): { icon: string; ariaLabel: string } {
  const loType = nodeType.toLowerCase();
  if (loType.includes("structure")) {
    return { icon: "\uD83D\uDC8E", ariaLabel: "Crystal" };
  }
  if (loType.includes("base") || loType.includes("log") || loType.includes("report")) {
    return { icon: "\u26A1", ariaLabel: "Activity" };
  }
  if (loType.includes("bands") || loType.includes("xy") || loType.includes("trajectory")) {
    return { icon: "\uD83D\uDCC8", ariaLabel: "Chart" };
  }
  if (loType.includes("dict") || loType.includes("array") || loType.includes("parameter")) {
    return { icon: "\uD83D\uDCD1", ariaLabel: "Data" };
  }
  if (loType.includes("folder") || loType.includes("retrieved")) {
    return { icon: "\uD83D\uDCC1", ariaLabel: "Folder" };
  }
  return { icon: "\uD83D\uDCE6", ariaLabel: "Node" };
}

function formatLinkPreview(link: ProcessNodeLink): string | null {
  const preview = link.preview_info;
  if (!preview) {
    return null;
  }
  const nodeType = String(link.node_type || "Node");
  const normalizedType = nodeType.trim().toLowerCase();

  if (Array.isArray(preview.mesh) && preview.mesh.length > 0) {
    return preview.mesh.join("x");
  }
  if (preview.mode === "list" && typeof preview.num_points === "number") {
    return `${preview.num_points} k-points`;
  }
  if (preview.formula) {
    return String(preview.formula);
  }
  if (normalizedType.includes("bands") && (preview.num_kpoints !== undefined || preview.num_bands !== undefined)) {
    const parts = [
      typeof preview.num_kpoints === "number" ? `${preview.num_kpoints} k-points` : null,
      typeof preview.num_bands === "number" ? `${preview.num_bands} bands` : null,
    ].filter(Boolean);
    if (parts.length > 0) {
      return parts.join(" · ");
    }
  }
  if (Array.isArray(preview.arrays) && preview.arrays.length > 0) {
    const arrayText = preview.arrays
      .slice(0, 2)
      .map((entry: { name?: string; label?: string; shape?: number[] | null }) => {
        const label = entry.name || entry.label || "array";
        const shape = Array.isArray(entry.shape) && entry.shape.length > 0 ? `(${entry.shape.join("x")})` : "";
        return `${label}${shape}`;
      })
      .join(", ");
    return preview.arrays.length > 2 ? `${arrayText}, ...` : arrayText;
  }
  if (preview.value !== undefined) {
    return String(preview.value);
  }
  if (preview.remote_path || preview.computer_name || preview.computer || preview.path) {
    const pieces = [preview.path || preview.remote_path, preview.computer || preview.computer_name].filter(Boolean);
    const pathText = pieces.join(" \u00B7 ");
    return pathText ? `dir · ${pathText}` : "remote directory";
  }
  const files = Array.isArray(preview.filenames)
    ? preview.filenames
    : Array.isArray(preview.files)
      ? preview.files
      : [];
  if (files.length > 0) {
    const prefix = typeof preview.file_count === "number" ? `${preview.file_count} files` : "files";
    return `${prefix}: ${files.slice(0, 3).join(", ")}`;
  }
  if (preview.keys && preview.keys.length > 0) {
    const suffix = (preview.count ?? 0) > 3 ? ", ..." : "";
    return `${preview.count ?? preview.keys.length} keys: ${preview.keys.slice(0, 3).join(", ")}${suffix}`;
  }
  if (preview.count !== undefined && preview.count !== null) {
    return normalizedType === "list" ? `${preview.count} items` : `items: ${preview.count}`;
  }
  if (preview.x_label || (preview.y_arrays && preview.y_arrays.length > 0)) {
    const yText = (preview.y_arrays || [])
      .slice(0, 3)
      .map((entry: { label: string; length: number | null }) => `${entry.label}${entry.length !== null ? `(${entry.length})` : ""}`)
      .join(", ");
    const xText = preview.x_label ? `${preview.x_label}${preview.x_length !== null ? `(${preview.x_length})` : ""}` : null;
    return [xText ? `x:${xText}` : null, yText ? `y:${yText}` : null].filter(Boolean).join(" \u00B7 ") || null;
  }
  if (preview.x_label || (preview.y_labels && preview.y_labels.length > 0)) {
    const yLabels = (preview.y_labels || []).slice(0, 3).join(", ");
    return [preview.x_label ? `x:${preview.x_label}` : null, yLabels ? `y:${yLabels}` : null].filter(Boolean).join(" · ") || null;
  }
  if (preview.summary) {
    const summary = String(preview.summary).replace(/\s+/g, " ").trim();
    return summary.length > 80 ? `${summary.slice(0, 77)}...` : summary;
  }
  return null;
}

function formatInspectorNodeTitle(target: InspectorTarget | null | undefined): string {
  if (!target) {
    return "Node Inspector";
  }
  const nodeType = String(target.nodeType || "Node").trim() || "Node";
  return `${nodeType} #${target.pk}`;
}

function NodeLinkRow({
  portName,
  link,
  onOpenNodeDetail,
  onAddContextNode,
  direction,
  compact = false,
}: {
  portName: string;
  link: ProcessNodeLink;
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void;
  onAddContextNode: (node: FocusNode) => void;
  direction: InspectorLinkDirection;
  compact?: boolean;
}) {
  const previewText = formatLinkPreview(link);
  const nodeType = String(link.node_type || "Node");
  const typeIndicator = iconForNodeType(nodeType);
  const linkLabel = portName || String(link.link_label || "").trim() || `link_${link.pk}`;
  return (
    <button
      type="button"
      onClick={() => onOpenNodeDetail(link, direction)}
      className={cn(
        "group flex w-full items-start justify-between gap-3 rounded-md px-2 py-1.5 text-left font-sans tracking-tight transition-colors duration-150 hover:bg-zinc-100/85 dark:hover:bg-zinc-900/70",
        compact && "py-1",
      )}
    >
      <div className="min-w-0 flex items-start gap-1.5">
        <span role="img" aria-label={typeIndicator.ariaLabel} className="mt-[1px] shrink-0">
          {typeIndicator.icon}
        </span>
        <p className={cn("min-w-0 truncate text-xs text-zinc-700 dark:text-zinc-300", compact && "text-[11px]")}>
          <span className="font-medium text-blue-600 dark:text-blue-400 font-mono">{linkLabel}</span>
          <span className="text-zinc-500 dark:text-zinc-400 mx-1">:</span>
          <span>{link.label || nodeType}</span>
          <span className="text-zinc-500 dark:text-zinc-400"> (</span>
          <span className="font-mono text-zinc-500 dark:text-zinc-400">
            #{link.pk}
          </span>
          <span className="text-zinc-500 dark:text-zinc-400">)</span>
          {previewText ? (
            <span className={cn("ml-1 text-zinc-500 dark:text-zinc-400", compact ? "text-[10px]" : "text-[11px]")}>
              [{previewText}]
            </span>
          ) : null}
        </p>
      </div>
    </button>
  );
}

function NodeLinksBlock({
  title,
  links,
  onOpenNodeDetail,
  onAddContextNode,
  emptyText,
  compact = false,
  showTitle = true,
}: NodeLinksBlockProps) {
  const direction: InspectorLinkDirection = title.toLowerCase().startsWith("input") ? "input" : "output";
  return (
    <section className="font-sans tracking-tight">
      {showTitle ? (
        <h4 className={cn("mb-1 text-xs font-semibold tracking-tight text-zinc-700 dark:text-zinc-300", compact && "text-[10px] uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400")}>
          {title}
        </h4>
      ) : null}
      {Object.keys(links).length === 0 ? (
        <p className={cn("px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400", compact && "text-[11px]")}>{emptyText}</p>
      ) : (
        <div className="space-y-0.5">
          {Object.entries(links).map(([portName, link]) => (
            <NodeLinkRow
              key={`${title}-${link.pk}-${portName}`}
              portName={portName}
              link={link}
              direction={direction}
              onOpenNodeDetail={onOpenNodeDetail}
              onAddContextNode={onAddContextNode}
              compact={compact}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ProcessTreeNodeView({ label, node, depth = 0, onOpenNodeDetail, onAddContextNode }: ProcessTreeNodeViewProps) {
  const children = Object.entries(node.children || {});
  const status = toDisplayStatus(node.state);
  const statusTone = getStatusTone(node.state);
  const durationLabel = getDurationLabel(node);
  const nodeLabel = node.process_label || label || "Process";
  const RowIcon = children.length > 0 ? GitBranch : CircleDot;
  const [isLinksOpen, setIsLinksOpen] = useState(false);
  const inputLinks = node.direct_inputs ?? node.inputs ?? {};
  const outputLinks = node.direct_outputs ?? node.outputs ?? {};
  const hasLinks = Object.keys(inputLinks).length > 0 || Object.keys(outputLinks).length > 0;

  return (
    <div className={cn("space-y-1", depth > 0 && "ml-3 border-l border-zinc-200/80 pl-4 dark:border-zinc-800/80")}>
      <div className="group flex items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors duration-200 hover:bg-zinc-100/80 dark:hover:bg-zinc-900/65">
        <div className="min-w-0 flex items-center gap-2">
          <RowIcon className="h-3.5 w-3.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
          <p className="truncate text-sm text-zinc-900 dark:text-zinc-100">
            <span className="font-medium">{nodeLabel}</span>{" "}
            <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">({node.pk})</span>
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-3">
          {hasLinks ? (
            <button
              type="button"
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[10px] uppercase tracking-[0.08em] text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-200"
              onClick={() => setIsLinksOpen((open) => !open)}
              aria-label={isLinksOpen ? "Hide node links" : "Show node links"}
            >
              <ChevronDown className={cn("h-3 w-3 transition-transform duration-200", isLinksOpen && "rotate-180")} />
              LINKS
            </button>
          ) : null}
          <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", statusTone.textClassName)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", statusTone.dotClassName)} />
            {status}
          </span>
          <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">{durationLabel}</span>
        </div>
      </div>

      {hasLinks && isLinksOpen ? (
        <div className="ml-5 space-y-2">
          <NodeLinksBlock
            title="Inputs"
            links={inputLinks}
            onOpenNodeDetail={onOpenNodeDetail}
            onAddContextNode={onAddContextNode}
            emptyText="No direct inputs."
            compact
          />
          <NodeLinksBlock
            title="Outputs"
            links={outputLinks}
            onOpenNodeDetail={onOpenNodeDetail}
            onAddContextNode={onAddContextNode}
            emptyText="No direct outputs."
            compact
          />
        </div>
      ) : null}

      {children.length > 0 ? (
        <div className="space-y-1">
          {children.map(([childLabel, child]) => (
            <ProcessTreeNodeView
              key={`${childLabel}-${child.pk}`}
              label={childLabel}
              node={child}
              depth={depth + 1}
              onOpenNodeDetail={onOpenNodeDetail}
              onAddContextNode={onAddContextNode}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function buildWorkgraphGraphLayout(workgraph: ProcessWorkgraphResponse): {
  width: number;
  height: number;
  layoutNodes: WorkgraphGraphLayoutNode[];
  layoutById: Map<string, WorkgraphGraphLayoutNode>;
} {
  const nodeMap = new Map(workgraph.nodes.map((node) => [node.id, node]));
  const columns = workgraph.levels.length > 0 ? workgraph.levels : [workgraph.nodes.map((node) => node.id)];
  const width =
    WORKGRAPH_GRAPH_PADDING * 2 +
    columns.length * WORKGRAPH_GRAPH_NODE_WIDTH +
    Math.max(0, columns.length - 1) * WORKGRAPH_GRAPH_COLUMN_GAP;
  const layoutNodes: WorkgraphGraphLayoutNode[] = [];
  const layoutById = new Map<string, WorkgraphGraphLayoutNode>();
  const estimatedHeights = new Map<string, number>();

  const estimateNodeHeight = (node: ProcessWorkgraphNode): number => {
    const identifierLineCount = Math.max(1, Math.min(3, Math.ceil((node.identifier || node.id).length / 36)));
    const visibleChipCount = Math.min(2, node.inputs.length) + Math.min(2, node.outputs.length);
    const chipRowCount = visibleChipCount > 0 ? Math.ceil(visibleChipCount / 2) : 0;
    const hasProcessControls = typeof node.process_pk === "number" && node.process_pk > 0;
    return (
      WORKGRAPH_GRAPH_NODE_MIN_HEIGHT +
      (identifierLineCount - 1) * 18 +
      chipRowCount * 20 +
      (hasProcessControls ? 0 : 6)
    );
  };

  columns.forEach((level) => {
    level.forEach((nodeId) => {
      const node = nodeMap.get(nodeId);
      if (!node) {
        return;
      }
      estimatedHeights.set(nodeId, estimateNodeHeight(node));
    });
  });

  const columnHeights = columns.map((level) =>
    level.reduce((total, nodeId, index) => {
      const nodeHeight = estimatedHeights.get(nodeId) ?? WORKGRAPH_GRAPH_NODE_MIN_HEIGHT;
      return total + nodeHeight + (index > 0 ? WORKGRAPH_GRAPH_ROW_GAP : 0);
    }, 0),
  );
  const innerHeight = Math.max(...columnHeights, WORKGRAPH_GRAPH_NODE_MIN_HEIGHT);
  const height = WORKGRAPH_GRAPH_PADDING * 2 + innerHeight;

  columns.forEach((level, levelIndex) => {
    const columnHeight = columnHeights[levelIndex] ?? 0;
    const startY = WORKGRAPH_GRAPH_PADDING + Math.max(0, (innerHeight - columnHeight) / 2);
    const x = WORKGRAPH_GRAPH_PADDING + levelIndex * (WORKGRAPH_GRAPH_NODE_WIDTH + WORKGRAPH_GRAPH_COLUMN_GAP);
    let currentY = startY;

    level.forEach((nodeId, rowIndex) => {
      const node = nodeMap.get(nodeId);
      if (!node) {
        return;
      }
      const nodeHeight = estimatedHeights.get(nodeId) ?? WORKGRAPH_GRAPH_NODE_MIN_HEIGHT;
      const layoutNode: WorkgraphGraphLayoutNode = {
        node,
        levelIndex,
        rowIndex,
        x,
        y: currentY,
        width: WORKGRAPH_GRAPH_NODE_WIDTH,
        height: nodeHeight,
      };
      layoutNodes.push(layoutNode);
      layoutById.set(nodeId, layoutNode);
      currentY += nodeHeight + WORKGRAPH_GRAPH_ROW_GAP;
    });
  });

  return { width, height, layoutNodes, layoutById };
}

function buildWorkgraphEdgePath(
  source: WorkgraphGraphLayoutNode,
  target: WorkgraphGraphLayoutNode,
): string {
  const startX = source.x + source.width;
  const startY = source.y + source.height / 2;
  const endX = target.x;
  const endY = target.y + target.height / 2;
  const controlOffset = Math.max(48, (endX - startX) * 0.45);
  return `M ${startX} ${startY} C ${startX + controlOffset} ${startY}, ${endX - controlOffset} ${endY}, ${endX} ${endY}`;
}

function WorkgraphNodeCard({ node, outgoingLabels, onOpenNodeDetail, onAddContextNode }: WorkgraphNodeCardProps) {
  const taskTone = getStatusTone(node.process_state ?? node.state);
  const canOpenProcess = typeof node.process_pk === "number" && node.process_pk > 0;
  const cardLabel = node.process_label || node.label || node.identifier || node.id;

  const handleOpen = () => {
    if (!canOpenProcess) {
      return;
    }
    onOpenNodeDetail(
      {
        link_label: node.label,
        node_type: node.process_node_type || node.task_type,
        pk: node.process_pk ?? 0,
        label: cardLabel,
      },
      "output",
    );
  };

  return (
    <div className="rounded-xl border border-zinc-200/80 bg-white/90 p-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{node.label}</p>
          <p className="mt-1 text-[11px] uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">{node.task_type}</p>
        </div>
        <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", taskTone.textClassName)}>
          <span className={cn("h-1.5 w-1.5 rounded-full", taskTone.dotClassName)} />
          {toDisplayStatus(node.process_state ?? node.state)}
        </span>
      </div>

      <div className="mt-3 space-y-2 text-xs text-zinc-600 dark:text-zinc-300">
        <p className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">{node.identifier}</p>
        {canOpenProcess ? (
          <button
            type="button"
            className="inline-flex items-center rounded-md border border-zinc-200/80 px-2.5 py-1 text-[11px] font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-900"
            onClick={handleOpen}
          >
            Open Process #{node.process_pk}
          </button>
        ) : (
          <p className="text-[11px] text-zinc-500 dark:text-zinc-400">Task process has not materialized into an AiiDA node yet.</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {node.inputs.slice(0, 4).map((inputName) => (
            <span key={`${node.id}-input-${inputName}`} className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-200">
              in: {inputName}
            </span>
          ))}
          {node.outputs.slice(0, 4).map((outputName) => (
            <span key={`${node.id}-output-${outputName}`} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200">
              out: {outputName}
            </span>
          ))}
        </div>
        {outgoingLabels.length > 0 ? (
          <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
            Next: {outgoingLabels.join(", ")}
          </p>
        ) : null}
      </div>

      {canOpenProcess ? (
        <div className="mt-3 flex items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
            PK {node.process_pk}
          </span>
          <button
            type="button"
            className="text-[11px] font-medium text-zinc-600 transition-colors hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100"
            onClick={() =>
              onAddContextNode({
                pk: node.process_pk ?? 0,
                label: cardLabel,
                formula: null,
                node_type: node.process_node_type || node.task_type,
              })
            }
          >
            Add Context
          </button>
        </div>
      ) : null}
    </div>
  );
}

function renderWorkgraphConnections(workgraph: ProcessWorkgraphResponse) {
  const nodeMap = new Map(workgraph.nodes.map((node) => [node.id, node]));

  return (
    <div className="rounded-xl border border-zinc-200/80 bg-zinc-50/70 p-4 dark:border-zinc-800 dark:bg-zinc-900/50">
      <div className="mb-3 flex items-center gap-2">
        <Activity className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
        <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Connections</h4>
      </div>
      {workgraph.edges.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No task-to-task links were reported for this workgraph.</p>
      ) : (
        <div className="space-y-2">
          {workgraph.edges.map((edge) => (
            <div
              key={edge.id}
              className="flex flex-wrap items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300"
            >
              <span className="rounded-full bg-white px-2 py-0.5 font-medium dark:bg-zinc-950">{nodeMap.get(edge.source)?.label || edge.source}</span>
              <ChevronRight className="h-3.5 w-3.5 text-zinc-400 dark:text-zinc-500" />
              <span className="rounded-full bg-white px-2 py-0.5 font-medium dark:bg-zinc-950">{nodeMap.get(edge.target)?.label || edge.target}</span>
              {edge.label ? (
                <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">{edge.label}</span>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function renderWorkgraphStage(
  workgraph: ProcessWorkgraphResponse,
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void,
  onAddContextNode: (node: FocusNode) => void,
) {
  const nodeMap = new Map(workgraph.nodes.map((node) => [node.id, node]));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
          {workgraph.nodes.length} tasks
        </span>
        <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
          {workgraph.edges.length} links
        </span>
        {workgraph.roots.length > 0 ? (
          <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
            Roots: {workgraph.roots.join(", ")}
          </span>
        ) : null}
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="grid auto-cols-[minmax(16rem,18rem)] grid-flow-col gap-4">
          {workgraph.levels.map((level, levelIndex) => (
            <div key={`workgraph-level-${levelIndex}`} className="space-y-3">
              <div className="flex items-center gap-2 px-1">
                <GitBranch className="h-3.5 w-3.5 text-zinc-400 dark:text-zinc-500" />
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                  Stage {levelIndex + 1}
                </p>
              </div>
              {level.map((nodeId) => {
                const node = nodeMap.get(nodeId);
                if (!node) {
                  return null;
                }
                const outgoingLabels = node.outgoing
                  .map((targetId) => nodeMap.get(targetId)?.label || targetId)
                  .filter(Boolean);
                return (
                  <WorkgraphNodeCard
                    key={node.id}
                    node={node}
                    outgoingLabels={outgoingLabels}
                    onOpenNodeDetail={onOpenNodeDetail}
                    onAddContextNode={onAddContextNode}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {renderWorkgraphConnections(workgraph)}
    </div>
  );
}

function renderWorkgraphGraph(
  workgraph: ProcessWorkgraphResponse,
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void,
  onAddContextNode: (node: FocusNode) => void,
) {
  const { width, height, layoutNodes, layoutById } = buildWorkgraphGraphLayout(workgraph);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
          {workgraph.nodes.length} tasks
        </span>
        <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
          {workgraph.edges.length} links
        </span>
        {workgraph.roots.length > 0 ? (
          <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
            Roots: {workgraph.roots.join(", ")}
          </span>
        ) : null}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-zinc-200/80 bg-[radial-gradient(circle_at_top_left,_rgba(148,163,184,0.08),_transparent_40%),linear-gradient(to_bottom_right,_rgba(255,255,255,0.98),_rgba(248,250,252,0.9))] p-3 dark:border-zinc-800 dark:bg-[radial-gradient(circle_at_top_left,_rgba(100,116,139,0.14),_transparent_35%),linear-gradient(to_bottom_right,_rgba(9,9,11,0.98),_rgba(24,24,27,0.92))]">
        <div className="relative" style={{ width, height }}>
          <svg
            className="absolute inset-0 h-full w-full"
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            fill="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="workgraph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" className="fill-zinc-400 dark:fill-zinc-500" />
              </marker>
            </defs>
            {workgraph.edges.map((edge) => {
              const source = layoutById.get(edge.source);
              const target = layoutById.get(edge.target);
              if (!source || !target) {
                return null;
              }
              return (
                <g key={edge.id}>
                  <path
                    d={buildWorkgraphEdgePath(source, target)}
                    className="stroke-zinc-300 dark:stroke-zinc-700"
                    strokeWidth="2"
                    markerEnd="url(#workgraph-arrow)"
                  />
                </g>
              );
            })}
          </svg>

          {layoutNodes.map(({ node, x, y, width: nodeWidth, height: nodeHeight, levelIndex }) => {
            const tone = getStatusTone(node.process_state ?? node.state);
            const canOpenProcess = typeof node.process_pk === "number" && node.process_pk > 0;
            const cardLabel = node.process_label || node.label || node.identifier || node.id;

            return (
              <div
                key={node.id}
                className="absolute flex flex-col rounded-2xl border border-zinc-200/90 bg-white/95 p-4 shadow-[0_14px_30px_-18px_rgba(15,23,42,0.35)] backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-950/92"
                style={{ left: x, top: y, width: nodeWidth, height: nodeHeight }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{node.label}</p>
                    <p className="mt-1 text-[10px] uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                      Stage {levelIndex + 1} · {node.task_type}
                    </p>
                  </div>
                  <span className={cn("inline-flex items-center gap-1 text-[10px] font-medium", tone.textClassName)}>
                    <span className={cn("h-1.5 w-1.5 rounded-full", tone.dotClassName)} />
                    {toDisplayStatus(node.process_state ?? node.state)}
                  </span>
                </div>

                <div className="mt-3 flex min-h-0 flex-1 flex-col justify-between">
                  <div className="space-y-2.5">
                    <p className="break-all font-mono text-[10px] leading-4 text-zinc-500 dark:text-zinc-400">{node.identifier}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {node.inputs.slice(0, 2).map((inputName) => (
                        <span key={`${node.id}-graph-input-${inputName}`} className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-200">
                          {inputName}
                        </span>
                      ))}
                      {node.outputs.slice(0, 2).map((outputName) => (
                        <span key={`${node.id}-graph-output-${outputName}`} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200">
                          {outputName}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center justify-between gap-2">
                    {canOpenProcess ? (
                      <button
                        type="button"
                        className="inline-flex items-center rounded-md border border-zinc-200/80 px-2.5 py-1 text-[11px] font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-900"
                        onClick={() =>
                          onOpenNodeDetail(
                            {
                              link_label: node.label,
                              node_type: node.process_node_type || node.task_type,
                              pk: node.process_pk ?? 0,
                              label: cardLabel,
                            },
                            "output",
                          )
                        }
                      >
                        Open #{node.process_pk}
                      </button>
                    ) : (
                      <span className="text-[10px] text-zinc-500 dark:text-zinc-400">Planned task</span>
                    )}
                    {canOpenProcess ? (
                      <button
                        type="button"
                        className="text-[11px] font-medium text-zinc-600 transition-colors hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100"
                        onClick={() =>
                          onAddContextNode({
                            pk: node.process_pk ?? 0,
                            label: cardLabel,
                            formula: null,
                            node_type: node.process_node_type || node.task_type,
                          })
                        }
                      >
                        Add
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {renderWorkgraphConnections(workgraph)}
    </div>
  );
}

function renderLogs(logs: ProcessLogsResponse | undefined) {
  const lines = logs?.lines ?? [];
  if (!logs) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">No execution logs are available for this process yet.</p>
    );
  }
  if (lines.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">{logs.text || "No logs found."}</p>;
  }
  const snippet = lines.slice(-LOG_SNIPPET_LINE_LIMIT);
  const hasMore = lines.length > snippet.length;
  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Latest {snippet.length} line{snippet.length === 1 ? "" : "s"}
        {hasMore ? ` of ${lines.length}` : ""}.
      </p>
      <pre className="max-h-[18rem] overflow-auto rounded-lg border border-zinc-200/80 bg-zinc-50/70 p-3 text-xs leading-5 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/65 dark:text-zinc-200">
        {snippet.join("\n")}
      </pre>
    </div>
  );
}

function renderProcessTree(
  detail: ProcessDetailResponse | undefined,
  onOpenNodeDetail: (link: ProcessNodeLink, direction: InspectorLinkDirection) => void,
  onAddContextNode: (node: FocusNode) => void,
) {
  const treeRoot = detail?.workchain?.provenance_tree;
  if (treeRoot) {
    return <ProcessTreeNodeView label="root" node={treeRoot} onOpenNodeDetail={onOpenNodeDetail} onAddContextNode={onAddContextNode} />;
  }

  const summary = detail?.summary;
  if (!summary?.pk) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">Process tree is not available for this node type.</p>
    );
  }

  const summaryNode: ProcessTreeNode = {
    pk: summary.pk,
    process_label: summary.type || "ProcessNode",
    state: summary.state || "unknown",
    exit_status: summary.exit_status ?? null,
    inputs: detail?.direct_inputs ?? detail?.inputs ?? {},
    outputs: detail?.direct_outputs ?? detail?.outputs ?? {},
    direct_inputs: detail?.direct_inputs ?? detail?.inputs ?? {},
    direct_outputs: detail?.direct_outputs ?? detail?.outputs ?? {},
    children: {},
  };

  return (
    <div className="space-y-1">
      <ProcessTreeNodeView label="root" node={summaryNode} onOpenNodeDetail={onOpenNodeDetail} onAddContextNode={onAddContextNode} />
      <p className="pl-2 text-xs text-zinc-500 dark:text-zinc-400">
        No nested provenance tree returned by worker.
      </p>
    </div>
  );
}

function InspectorPanel({
  target,
  fallbackPreviewNode,
  onOpenNodeDetail,
  onAddContextNode,
  onExplainFailure,
  preferredMode = "overview",
}: InspectorPanelProps) {
  const [panelMode, setPanelMode] = useState<InspectorMode>(preferredMode);
  const [workgraphViewMode, setWorkgraphViewMode] = useState<WorkgraphViewMode>("graph");

  useEffect(() => {
    setPanelMode(preferredMode);
  }, [preferredMode, target.pk]);

  useEffect(() => {
    setWorkgraphViewMode("graph");
  }, [target.pk]);

  const detailQuery = useQuery({
    queryKey: ["process-detail", target.pk],
    queryFn: () => aiidaClient.getProcessDetail(target.pk),
    enabled: Boolean(target.pk),
    staleTime: 4_000,
  });

  const summary = detailQuery.data?.summary;
  const nodeType = summary?.node_type ?? summary?.type ?? target.nodeType ?? "Node";
  const isProcessTarget = isProcessLikeNodeType(nodeType);
  const isWorkgraphTarget = isWorkGraphType(nodeType);

  const logsQuery = useQuery({
    queryKey: ["process-logs", target.pk],
    queryFn: () => aiidaClient.getProcessLogs(target.pk),
    enabled: Boolean(target.pk) && isProcessTarget,
    staleTime: 4_000,
  });

  const summaryState = summary?.state ?? "unknown";
  const isFailedTarget = isProcessTarget && FAILED_STATES.has(normalizeState(summaryState));
  const panelLabel = summary?.label || target.label || `Node #${target.pk}`;
  const previewNode: PreviewableNode = {
    pk: target.pk,
    label: panelLabel,
    node_type: nodeType,
    preview_info: (summary?.preview_info as Record<string, unknown> | null | undefined) ?? fallbackPreviewNode?.preview_info ?? target.previewInfo ?? null,
  };
  const normalizedPreview = normalizePreview(previewNode);
  const processMeta = isProcessTarget ? extractProcessMeta(normalizedPreview, summaryState) : null;
  const processMetaTone = getStatusTone(processMeta?.state ?? summaryState);
  const directInputs = detailQuery.data?.direct_inputs ?? detailQuery.data?.inputs ?? {};
  const directOutputs = detailQuery.data?.direct_outputs ?? detailQuery.data?.outputs ?? {};
  const hasStandaloneLinks = Object.keys(directInputs).length > 0 || Object.keys(directOutputs).length > 0;
  const workgraphQuery = useQuery({
    queryKey: ["process-workgraph", target.pk],
    queryFn: () => aiidaClient.getProcessWorkgraph(target.pk),
    enabled: Boolean(target.pk) && isWorkgraphTarget,
    staleTime: 4_000,
  });
  const showProcessTree =
    (isProcessTarget && !isWorkgraphTarget) ||
    (!isWorkgraphTarget && isWorkChainType(nodeType)) ||
    Boolean(detailQuery.data?.workchain?.provenance_tree);
  const diagnosticsQuery = useQuery({
    queryKey: ["process-diagnostics", target.pk],
    queryFn: () => aiidaClient.getProcessDiagnostics(target.pk),
    enabled: Boolean(target.pk) && isProcessTarget && (panelMode === "diagnostics" || isFailedTarget),
    staleTime: 4_000,
  });
  const processItemForFailure = buildProcessItemFromInspector(target, detailQuery.data);

  useEffect(() => {
    if (isFailedTarget) {
      setPanelMode("diagnostics");
    } else if (preferredMode === "overview") {
      setPanelMode("overview");
    }
  }, [isFailedTarget, preferredMode, target.pk]);

  const overviewContent = (
    <>
      {previewNode.preview_info && (
        <section className="space-y-3">
          {processMeta && (processMeta.state || processMeta.duration) ? (
            <div className="flex flex-wrap items-center gap-2">
              {processMeta.state ? (
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium dark:border-zinc-800 dark:bg-zinc-900/60",
                    processMetaTone.textClassName,
                  )}
                >
                  <span className={cn("h-1.5 w-1.5 rounded-full", processMetaTone.dotClassName)} />
                  {processMeta.state}
                </span>
              ) : null}
              {processMeta.duration ? (
                <span className="inline-flex items-center rounded-full border border-zinc-200/80 bg-zinc-50 px-2.5 py-1 text-[11px] font-mono text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
                  {processMeta.duration}
                </span>
              ) : null}
            </div>
          ) : null}
          <NodePreviewContent node={previewNode} />
        </section>
      )}

      {isWorkgraphTarget && (
        <section className="space-y-3">
          <div className="mb-1 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Workgraph</h3>
              <div className="inline-flex items-center rounded-full border border-zinc-200/80 bg-white/90 p-1 dark:border-zinc-800 dark:bg-zinc-950/80">
                <button
                  type="button"
                  className={cn(
                    "rounded-full px-3 py-1 text-[11px] font-medium transition-colors",
                    workgraphViewMode === "graph"
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
                  )}
                  onClick={() => setWorkgraphViewMode("graph")}
                >
                  Graph
                </button>
                <button
                  type="button"
                  className={cn(
                    "rounded-full px-3 py-1 text-[11px] font-medium transition-colors",
                    workgraphViewMode === "stage"
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
                  )}
                  onClick={() => setWorkgraphViewMode("stage")}
                >
                  Stages
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-[0.08em] text-zinc-400 dark:text-zinc-500">
                {workgraphViewMode === "graph" ? "Arrow Layout" : "Stage Layout"}
              </span>
              {workgraphQuery.isFetching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400 dark:text-zinc-500" />
              ) : null}
            </div>
          </div>
          {workgraphQuery.isError ? (
            <p className="text-sm font-sans tracking-tight text-rose-500">Failed to load workgraph structure.</p>
          ) : workgraphQuery.isPending ? (
            <p className="animate-pulse text-sm font-sans text-zinc-500 dark:text-zinc-400">Loading workgraph structure...</p>
          ) : workgraphQuery.data ? (
            workgraphViewMode === "graph"
              ? renderWorkgraphGraph(workgraphQuery.data, onOpenNodeDetail, onAddContextNode)
              : renderWorkgraphStage(workgraphQuery.data, onOpenNodeDetail, onAddContextNode)
          ) : (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">No workgraph structure is available for this node.</p>
          )}
        </section>
      )}

      {showProcessTree && (
        <section>
          {detailQuery.isError ? (
            <p className="text-sm font-sans tracking-tight text-rose-500">Failed to load process tree.</p>
          ) : detailQuery.isPending ? (
            <p className="animate-pulse text-sm font-sans text-zinc-500 dark:text-zinc-400">Loading process tree...</p>
          ) : (
            renderProcessTree(detailQuery.data, onOpenNodeDetail, onAddContextNode)
          )}
        </section>
      )}

      {!showProcessTree && (
        <section className="space-y-3">
          <div className="mb-1 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Connections</h3>
            {detailQuery.isFetching ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400 dark:text-zinc-500" />
            ) : null}
          </div>
          {detailQuery.isError ? (
            <p className="text-sm font-sans tracking-tight text-rose-500">Failed to load node links.</p>
          ) : detailQuery.isPending ? (
            <p className="animate-pulse text-sm font-sans text-zinc-500 dark:text-zinc-400">Loading inputs and outputs...</p>
          ) : hasStandaloneLinks ? (
            <div className="space-y-2">
              <NodeLinksBlock
                title="Inputs"
                links={directInputs}
                onOpenNodeDetail={onOpenNodeDetail}
                onAddContextNode={onAddContextNode}
                emptyText="No incoming links reported."
              />
              <NodeLinksBlock
                title="Outputs"
                links={directOutputs}
                onOpenNodeDetail={onOpenNodeDetail}
                onAddContextNode={onAddContextNode}
                emptyText="No outgoing links reported."
              />
            </div>
          ) : (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">No inputs or outputs are available for this node.</p>
          )}
        </section>
      )}

      {isProcessTarget && (
        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Execution Logs</h3>
            {logsQuery.isFetching ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400 dark:text-zinc-500" />
            ) : null}
          </div>
          {logsQuery.isError ? (
            <p className="text-sm font-sans tracking-tight text-rose-500">Failed to load execution logs.</p>
          ) : logsQuery.isPending ? (
            <p className="animate-pulse text-sm font-sans text-zinc-500 dark:text-zinc-400">Loading execution logs...</p>
          ) : (
            renderLogs(logsQuery.data ?? detailQuery.data?.logs)
          )}
        </section>
      )}
    </>
  );

  return (
    <div className="minimal-scrollbar h-full overflow-y-auto px-6 py-6">
      <div className="space-y-5">
        {isProcessTarget ? (
          <section className="rounded-xl border border-zinc-200/80 bg-zinc-50/70 p-1 dark:border-zinc-800 dark:bg-zinc-900/50">
            <div className="grid grid-cols-2 gap-1">
              <button
                type="button"
                onClick={() => setPanelMode("overview")}
                className={cn(
                  "rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                  panelMode === "overview"
                    ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200",
                )}
              >
                Overview
              </button>
              <button
                type="button"
                onClick={() => {
                  if (isFailedTarget) {
                    setPanelMode("diagnostics");
                  }
                }}
                disabled={!isFailedTarget}
                className={cn(
                  "rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                  panelMode === "diagnostics" && isFailedTarget
                    ? "bg-white text-rose-700 shadow-sm dark:bg-zinc-800 dark:text-rose-300"
                    : "text-zinc-500 hover:text-zinc-700 disabled:cursor-not-allowed disabled:text-zinc-300 dark:text-zinc-400 dark:hover:text-zinc-200 dark:disabled:text-zinc-600",
                )}
              >
                Diagnostic Tool
              </button>
            </div>
          </section>
        ) : null}

        {panelMode === "diagnostics" && isFailedTarget ? (
          <section className="space-y-4">
            <div className="rounded-xl border border-rose-200/80 bg-rose-50/80 p-4 dark:border-rose-900/70 dark:bg-rose-950/25">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-rose-500" />
                    <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Scientific Troubleshooter</h3>
                  </div>
                  <p className="text-sm text-zinc-600 dark:text-zinc-300">
                    Exit metadata, stdout tail, and execution logs are bundled for failure analysis.
                  </p>
                  <div className="flex flex-wrap items-center gap-2 text-[11px]">
                    <span className="rounded-full border border-rose-200/80 bg-white/80 px-2.5 py-1 font-medium text-rose-700 dark:border-rose-900/70 dark:bg-zinc-900/60 dark:text-rose-300">
                      {toDisplayStatus(summaryState)}
                    </span>
                    {diagnosticsQuery.data?.exit_status !== null && diagnosticsQuery.data?.exit_status !== undefined ? (
                      <span className="rounded-full border border-zinc-200/80 bg-white/80 px-2.5 py-1 font-mono text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-200">
                        exit_status={diagnosticsQuery.data.exit_status}
                      </span>
                    ) : null}
                    {diagnosticsQuery.data?.computer_label ? (
                      <span className="rounded-full border border-zinc-200/80 bg-white/80 px-2.5 py-1 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300">
                        {diagnosticsQuery.data.computer_label}
                      </span>
                    ) : null}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onExplainFailure(processItemForFailure, diagnosticsQuery.data ?? null)}
                  disabled={diagnosticsQuery.isPending}
                  className="inline-flex items-center gap-2 rounded-xl bg-zinc-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-zinc-800 disabled:cursor-wait disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                >
                  <Bot className="h-3.5 w-3.5" />
                  Explain Failure
                </button>
              </div>
            </div>

            {diagnosticsQuery.isError ? (
              <div className="rounded-xl border border-rose-200/80 bg-rose-50/80 px-4 py-3 text-sm text-rose-600 dark:border-rose-900/70 dark:bg-rose-950/25 dark:text-rose-300">
                Failed to collect diagnostic artifacts.
              </div>
            ) : diagnosticsQuery.isPending ? (
              <div className="rounded-xl border border-zinc-200/80 bg-zinc-50/80 px-4 py-3 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400">
                Collecting exit status, stdout tail, and process logs...
              </div>
            ) : diagnosticsQuery.data ? (
              <>
                <section className="space-y-2">
                  <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Failure Summary</h3>
                  <div className="rounded-xl border border-zinc-200/80 bg-zinc-50/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900/60">
                    <p className="text-xs uppercase tracking-[0.12em] text-zinc-500 dark:text-zinc-400">Exit Message</p>
                    <p className="mt-2 text-sm leading-6 text-zinc-800 dark:text-zinc-200">
                      {diagnosticsQuery.data.exit_message || "Worker did not report an exit_message."}
                    </p>
                  </div>
                </section>

                <section className="space-y-2">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
                    <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                      STDOUT Tail
                      {diagnosticsQuery.data.stdout_excerpt.filename ? ` · ${diagnosticsQuery.data.stdout_excerpt.filename}` : ""}
                    </h3>
                  </div>
                  {diagnosticsQuery.data.stdout_excerpt.text ? (
                    <pre className="max-h-[18rem] overflow-auto rounded-lg border border-zinc-200/80 bg-zinc-50/70 p-3 text-xs leading-5 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/65 dark:text-zinc-200">
                      {diagnosticsQuery.data.stdout_excerpt.text}
                    </pre>
                  ) : (
                    <p className="rounded-xl border border-zinc-200/80 bg-zinc-50/80 px-4 py-3 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400">
                      No stdout artifact was recovered for this failed process.
                    </p>
                  )}
                </section>

                <section className="space-y-2">
                  <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Execution Log Excerpt</h3>
                  {diagnosticsQuery.data.log_excerpt.text ? (
                    <pre className="max-h-[14rem] overflow-auto rounded-lg border border-zinc-200/80 bg-zinc-50/70 p-3 text-xs leading-5 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/65 dark:text-zinc-200">
                      {diagnosticsQuery.data.log_excerpt.text}
                    </pre>
                  ) : (
                    <p className="rounded-xl border border-zinc-200/80 bg-zinc-50/80 px-4 py-3 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400">
                      No process log excerpt is available.
                    </p>
                  )}
                </section>

                {diagnosticsQuery.data.stderr_excerpt ? (
                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Scheduler STDERR</h3>
                    <pre className="max-h-[10rem] overflow-auto rounded-lg border border-zinc-200/80 bg-zinc-50/70 p-3 text-xs leading-5 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/65 dark:text-zinc-200">
                      {diagnosticsQuery.data.stderr_excerpt}
                    </pre>
                  </section>
                ) : null}
              </>
            ) : null}
          </section>
        ) : (
          overviewContent
        )}
      </div>
    </div>
  );
}

export function ProcessDetailDrawer({ process, onClose, onAddContextNode, onExplainFailure }: ProcessDetailDrawerProps) {
  const isOpen = process !== null;
  const [stack, setStack] = useState<InspectorTarget[]>([]);

  useEffect(() => {
    if (!process) {
      setStack([]);
      return;
    }
    setStack([buildRootTarget(process)]);
  }, [process]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen, onClose]);

  const activeIndex = Math.max(0, stack.length - 1);
  const activeTarget = stack[activeIndex] ?? null;
  const panelWidth = stack.length > 0 ? 100 / stack.length : 100;
  const translatePercent = activeIndex * panelWidth;

  const handleOpenNodeDetail = (link: ProcessNodeLink, direction: InspectorLinkDirection) => {
    const target = buildLinkTarget(link, direction);
    setStack((current) => {
      const existingIndex = current.findIndex((item) => item.pk === target.pk);
      if (existingIndex >= 0) {
        return current.slice(0, existingIndex + 1);
      }
      return [...current, target];
    });
  };

  const handleNavigateToIndex = (index: number) => {
    setStack((current) => current.slice(0, index + 1));
  };

  return (
    <div className={cn("fixed inset-0 z-50 transition-opacity duration-200", isOpen ? "pointer-events-auto" : "pointer-events-none")}>
      <div
        className={cn("absolute inset-0 bg-zinc-950/45 transition-opacity duration-200", isOpen ? "opacity-100" : "opacity-0")}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={cn(
          "absolute bottom-4 right-0 top-4 h-auto max-h-[calc(100vh-2rem)] w-full max-w-2xl transform rounded-l-2xl border-l border-t border-b border-zinc-200/80 bg-white shadow-2xl transition-transform duration-300 dark:border-zinc-800 dark:bg-zinc-950",
          isOpen ? "translate-x-0" : "translate-x-full",
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Process detail drawer"
      >
        <div className="flex h-full min-h-0 flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-zinc-200/70 px-6 pb-4 pt-6 dark:border-zinc-800">
            <div className="min-w-0 flex items-center gap-3">
              {activeIndex > 0 ? (
                <button
                  type="button"
                  onClick={() => handleNavigateToIndex(activeIndex - 1)}
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-zinc-500 transition-colors duration-200 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100"
                  aria-label="Back to previous inspector panel"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
              ) : null}
              <h2 className="truncate text-xl font-semibold text-zinc-900 dark:text-zinc-100">
                {formatInspectorNodeTitle(activeTarget)}
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-zinc-500 transition-colors duration-200 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100"
              aria-label="Close process detail drawer"
            >
              <X className="h-4 w-4" />
            </button>
          </header>

          <div className="relative min-h-0 flex-1 overflow-hidden">
            <div
              className="flex h-full transition-transform duration-300 ease-out"
              style={{
                width: `${Math.max(stack.length, 1) * 100}%`,
                transform: `translateX(-${translatePercent}%)`,
              }}
            >
              {stack.map((target, index) => (
                <div
                  key={`${target.pk}-${target.breadcrumb}-${index}`}
                  className="h-full shrink-0 border-r border-zinc-200/70 bg-white dark:border-zinc-800 dark:bg-zinc-950"
                  style={{ width: `${panelWidth}%` }}
                >
                  <InspectorPanel
                    target={target}
                    fallbackPreviewNode={index === 0 && process ? process : null}
                    onOpenNodeDetail={handleOpenNodeDetail}
                    onAddContextNode={onAddContextNode}
                    onExplainFailure={onExplainFailure}
                    preferredMode={
                      index === 0 && process && FAILED_STATES.has(normalizeState(process.process_state || process.state))
                        ? "diagnostics"
                        : "overview"
                    }
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
