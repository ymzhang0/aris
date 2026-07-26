import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  CHAT_STREAM_URL,
  GROUPS_STREAM_URL,
  INFRASTRUCTURE_STREAM_URL,
  LOGS_STREAM_URL,
  PROCESS_EVENTS_URL,
  PROCESSES_STREAM_URL,
  activateChatSession,
  addNodesToGroup,
  cancelPendingSubmission,
  createChatProject,
  createChatSession,
  createGroup,
  deleteChatItems,
  deleteChatProject,
  deleteChatSession,
  deleteGroup,
  exportGroup,
  getBootstrap,
  getChatMessages,
  getChatSessions,
  getGroups,
  getLogs,
  getProcessCloneDraft,
  getProcesses,
  renameGroup,
  sendChat,
  softDeleteNode,
  stopChat,
  submitPreviewDraft,
  uploadArchive,
  updateChatSession,
  updateChatSessionTitle,
} from "@/lib/api";
import { ChatPanel } from "@/components/dashboard/chat-panel";
import { HistorySidebar } from "@/components/dashboard/history-sidebar";
import { MainWorkspace } from "@/components/dashboard/MainWorkspace";
import { ProcessDetailDrawer } from "@/components/dashboard/process-detail-drawer";
import { RuntimeTerminal } from "@/components/dashboard/runtime-terminal";
import { Sidebar } from "@/components/dashboard/sidebar";
import { WorkspaceExplorerSidebar, type WorkspaceExplorerFileSelection } from "@/components/dashboard/workspace-explorer-sidebar";
import { Button } from "@/components/ui/button";
import { cn, decodeEscapedUnicode, decodeEscapedUnicodeDeep } from "@/lib/utils";
import {
  SubmissionModal,
  type SubmissionDraftPayload,
  type SubmissionModalState,
  type SubmissionSubmitDraft,
} from "@/components/dashboard/submission-modal";
import { useProjectEnvironmentSync } from "@/store/EnvironmentStore";
import type {
  ChatMessage,
  ChatSessionSnapshot,
  ChatSessionsResponse,
  ChatSessionSummary,
  ChatSnapshot,
  FocusNode,
  GroupItem,
  GroupsResponse,
  InfrastructureComputer,
  ProcessDiagnosticsResponse,
  ProcessItem,
  ProcessesResponse,
  ResourceAttachment,
  SendChatRequest,
  SessionParameter,
} from "@/types/aiida";
import { Database, FolderOpen, History, Moon, Sun } from "lucide-react";

const THEME_STORAGE_KEY = "aris.dashboard.theme";
const CURRENT_SESSION_STORAGE_KEY = "current_session_id";
const CHAT_POLL_INTERVAL_MS = 350;
const GROUP_SELECTION_ALL = "__all_groups__";
const GROUP_SELECTION_CURRENT_CONTEXT = "__current_context__";

function initialTheme(): "light" | "dark" {
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
  return saved === "light" ? "light" : "dark";
}

function readStoredSessionId(): string | null {
  return normalizeSessionId(window.localStorage.getItem(CURRENT_SESSION_STORAGE_KEY));
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === "AbortError") {
    return true;
  }
  if (typeof error === "object" && error !== null) {
    const maybeError = error as { name?: string; code?: string };
    return maybeError.name === "AbortError" || maybeError.code === "ERR_CANCELED";
  }
  return false;
}

function isTurnFinalized(messages: ChatMessage[], turnId: number): boolean {
  return messages.some(
    (message, index) =>
      (message.turn_id > 0 ? message.turn_id : index + 1) === turnId &&
      message.role !== "user" &&
      message.status !== "thinking",
  );
}

function scoreChatMessages(messages: ChatMessage[]): number {
  const finalizedCount = messages.reduce((count, message) => {
    if (message.role === "user") {
      return count;
    }
    return count + (message.status !== "thinking" ? 1 : 0);
  }, 0);
  const totalChars = messages.reduce((count, message) => count + (message.text?.length ?? 0), 0);
  return finalizedCount * 1_000_000 + messages.length * 10_000 + totalChars;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function buildFailureConsultPrompt(
  process: ProcessItem,
  diagnostics?: ProcessDiagnosticsResponse | null,
): string {
  const lines = [
    "You are a computational materials science expert specializing in Quantum ESPRESSO, AiiDA workflows, and remote HPC scheduler failures.",
    "Diagnose this failed AiiDA/QE process. Prioritize convergence problems, mixing_beta, starting_magnetization, diagonalization, conv_thr, occupations, walltime/memory pressure, MPI/parallelisation mismatches, parser failures, and missing pseudopotential or file issues.",
    "Return four sections:",
    "1. Most likely root cause",
    "2. Evidence from the logs",
    "3. Concrete QE/AiiDA parameter changes to try next",
    "4. Immediate next actions on the HPC side",
    "",
    `Node PK: #${process.pk}`,
    `Label: ${process.label || process.process_label || process.node_type}`,
    `Node Type: ${process.node_type}`,
    `Process Label: ${process.process_label || "Unknown"}`,
    `State: ${process.process_state || process.state || "Unknown"}`,
  ];

  if (diagnostics?.computer_label) {
    lines.push(`Computer: ${diagnostics.computer_label}`);
  }
  if (diagnostics?.exit_status !== null && diagnostics?.exit_status !== undefined) {
    lines.push(`Exit Status: ${diagnostics.exit_status}`);
  }
  if (diagnostics?.exit_message) {
    lines.push(`Exit Message: ${diagnostics.exit_message}`);
  }
  if (diagnostics?.stdout_excerpt?.text) {
    lines.push("");
    lines.push(`STDOUT Tail (${diagnostics.stdout_excerpt.filename || diagnostics.stdout_excerpt.source || "stdout"}):`);
    lines.push(diagnostics.stdout_excerpt.text);
  }
  if (diagnostics?.log_excerpt?.text) {
    lines.push("");
    lines.push("Process Log Excerpt:");
    lines.push(diagnostics.log_excerpt.text);
  }
  if (diagnostics?.stderr_excerpt) {
    lines.push("");
    lines.push("Scheduler STDERR:");
    lines.push(diagnostics.stderr_excerpt);
  }
  if (!diagnostics) {
    lines.push("");
    lines.push("No structured diagnostics payload was available; infer the likely failure mode from the node metadata and explain what extra artifacts should be inspected.");
  }

  return lines.join("\n");
}

function normalizeTurnId(message: ChatMessage, index: number): number {
  return message.turn_id > 0 ? message.turn_id : index + 1;
}

function normalizeSessionId(sessionId: string | null | undefined): string | null {
  const cleaned = String(sessionId || "").trim();
  return cleaned || null;
}

function normalizeGroupSelection(value: string | null | undefined): string {
  const cleaned = String(value || "").trim();
  return cleaned || "";
}

function resolveCurrentContextGroupLabel(session: ChatSessionSummary | null): string | null {
  if (!session) {
    return null;
  }
  const label =
    typeof session.session_group_label === "string" && session.session_group_label.trim()
      ? session.session_group_label.trim()
      : "";
  return label || null;
}

function resolveSelectedGroupLabel(selection: string, currentContextGroupLabel: string | null): string | null {
  const normalizedSelection = normalizeGroupSelection(selection);
  if (!normalizedSelection || normalizedSelection === GROUP_SELECTION_ALL) {
    return null;
  }
  if (normalizedSelection === GROUP_SELECTION_CURRENT_CONTEXT) {
    return currentContextGroupLabel;
  }
  return normalizedSelection;
}

function resolveSelectedGroupDisplayLabel(selection: string, currentContextGroupLabel: string | null): string | null {
  const normalizedSelection = normalizeGroupSelection(selection);
  if (!normalizedSelection || normalizedSelection === GROUP_SELECTION_ALL) {
    return null;
  }
  if (normalizedSelection === GROUP_SELECTION_CURRENT_CONTEXT) {
    return currentContextGroupLabel ? "Current Context" : null;
  }
  return normalizedSelection;
}

function resolveProcessNodeType(nodeTypeFilter: string): string | undefined {
  if (nodeTypeFilter === "tasks" || nodeTypeFilter === "failed") {
    return "ProcessNode";
  }
  if (nodeTypeFilter === "structures") {
    return "StructureData";
  }
  return undefined;
}

function resolveProcessRootOnly(_nodeTypeFilter: string): boolean {
  return false;
}

function dedupeFocusNodes(nodes: FocusNode[]): FocusNode[] {
  const seen = new Set<number>();
  return nodes.filter((node) => {
    if (!node || !Number.isInteger(node.pk) || node.pk <= 0 || seen.has(node.pk)) {
      return false;
    }
    seen.add(node.pk);
    return true;
  });
}

function normalizeSessionParameters(raw: unknown): SessionParameter[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const seen = new Set<string>();
  return raw
    .map((entry) => {
      const record = asRecord(entry);
      if (!record) {
        return null;
      }
      const key = typeof record.key === "string" ? decodeEscapedUnicode(record.key).trim() : "";
      const value = typeof record.value === "string" ? decodeEscapedUnicode(record.value).trim() : "";
      if (!key || !value) {
        return null;
      }
      const normalizedKey = key.toLowerCase();
      if (seen.has(normalizedKey)) {
        return null;
      }
      seen.add(normalizedKey);
      return { key, value };
    })
    .filter((entry): entry is SessionParameter => Boolean(entry));
}

function normalizeChatSessionSnapshot(snapshot: ChatSessionSnapshot | null | undefined): ChatSessionSnapshot {
  const decodedSnapshot = decodeEscapedUnicodeDeep(snapshot);
  const contextNodes = Array.isArray(decodedSnapshot?.context_nodes)
    ? dedupeFocusNodes(
        decodedSnapshot.context_nodes.map((node) => ({
          pk: Number(node.pk),
          label: String(node.label || `#${node.pk}`),
          formula: node.formula ?? null,
          node_type: String(node.node_type || "Unknown"),
        })),
      )
    : [];
  const pinnedNodes = Array.isArray(decodedSnapshot?.pinned_nodes)
    ? dedupeFocusNodes(
        decodedSnapshot.pinned_nodes.map((node) => ({
          pk: Number(node.pk),
          label: String(node.label || `#${node.pk}`),
          formula: node.formula ?? null,
          node_type: String(node.node_type || "Unknown"),
        })),
      )
    : [];
  const selectedGroup =
    typeof decodedSnapshot?.selected_group === "string" && decodedSnapshot.selected_group.trim()
      ? decodedSnapshot.selected_group.trim()
      : null;
  const selectedModel =
    typeof decodedSnapshot?.selected_model === "string" && decodedSnapshot.selected_model.trim()
      ? decodedSnapshot.selected_model.trim()
      : null;
  const sessionEnvironment =
    typeof decodedSnapshot?.session_environment === "string" && decodedSnapshot.session_environment.trim()
      ? decodedSnapshot.session_environment.trim().toLowerCase()
      : null;
  const promptOverride =
    typeof decodedSnapshot?.prompt_override === "string" && decodedSnapshot.prompt_override.trim()
      ? decodedSnapshot.prompt_override.trim()
      : null;
  return {
    context_nodes: contextNodes,
    pinned_nodes: pinnedNodes,
    selected_group: selectedGroup,
    selected_model: selectedModel,
    session_environment: sessionEnvironment,
    session_environment_auto: decodedSnapshot?.session_environment_auto !== false,
    prompt_override: promptOverride,
    session_parameters: normalizeSessionParameters(decodedSnapshot?.session_parameters),
  };
}

function normalizeChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    ...message,
    role: String(message.role ?? "assistant"),
    text: decodeEscapedUnicode(String(message.text ?? "")),
    status: String(message.status ?? "done"),
    payload: decodeEscapedUnicodeDeep(message.payload ?? null),
  }));
}

function buildChatSessionSnapshotPayload(params: {
  contextNodes: FocusNode[];
  pinnedNodes: FocusNode[];
  selectedGroup: string;
  selectedModel: string;
  sessionEnvironment: string | null;
  sessionEnvironmentAuto: boolean;
  promptOverride: string;
  sessionParameters: SessionParameter[];
}): Record<string, unknown> {
  return {
    context_nodes: dedupeFocusNodes(params.contextNodes).map((node) => ({
      pk: node.pk,
      label: node.label,
      formula: node.formula,
      node_type: node.node_type,
    })),
    pinned_nodes: dedupeFocusNodes(params.pinnedNodes).map((node) => ({
      pk: node.pk,
      label: node.label,
      formula: node.formula,
      node_type: node.node_type,
    })),
    selected_group: params.selectedGroup.trim() || null,
    selected_model: params.selectedModel.trim() || null,
    session_environment: params.sessionEnvironment?.trim().toLowerCase() || null,
    session_environment_auto: params.sessionEnvironmentAuto,
    prompt_override: params.promptOverride.trim() || null,
    session_parameters: normalizeSessionParameters(params.sessionParameters),
  };
}

type MergeIndexedMessage = {
  key: string;
  message: ChatMessage;
};

function buildMergeIndexedMessages(messages: ChatMessage[]): MergeIndexedMessage[] {
  const counters = new Map<string, number>();
  return messages.map((message, index) => {
    const mergeBase = `${normalizeTurnId(message, index)}|${message.role}`;
    const occurrence = counters.get(mergeBase) ?? 0;
    counters.set(mergeBase, occurrence + 1);
    return {
      key: `${mergeBase}|${occurrence}`,
      message,
    };
  });
}

function isToolStatusText(text: string): boolean {
  const lines = text
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return false;
  }
  return lines.every((line) =>
    /^(thinking:|running:|step:|\u2699\uFE0F\s*\[step\]\s*:)/i.test(line),
  );
}

function hasActiveAiidaAgentStep(
  messages: ChatMessage[],
  activeTurnId: number | null,
  isChatLoading: boolean,
): boolean {
  if (!isChatLoading || messages.length === 0) {
    return false;
  }

  const fallbackTurnId = messages.reduce<number | null>((latest, message, index) => {
    if (message.role !== "assistant" || message.status !== "thinking") {
      return latest;
    }
    return normalizeTurnId(message, index);
  }, null);
  const targetTurnId = activeTurnId ?? fallbackTurnId;
  if (targetTurnId === null) {
    return false;
  }

  return messages.some((message, index) => {
    if (message.role !== "assistant" || message.status !== "thinking") {
      return false;
    }
    if (normalizeTurnId(message, index) !== targetTurnId) {
      return false;
    }

    const payload = asRecord(message.payload);
    const payloadStatus = asRecord(payload?.status);
    const toolCalls = Array.isArray(payload?.tool_calls)
      ? payload.tool_calls.map((entry) => String(entry ?? "").trim()).filter(Boolean)
      : [];
    const statusSteps = Array.isArray(payloadStatus?.steps)
      ? payloadStatus.steps.map((entry) => String(entry ?? "").trim()).filter(Boolean)
      : [];
    const currentStep =
      typeof payloadStatus?.current_step === "string" ? payloadStatus.current_step.trim() : "";
    const text = String(message.text ?? "").trim();

    return (
      toolCalls.some((entry) => entry.toLowerCase().includes("aiida.agent.step")) ||
      statusSteps.length > 0 ||
      Boolean(currentStep) ||
      /^(thinking:|running:|step:|\u2699\uFE0F\s*\[step\]\s*:)/i.test(text)
    );
  });
}

function extractToolCalls(payload: Record<string, unknown> | null): string[] {
  if (!payload || !Array.isArray(payload.tool_calls)) {
    return [];
  }
  return payload.tool_calls
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
}

function mergeToolCalls(previousCalls: string[], incomingCalls: string[]): string[] {
  if (previousCalls.length === 0) {
    return incomingCalls;
  }
  if (incomingCalls.length === 0) {
    return previousCalls;
  }
  const merged: string[] = [];
  const seen = new Set<string>();
  [...previousCalls, ...incomingCalls].forEach((call) => {
    if (seen.has(call)) {
      return;
    }
    seen.add(call);
    merged.push(call);
  });
  return merged;
}

function mergeMessagePayload(
  previousPayload: Record<string, unknown> | null | undefined,
  incomingPayload: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null | undefined {
  const previousRecord = asRecord(previousPayload);
  const incomingRecord = asRecord(incomingPayload);

  if (!previousRecord && !incomingRecord) {
    return incomingPayload ?? previousPayload;
  }
  if (!previousRecord) {
    return incomingRecord;
  }
  if (!incomingRecord) {
    return previousRecord;
  }

  const merged = { ...previousRecord, ...incomingRecord };
  const mergedToolCalls = mergeToolCalls(
    extractToolCalls(previousRecord),
    extractToolCalls(incomingRecord),
  );
  if (mergedToolCalls.length > 0) {
    merged.tool_calls = mergedToolCalls;
  }
  return merged;
}

function mergeMessageText(previous: ChatMessage, incoming: ChatMessage): string {
  const previousText = typeof previous.text === "string" ? previous.text : "";
  const incomingText = typeof incoming.text === "string" ? incoming.text : "";
  const previousTrimmed = previousText.trim();
  const incomingTrimmed = incomingText.trim();

  if (!incomingTrimmed && previousTrimmed) {
    return previousText;
  }

  const incomingLooksLikeToolStatus = isToolStatusText(incomingText);
  const previousLooksLikeToolStatus = isToolStatusText(previousText);
  if (incoming.status === "thinking" && previousTrimmed) {
    if (!previousLooksLikeToolStatus && (incomingLooksLikeToolStatus || !incomingTrimmed)) {
      return previousText;
    }
    if (previousLooksLikeToolStatus && incomingLooksLikeToolStatus && previousText.length > incomingText.length) {
      return previousText;
    }
    if (!previousLooksLikeToolStatus && incomingTrimmed.length <= previousTrimmed.length) {
      return previousText;
    }
  }

  if (incomingLooksLikeToolStatus && previousTrimmed && !previousLooksLikeToolStatus) {
    return previousText;
  }

  if (incoming.status !== "thinking" && !incomingTrimmed && previousTrimmed) {
    return previousText;
  }

  return incomingText;
}

function mergeChatMessages(previous: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const previousByKey = new Map<string, ChatMessage[]>();
  buildMergeIndexedMessages(previous).forEach(({ key, message }) => {
    const bucket = previousByKey.get(key) ?? [];
    bucket.push(message);
    previousByKey.set(key, bucket);
  });

  return buildMergeIndexedMessages(incoming).map(({ key, message: incomingMessage }) => {
    const bucket = previousByKey.get(key);
    const previousMessage = bucket?.shift();
    if (!previousMessage) {
      return incomingMessage;
    }

    const mergedText = mergeMessageText(previousMessage, incomingMessage);
    const mergedPayload = mergeMessagePayload(previousMessage.payload, incomingMessage.payload);
    const preserveDoneStatus =
      previousMessage.status !== "thinking" &&
      incomingMessage.status === "thinking" &&
      mergedText.trim().length > 0 &&
      mergedText === previousMessage.text;
    const mergedMessage: ChatMessage = {
      ...incomingMessage,
      text: mergedText,
      status: preserveDoneStatus ? previousMessage.status : incomingMessage.status,
    };
    if (mergedPayload !== undefined) {
      mergedMessage.payload = mergedPayload;
    }
    return mergedMessage;
  });
}

function extractPkReferences(text: string): number[] {
  const seen = new Set<number>();
  const matches = text.matchAll(/#\s*(\d+)\b/g);
  for (const match of matches) {
    const raw = match[1];
    if (!raw) {
      continue;
    }
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed) || parsed <= 0 || seen.has(parsed)) {
      continue;
    }
    seen.add(parsed);
  }
  return [...seen];
}

function mergeUniquePks(...sources: number[][]): number[] {
  const merged: number[] = [];
  const seen = new Set<number>();
  sources.flat().forEach((pk) => {
    if (!Number.isFinite(pk) || pk <= 0 || seen.has(pk)) {
      return;
    }
    seen.add(pk);
    merged.push(pk);
  });
  return merged;
}

function normalizeGroups(raw: unknown): GroupItem[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const seen = new Set<number>();
  const groups: GroupItem[] = [];
  raw.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }
    const item = entry as Record<string, unknown>;
    const label = String(item.label ?? "").trim();
    const pk = Number.parseInt(String(item.pk ?? ""), 10);
    const count = Number.parseInt(String(item.count ?? 0), 10);
    if (!label || Number.isNaN(pk) || pk <= 0 || seen.has(pk)) {
      return;
    }
    seen.add(pk);
    groups.push({
      pk,
      label,
      count: Number.isNaN(count) || count < 0 ? 0 : count,
      type_string:
        typeof item.type_string === "string" && item.type_string.trim() ? item.type_string.trim() : null,
    });
  });
  return groups;
}

export default function App() {
  const queryClient = useQueryClient();
  const [theme, setTheme] = useState<"light" | "dark">(initialTheme);
  const [sidebarView, setSidebarView] = useState<"explorer" | "history" | "workspace">("explorer");
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedGroup, setSelectedGroup] = useState("");
  const [nodeTypeFilter, setNodeTypeFilter] = useState<"all" | "structures" | "tasks" | "failed">("all");
  const [processLimit, setProcessLimit] = useState(15);
  const [pendingProcessLimit, setPendingProcessLimit] = useState<number | null>(null);
  const [contextNodes, setContextNodes] = useState<FocusNode[]>([]);
  const [pinnedNodes, setPinnedNodes] = useState<FocusNode[]>([]);
  const [sessionEnvironment, setSessionEnvironment] = useState<string | null>(null);
  const [sessionEnvironmentAuto, setSessionEnvironmentAuto] = useState(true);
  const [promptOverride, setPromptOverride] = useState("");
  const [sessionParameters, setSessionParameters] = useState<SessionParameter[]>([]);
  const [activeProcess, setActiveProcess] = useState<ProcessItem | null>(null);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [activeTurnId, setActiveTurnId] = useState<number | null>(null);
  const [activeChatSessionId, setActiveChatSessionId] = useState<string | null>(null);
  const [composerResetVersion, setComposerResetVersion] = useState(0);
  const [streamedLogs, setStreamedLogs] = useState<{ version: number; lines: string[] } | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeWorkspaceProjectId, setActiveWorkspaceProjectId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"CHAT" | "EDITOR">("CHAT");
  const [viewerFile, setViewerFile] = useState<WorkspaceExplorerFileSelection | null>(null);
  const [cloneDraft, setCloneDraft] = useState<SubmissionDraftPayload | null>(null);
  const [cloneTurnId, setCloneTurnId] = useState<number | null>(null);
  const [cloneModalState, setCloneModalState] = useState<SubmissionModalState>({ status: "idle" });
  const [isCloneDraftLoading, setIsCloneDraftLoading] = useState(false);
  const sendAbortControllerRef = useRef<AbortController | null>(null);
  const requestInFlightRef = useRef(false);
  const chatVersionRef = useRef(-1);
  const activeChatSessionRef = useRef<string | null>(null);
  const lastPersistedSnapshotRef = useRef<string>("");
  const hasAttemptedSessionRestoreRef = useRef(false);
  const restoringSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const bootstrapQuery = useQuery({
    queryKey: ["bootstrap"],
    queryFn: getBootstrap,
    refetchOnWindowFocus: false,
  });

  const chatSessionsQuery = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: getChatSessions,
    enabled: bootstrapQuery.isSuccess,
    refetchOnWindowFocus: false,
    refetchInterval: isChatLoading ? 1_500 : 5_000,
  });

  const chatSessions = chatSessionsQuery.data?.items ?? [];
  const chatProjects = chatSessionsQuery.data?.projects ?? [];
  const activeProjectId = chatSessionsQuery.data?.active_project_id ?? null;
  const selectedWorkspaceProject =
    chatProjects.find((project) => project.id === (activeWorkspaceProjectId ?? activeProjectId ?? "")) ?? null;
  const resolvedActiveChatSessionId = activeChatSessionId ?? chatSessionsQuery.data?.active_session_id ?? null;
  const activeChatSession = chatSessions.find((session) => session.id === resolvedActiveChatSessionId) ?? null;
  const activeSessionProject =
    chatProjects.find((project) => project.id === (activeChatSession?.project_id ?? "")) ?? null;
  const currentProjectPath = activeSessionProject?.root_path ?? selectedWorkspaceProject?.root_path ?? null;
  const currentContextGroupLabel = resolveCurrentContextGroupLabel(activeChatSession);
  const selectedGroupLabel = resolveSelectedGroupLabel(selectedGroup, currentContextGroupLabel);
  useProjectEnvironmentSync(activeSessionProject ?? selectedWorkspaceProject ?? null);

  const processesQuery = useQuery({
    queryKey: ["processes", selectedGroup, selectedGroupLabel, processLimit, nodeTypeFilter],
    queryFn: () => {
      return getProcesses(
        processLimit,
        selectedGroupLabel ?? undefined,
        resolveProcessNodeType(nodeTypeFilter),
        undefined,
        undefined,
        resolveProcessRootOnly(nodeTypeFilter),
      );
    },
    enabled: bootstrapQuery.isSuccess,
    refetchInterval: 60_000,
  });

  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: getGroups,
    enabled: bootstrapQuery.isSuccess,
    refetchInterval: 60_000,
  });

  const logsQuery = useQuery({
    queryKey: ["logs"],
    queryFn: () => getLogs(260),
    enabled: bootstrapQuery.isSuccess,
    refetchInterval: 1_500,
  });

  const chatQuery = useQuery({
    queryKey: ["chat"],
    queryFn: getChatMessages,
    enabled: bootstrapQuery.isSuccess,
    refetchInterval: isChatLoading ? CHAT_POLL_INTERVAL_MS : 900,
  });

  const defaultSelectedModel = bootstrapQuery.data?.selected_model ?? bootstrapQuery.data?.models?.[0] ?? "";
  const applyChatSessionsSnapshot = useCallback((snapshot: ChatSessionsResponse | null | undefined) => {
    if (!snapshot || !Array.isArray(snapshot.items) || !Array.isArray(snapshot.projects)) {
      return;
    }

    queryClient.setQueryData<ChatSessionsResponse>(["chat-sessions"], (current) => {
      const incomingVersion = Number.isFinite(snapshot.version) ? Number(snapshot.version) : -1;
      const currentVersion = current?.version ?? -1;
      if (current && incomingVersion >= 0 && incomingVersion < currentVersion) {
        return current;
      }
      return snapshot;
    });

    const incomingActiveSessionId = normalizeSessionId(snapshot.active_session_id);
    setActiveChatSessionId((current) => incomingActiveSessionId ?? current);
  }, [queryClient]);

  const applyChatSnapshot = useCallback((snapshot: ChatSnapshot | null | undefined) => {
    if (!snapshot || !Array.isArray(snapshot.messages)) {
      return;
    }

    const normalizedMessages = normalizeChatMessages(snapshot.messages);
    const incomingSessionId = normalizeSessionId(snapshot.session_id);
    const isSessionChanged = incomingSessionId !== activeChatSessionRef.current;
    const incomingVersion = Number.isFinite(snapshot.version) ? snapshot.version : -1;
    const normalizedSnapshot = normalizeChatSessionSnapshot(snapshot.snapshot);

    setActiveChatSessionId(incomingSessionId);
    if (isSessionChanged) {
      activeChatSessionRef.current = incomingSessionId;
      chatVersionRef.current = incomingVersion;
      setMessages(normalizedMessages);
      setContextNodes(normalizedSnapshot.context_nodes);
      setPinnedNodes(normalizedSnapshot.pinned_nodes);
      setSelectedGroup(normalizedSnapshot.selected_group ?? "");
      setSelectedModel(normalizedSnapshot.selected_model ?? defaultSelectedModel);
      setSessionEnvironment(normalizedSnapshot.session_environment);
      setSessionEnvironmentAuto(normalizedSnapshot.session_environment_auto);
      setPromptOverride(normalizedSnapshot.prompt_override ?? "");
      setSessionParameters(normalizedSnapshot.session_parameters);
      lastPersistedSnapshotRef.current = JSON.stringify(normalizedSnapshot);
      return;
    }

    setMessages((previous) => {
      const currentVersion = chatVersionRef.current;
      if (incomingVersion < currentVersion) {
        return previous;
      }
      const mergedMessages = mergeChatMessages(previous, normalizedMessages);
      if (incomingVersion === currentVersion) {
        const nextScore = scoreChatMessages(mergedMessages);
        const prevScore = scoreChatMessages(previous);
        if (nextScore < prevScore) {
          return previous;
        }
      }

      chatVersionRef.current = incomingVersion;
      return mergedMessages;
    });
  }, [defaultSelectedModel]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }

    const source = new EventSource(LOGS_STREAM_URL);

    const applySnapshot = (payload: string) => {
      try {
        const parsed = JSON.parse(payload) as { version?: number; lines?: string[] };
        if (Array.isArray(parsed.lines)) {
          setStreamedLogs({
            version: Number.isFinite(parsed.version) ? Number(parsed.version) : -1,
            lines: parsed.lines,
          });
        }
      } catch (error) {
        console.error("Failed to parse runtime log stream payload", error);
      }
    };

    source.addEventListener("logs", (event) => {
      applySnapshot((event as MessageEvent<string>).data);
    });
    source.onmessage = (event) => {
      applySnapshot(event.data);
    };

    return () => {
      source.close();
    };
  }, [bootstrapQuery.isSuccess]);

  useEffect(() => {
    if (!bootstrapQuery.data?.chat) {
      return;
    }
    applyChatSnapshot(bootstrapQuery.data.chat);
  }, [applyChatSnapshot, bootstrapQuery.data?.chat]);

  useEffect(() => {
    if (!chatQuery.data) {
      return;
    }
    applyChatSnapshot(chatQuery.data);
  }, [applyChatSnapshot, chatQuery.data]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }

    const source = new EventSource(CHAT_STREAM_URL);
    const applySnapshot = (payload: string) => {
      try {
        const parsed = JSON.parse(payload) as ChatSnapshot;
        applyChatSnapshot(parsed);
      } catch (error) {
        console.error("Failed to parse chat stream payload", error);
      }
    };

    source.addEventListener("chat", (event) => {
      applySnapshot((event as MessageEvent<string>).data);
    });
    source.addEventListener("sessions", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent<string>).data) as ChatSessionsResponse;
        applyChatSessionsSnapshot(parsed);
      } catch (error) {
        console.error("Failed to parse chat sessions stream payload", error);
      }
    });
    source.onmessage = (event) => {
      applySnapshot(event.data);
    };

    return () => {
      source.close();
    };
  }, [applyChatSessionsSnapshot, applyChatSnapshot, bootstrapQuery.isSuccess]);

  // \u2500\u2500 SSE: Real-time process state changes \u2500\u2500
  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }

    const searchParams = new URLSearchParams();
    searchParams.set("limit", String(processLimit));
    if (selectedGroupLabel) {
      searchParams.set("group_label", selectedGroupLabel);
    }
    const resolvedNodeType = resolveProcessNodeType(nodeTypeFilter);
    if (resolvedNodeType) {
      searchParams.set("node_type", resolvedNodeType);
    }
    if (!resolveProcessRootOnly(nodeTypeFilter)) {
      searchParams.set("root_only", "false");
    }

    const streamUrl = searchParams.size > 0
      ? `${PROCESSES_STREAM_URL}?${searchParams.toString()}`
      : PROCESSES_STREAM_URL;
    const queryKey = ["processes", selectedGroup, selectedGroupLabel, processLimit, nodeTypeFilter] as const;
    const source = new EventSource(streamUrl);

    const syncProcesses = (rawData: string) => {
      try {
        const parsed = JSON.parse(rawData) as { items?: ProcessItem[] };
        if (!Array.isArray(parsed.items)) {
          return;
        }
        queryClient.setQueryData<ProcessesResponse>(queryKey, { items: parsed.items });
      } catch (error) {
        console.error("Failed to parse processes stream payload", error);
      }
    };

    source.addEventListener("processes", (event) => {
      syncProcesses((event as MessageEvent<string>).data);
    });
    source.onmessage = (event) => {
      syncProcesses(event.data);
    };

    return () => {
      source.close();
    };
  }, [bootstrapQuery.isSuccess, nodeTypeFilter, processLimit, queryClient, selectedGroup, selectedGroupLabel]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }

    const source = new EventSource(GROUPS_STREAM_URL);

    const syncGroups = (rawData: string) => {
      try {
        const parsed = JSON.parse(rawData) as { items?: GroupItem[] };
        if (!Array.isArray(parsed.items)) {
          return;
        }
        queryClient.setQueryData<GroupsResponse>(["groups"], { items: parsed.items });
      } catch (error) {
        console.error("Failed to parse groups stream payload", error);
      }
    };

    source.addEventListener("groups", (event) => {
      syncGroups((event as MessageEvent<string>).data);
    });
    source.onmessage = (event) => {
      syncGroups(event.data);
    };

    return () => {
      source.close();
    };
  }, [bootstrapQuery.isSuccess, queryClient]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }

    const source = new EventSource(PROCESS_EVENTS_URL);

    source.addEventListener("process_state_change", () => {
      queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      queryClient.invalidateQueries({ queryKey: ["chat-session-batch-progress"] });
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    });
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.event === "process_state_change" || data.pk) {
          queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
          queryClient.invalidateQueries({ queryKey: ["chat-session-batch-progress"] });
          queryClient.invalidateQueries({ queryKey: ["groups"] });
        }
      } catch {
        // ignore unparseable keepalive messages
      }
    };

    return () => {
      source.close();
    };
  }, [bootstrapQuery.isSuccess, queryClient]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }

    const source = new EventSource(INFRASTRUCTURE_STREAM_URL);

    const syncInfrastructure = (rawData: string) => {
      try {
        const parsed = JSON.parse(rawData) as { items?: InfrastructureComputer[] };
        if (!Array.isArray(parsed.items)) {
          return;
        }
        queryClient.setQueryData<InfrastructureComputer[]>(["aiida-infrastructure"], parsed.items);
        void queryClient.invalidateQueries({ queryKey: ["aiida-bridge-status"] });
        void queryClient.invalidateQueries({ queryKey: ["aiida-bridge-resources"] });
        void queryClient.invalidateQueries({ queryKey: ["aiida-bridge-profiles"] });
      } catch (error) {
        console.error("Failed to parse infrastructure stream payload", error);
      }
    };

    source.addEventListener("infrastructure", (event) => {
      syncInfrastructure((event as MessageEvent<string>).data);
    });
    source.onmessage = (event) => {
      syncInfrastructure(event.data);
    };

    return () => {
      source.close();
    };
  }, [bootstrapQuery.isSuccess, queryClient]);

  useEffect(() => {
    if (selectedModel) {
      return;
    }
    const fallback = bootstrapQuery.data?.selected_model ?? bootstrapQuery.data?.models?.[0] ?? "";
    if (fallback) {
      setSelectedModel(fallback);
    }
  }, [bootstrapQuery.data, selectedModel]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess) {
      return;
    }
    const sessionId = normalizeSessionId(activeChatSessionId);
    if (sessionId) {
      window.localStorage.setItem(CURRENT_SESSION_STORAGE_KEY, sessionId);
      return;
    }
    if (!hasAttemptedSessionRestoreRef.current) {
      return;
    }
    window.localStorage.removeItem(CURRENT_SESSION_STORAGE_KEY);
  }, [activeChatSessionId, bootstrapQuery.isSuccess]);

  useEffect(() => {
    if (!bootstrapQuery.isSuccess || !chatSessionsQuery.isSuccess || hasAttemptedSessionRestoreRef.current) {
      return;
    }

    const storedSessionId = readStoredSessionId();
    if (!storedSessionId) {
      hasAttemptedSessionRestoreRef.current = true;
      return;
    }

    const matchingSession = chatSessionsQuery.data.items.find((session) => session.id === storedSessionId);
    if (!matchingSession) {
      window.localStorage.removeItem(CURRENT_SESSION_STORAGE_KEY);
      hasAttemptedSessionRestoreRef.current = true;
      return;
    }

    const backendActiveSessionId = normalizeSessionId(chatSessionsQuery.data.active_session_id);
    if (storedSessionId === backendActiveSessionId || storedSessionId === activeChatSessionId) {
      hasAttemptedSessionRestoreRef.current = true;
      return;
    }
    if (restoringSessionIdRef.current === storedSessionId) {
      return;
    }

    restoringSessionIdRef.current = storedSessionId;
    void (async () => {
      try {
        const response = await activateChatSession(storedSessionId);
        applyChatSnapshot(response.chat);
        setComposerResetVersion((current) => current + 1);
        await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
        await queryClient.invalidateQueries({ queryKey: ["chat"] });
      } catch (error) {
        console.error("Failed to restore stored chat session", error);
        window.localStorage.removeItem(CURRENT_SESSION_STORAGE_KEY);
      } finally {
        hasAttemptedSessionRestoreRef.current = true;
        restoringSessionIdRef.current = null;
      }
    })();
  }, [
    activeChatSessionId,
    applyChatSnapshot,
    bootstrapQuery.isSuccess,
    chatSessionsQuery.data,
    chatSessionsQuery.isSuccess,
    queryClient,
  ]);

  const uploadMutation = useMutation({
    mutationFn: uploadArchive,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      queryClient.invalidateQueries({ queryKey: ["processes"] });
    },
  });

  const createProjectMutation = useMutation({
    mutationFn: ({ name, rootPath }: { name: string; rootPath: string }) =>
      createChatProject({
        name,
        root_path: rootPath.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });

  const createGroupMutation = useMutation({
    mutationFn: (label: string) => createGroup(label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
  });

  const renameGroupMutation = useMutation({
    mutationFn: ({ pk, label }: { pk: number; label: string }) => renameGroup(pk, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
  });

  const deleteGroupsMutation = useMutation({
    mutationFn: async (pks: number[]) => {
      const normalizedPks = [...new Set(pks.filter((pk) => Number.isFinite(pk) && pk > 0))];
      const results = await Promise.allSettled(normalizedPks.map((pk) => deleteGroup(pk)));
      const deletedPks: number[] = [];
      const failed: Array<{ pk: number; message: string }> = [];
      results.forEach((result, index) => {
        const pk = normalizedPks[index];
        if (result.status === "fulfilled") {
          deletedPks.push(pk);
          return;
        }
        const reason = result.reason;
        failed.push({
          pk,
          message: reason instanceof Error ? reason.message : `Failed to delete group #${pk}.`,
        });
      });
      return { deletedPks, failed };
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      queryClient.invalidateQueries({ queryKey: ["processes"] });
    },
  });

  const addNodesToGroupMutation = useMutation({
    mutationFn: ({ groupPk, nodePks }: { groupPk: number; nodePks: number[] }) => addNodesToGroup(groupPk, nodePks),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      queryClient.invalidateQueries({ queryKey: ["processes"] });
    },
  });

  const softDeleteNodeMutation = useMutation({
    mutationFn: (pk: number) => softDeleteNode(pk, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["processes"] });
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
  });

  const processes = processesQuery.data?.items ?? bootstrapQuery.data?.processes ?? [];
  const groups = normalizeGroups(groupsQuery.data?.items ?? bootstrapQuery.data?.groups ?? []);
  const polledLogsVersion = logsQuery.data?.version ?? bootstrapQuery.data?.logs.version ?? -1;
  const polledLogs = logsQuery.data?.lines ?? bootstrapQuery.data?.logs.lines ?? [];
  const logs =
    streamedLogs && streamedLogs.version >= polledLogsVersion
      ? streamedLogs.lines
      : polledLogs;
  const chatMessages = messages;
  const models = bootstrapQuery.data?.models ?? [];
  const isReady = bootstrapQuery.isSuccess;
  const contextNodeIds = useMemo(() => contextNodes.map((node) => node.pk), [contextNodes]);
  const isChatBusy = isChatLoading;
  const hasPendingAgentStep = useMemo(
    () => hasActiveAiidaAgentStep(chatMessages, activeTurnId, isChatBusy),
    [activeTurnId, chatMessages, isChatBusy],
  );

  useEffect(() => {
    setActiveWorkspaceProjectId((current) => {
      if (current && chatProjects.some((project) => project.id === current)) {
        return current;
      }
      return activeProjectId ?? null;
    });
  }, [activeProjectId, chatProjects]);
  const sessionSnapshotPayload = useMemo(
    () =>
      buildChatSessionSnapshotPayload({
        contextNodes,
        pinnedNodes,
        selectedGroup,
        selectedModel,
        sessionEnvironment,
        sessionEnvironmentAuto,
        promptOverride,
        sessionParameters,
      }),
    [
      contextNodes,
      pinnedNodes,
      promptOverride,
      selectedGroup,
      selectedModel,
      sessionEnvironment,
      sessionEnvironmentAuto,
      sessionParameters,
    ],
  );
  const sessionSnapshotSignature = useMemo(
    () => JSON.stringify(sessionSnapshotPayload),
    [sessionSnapshotPayload],
  );

  useEffect(() => {
    if (!bootstrapQuery.isSuccess || !activeChatSessionId) {
      return;
    }
    if (sessionSnapshotSignature === lastPersistedSnapshotRef.current) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      lastPersistedSnapshotRef.current = sessionSnapshotSignature;
      void updateChatSession(activeChatSessionId, { snapshot: sessionSnapshotPayload }).catch((error) => {
        console.error("Failed to persist chat session snapshot", error);
        lastPersistedSnapshotRef.current = "";
      });
    }, 220);

    return () => window.clearTimeout(timeoutId);
  }, [activeChatSessionId, bootstrapQuery.isSuccess, sessionSnapshotPayload, sessionSnapshotSignature]);

  const appendContextNode = useCallback((node: FocusNode) => {
    setContextNodes((current) => {
      if (current.some((existing) => existing.pk === node.pk)) {
        return current;
      }
      return [...current, node];
    });
  }, []);

  const handleAddContextNode = useCallback((process: ProcessItem) => {
    appendContextNode({
      pk: process.pk,
      label: process.label,
      formula: process.formula ?? null,
      node_type: process.node_type,
    });
  }, [appendContextNode]);

  const handleRemoveContextNode = useCallback((pk: number) => {
    setContextNodes((current) => current.filter((node) => node.pk !== pk));
  }, []);

  const handleRestoreContextNodes = useCallback((nodes: FocusNode[]) => {
    setContextNodes(dedupeFocusNodes(nodes));
  }, []);

  const handlePinNode = useCallback((node: FocusNode) => {
    setPinnedNodes((current) => dedupeFocusNodes([...current, node]));
  }, []);

  const handleUnpinNode = useCallback((pk: number) => {
    setPinnedNodes((current) => current.filter((node) => node.pk !== pk));
  }, []);

  const stopActiveChatTurn = useCallback(async () => {
    if (!isChatBusy) {
      return;
    }

    sendAbortControllerRef.current?.abort();
    sendAbortControllerRef.current = null;
    requestInFlightRef.current = false;
    setIsChatLoading(false);
    const turnIdToStop = activeTurnId;
    setActiveTurnId(null);

    try {
      await stopChat(turnIdToStop ?? undefined);
    } catch (error) {
      if (!isAbortError(error)) {
        console.error("Failed to stop chat request", error);
      }
    } finally {
      await queryClient.invalidateQueries({ queryKey: ["chat"] });
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    }
  }, [activeTurnId, isChatBusy, queryClient]);

  const handleCreateChatSession = useCallback(async (projectId?: string) => {
    if (hasPendingAgentStep) {
      const confirmed = window.confirm(
        "An AiiDA agent step is still running. Starting a new conversation will stop it, archive the current session, and open a fresh one. Continue?",
      );
      if (!confirmed) {
        return;
      }
    }

    if (isChatBusy) {
      await stopActiveChatTurn();
    }

    window.localStorage.removeItem(CURRENT_SESSION_STORAGE_KEY);
    const response = await createChatSession({
      archive_session_id: activeChatSessionId ?? undefined,
      project_id: projectId,
    });
    applyChatSnapshot(response.chat);
    setActiveWorkspaceProjectId(response.session?.project_id ?? response.active_project_id ?? null);
    setComposerResetVersion((current) => current + 1);
    setSidebarView("explorer");
    await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    await queryClient.invalidateQueries({ queryKey: ["chat"] });
  }, [activeChatSessionId, applyChatSnapshot, hasPendingAgentStep, isChatBusy, queryClient, stopActiveChatTurn]);

  const handleActivateChatSession = useCallback(
    async (sessionId: string) => {
      if (isChatBusy || !sessionId || sessionId === activeChatSessionId) {
        return;
      }
      const response = await activateChatSession(sessionId);
      applyChatSnapshot(response.chat);
      setActiveWorkspaceProjectId(response.session?.project_id ?? response.active_project_id ?? null);
      setComposerResetVersion((current) => current + 1);
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      await queryClient.invalidateQueries({ queryKey: ["chat"] });
    },
    [activeChatSessionId, applyChatSnapshot, isChatBusy, queryClient],
  );

  const handleRenameChatSession = useCallback(
    async (sessionId: string, title: string) => {
      if (!sessionId) {
        return;
      }
      const response = await updateChatSessionTitle(sessionId, { title });
      applyChatSnapshot(response.chat);
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    [applyChatSnapshot, queryClient],
  );

  const handleCreateProject = useCallback(
    async ({ name, rootPath }: { name: string; rootPath: string }) => {
      const response = await createProjectMutation.mutateAsync({ name, rootPath });
      await handleCreateChatSession(response.project.id);
      setSidebarView("history");
    },
    [createProjectMutation, handleCreateChatSession],
  );

  const handleDeleteChatItems = useCallback(
    async ({ projectIds, sessionIds }: { projectIds?: string[]; sessionIds?: string[] }) => {
      const normalizedProjectIds = [...new Set((projectIds ?? []).map((value) => value.trim()).filter(Boolean))];
      const normalizedSessionIds = [...new Set((sessionIds ?? []).map((value) => value.trim()).filter(Boolean))];
      if (normalizedProjectIds.length === 0 && normalizedSessionIds.length === 0) {
        return;
      }

      const projectSet = new Set(normalizedProjectIds);
      const sessionSet = new Set(normalizedSessionIds);
      const targetedSessionIds = new Set(sessionSet);
      chatSessions.forEach((session) => {
        if (projectSet.has(session.project_id)) {
          targetedSessionIds.add(session.id);
        }
      });

      const deletingActiveSession =
        Boolean(activeChatSessionId && targetedSessionIds.has(activeChatSessionId)) ||
        Boolean(activeProjectId && projectSet.has(activeProjectId));

      if (deletingActiveSession && hasPendingAgentStep) {
        const confirmed = window.confirm(
          "Deleting the active project/session will stop the running AiiDA agent step. Continue?",
        );
        if (!confirmed) {
          return;
        }
      }

      if (deletingActiveSession && isChatBusy) {
        await stopActiveChatTurn();
      }

      const summaryParts: string[] = [];
      if (normalizedProjectIds.length > 0) {
        summaryParts.push(`${normalizedProjectIds.length} project${normalizedProjectIds.length === 1 ? "" : "s"}`);
      }
      if (normalizedSessionIds.length > 0) {
        summaryParts.push(`${normalizedSessionIds.length} session${normalizedSessionIds.length === 1 ? "" : "s"}`);
      }
      const confirmMessage =
        normalizedProjectIds.length > 0
          ? `Delete ${summaryParts.join(" and ")}? This will also delete all sessions inside the selected projects.`
          : `Delete ${summaryParts.join(" and ")}?`;
      if (!window.confirm(confirmMessage)) {
        return;
      }

      let response;
      if (normalizedProjectIds.length > 0 && normalizedSessionIds.length > 0) {
        response = await deleteChatItems({
          project_ids: normalizedProjectIds,
          session_ids: normalizedSessionIds,
        });
      } else if (normalizedProjectIds.length === 1 && normalizedSessionIds.length === 0) {
        response = await deleteChatProject(normalizedProjectIds[0]!);
      } else if (normalizedProjectIds.length === 0 && normalizedSessionIds.length === 1) {
        response = await deleteChatSession(normalizedSessionIds[0]!);
      } else if (normalizedProjectIds.length > 0) {
        response = await deleteChatItems({ project_ids: normalizedProjectIds });
      } else {
        response = await deleteChatItems({ session_ids: normalizedSessionIds });
      }

      applyChatSessionsSnapshot(response);
      applyChatSnapshot(response.chat);
      setActiveWorkspaceProjectId((current) => (current && !projectSet.has(current) ? current : null));
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      await queryClient.invalidateQueries({ queryKey: ["chat"] });
    },
    [
      activeChatSessionId,
      activeProjectId,
      applyChatSessionsSnapshot,
      applyChatSnapshot,
      chatSessions,
      hasPendingAgentStep,
      isChatBusy,
      queryClient,
      stopActiveChatTurn,
    ],
  );

  const handleOpenProjectWorkspace = useCallback(
    (projectId: string) => {
      if (!projectId) {
        return;
      }
      setActiveWorkspaceProjectId(projectId);
      setSidebarView("workspace");
    },
    [],
  );

  const handleOpenWorkspaceFile = useCallback((file: WorkspaceExplorerFileSelection) => {
    setActiveWorkspaceProjectId(file.projectId);
    setViewerFile(file);
    setActiveView("EDITOR");
  }, []);

  const closeViewer = useCallback(() => {
    setActiveView("CHAT");
  }, []);

  const handleOpenDetail = useCallback((pk: number) => {
    setActiveProcess({
      pk,
      label: `Process #${pk}`,
      state: "submitted",
      status_color: "running",
      node_type: "ProcessNode",
      process_state: null,
      formula: null,
    });
  }, []);

  useEffect(() => {
    if (!currentContextGroupLabel) {
      if (selectedGroup === GROUP_SELECTION_CURRENT_CONTEXT) {
        setSelectedGroup(GROUP_SELECTION_ALL);
      }
      return;
    }

    if (!selectedGroup) {
      setSelectedGroup(GROUP_SELECTION_CURRENT_CONTEXT);
      return;
    }

    if (selectedGroup === GROUP_SELECTION_ALL || selectedGroup === GROUP_SELECTION_CURRENT_CONTEXT) {
      return;
    }

    if (!groups.some((group) => group.label === selectedGroup)) {
      setSelectedGroup(GROUP_SELECTION_CURRENT_CONTEXT);
    }
  }, [currentContextGroupLabel, groups, selectedGroup]);

  useEffect(() => {
    if (pendingProcessLimit === null) {
      return;
    }
    if (!processesQuery.isFetching && !processesQuery.isPending) {
      setPendingProcessLimit(null);
    }
  }, [pendingProcessLimit, processesQuery.isFetching, processesQuery.isPending]);

  useEffect(() => {
    return () => {
      sendAbortControllerRef.current?.abort();
      sendAbortControllerRef.current = null;
      requestInFlightRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!isChatLoading || activeTurnId === null) {
      return;
    }
    if (isTurnFinalized(chatMessages, activeTurnId)) {
      setIsChatLoading(false);
      setActiveTurnId(null);
      requestInFlightRef.current = false;
      sendAbortControllerRef.current = null;
    }
  }, [activeTurnId, chatMessages, isChatLoading]);

  useEffect(() => {
    if (!isChatLoading) {
      return;
    }
    if (activeTurnId !== null || requestInFlightRef.current) {
      return;
    }
    setIsChatLoading(false);
  }, [activeTurnId, isChatLoading]);

  const loadingMessage = useMemo(() => {
    if (bootstrapQuery.isLoading) {
      return "Initializing dashboard...";
    }
    if (bootstrapQuery.isError) {
      return "Unable to connect to backend bridge.";
    }
    return "";
  }, [bootstrapQuery.isError, bootstrapQuery.isLoading]);

  const handleSendMessage = useCallback(
    async (text: string, options?: { resourceAttachments?: ResourceAttachment[] }) => {
      const intent = text.trim();
      const hasStaleBusyLock = isChatBusy && activeTurnId === null && !requestInFlightRef.current;
      if (hasStaleBusyLock) {
        setIsChatLoading(false);
      }
      if (!intent || (isChatBusy && !hasStaleBusyLock) || requestInFlightRef.current) {
        return;
      }
      const rawResourceAttachments = Array.isArray(options?.resourceAttachments) ? options.resourceAttachments : [];
      const resourceAttachmentMap = new Map<string, ResourceAttachment>();
      rawResourceAttachments.forEach((attachment) => {
        const kind = typeof attachment.kind === "string" ? attachment.kind.trim().toLowerCase() : "";
        const value = typeof attachment.value === "string" ? attachment.value.trim() : "";
        if (!value || (kind !== "computer" && kind !== "code" && kind !== "plugin")) {
          return;
        }
        const key = `${kind}:${value.toLowerCase()}`;
        if (resourceAttachmentMap.has(key)) {
          return;
        }
        resourceAttachmentMap.set(key, {
          kind,
          value,
          label: typeof attachment.label === "string" && attachment.label.trim() ? attachment.label.trim() : value,
          plugin:
            typeof attachment.plugin === "string" && attachment.plugin.trim() ? attachment.plugin.trim() : null,
          computerLabel:
            typeof attachment.computerLabel === "string" && attachment.computerLabel.trim()
              ? attachment.computerLabel.trim()
              : null,
          hostname:
            typeof attachment.hostname === "string" && attachment.hostname.trim() ? attachment.hostname.trim() : null,
        });
      });
      const resourceAttachments = [...resourceAttachmentMap.values()];
      const selectedContextNodes = dedupeFocusNodes([...pinnedNodes, ...contextNodes]);
      const contextPks = selectedContextNodes.map((node) => node.pk);
      const textReferencedPks = extractPkReferences(intent);
      const mergedContextPks = mergeUniquePks(contextPks, textReferencedPks);

      const controller = new AbortController();
      sendAbortControllerRef.current = controller;
      requestInFlightRef.current = true;
      setIsChatLoading(true);
      setActiveTurnId(null);

      try {
        const payload: SendChatRequest = {
          intent,
          model_name: selectedModel || undefined,
          context_node_ids: mergedContextPks,
          context_pks: mergedContextPks,
          metadata: {
            selected_group: selectedGroupLabel,
            session_environment: sessionEnvironment,
            session_environment_auto: sessionEnvironmentAuto,
            prompt_override: promptOverride.trim() || null,
            context_pks: mergedContextPks,
            context_node_pks: mergedContextPks,
            context_nodes: selectedContextNodes.map((node) => ({
              pk: node.pk,
              label: node.label,
              formula: node.formula,
              node_type: node.node_type,
            })),
            pinned_nodes: pinnedNodes.map((node) => ({
              pk: node.pk,
              label: node.label,
              formula: node.formula,
              node_type: node.node_type,
            })),
            session_parameters: normalizeSessionParameters(sessionParameters),
            resource_attachments: resourceAttachments.map((attachment) => ({
              kind: attachment.kind,
              value: attachment.value,
              label: attachment.label,
              plugin: attachment.plugin,
              computer_label: attachment.computerLabel,
              hostname: attachment.hostname,
            })),
          },
        };
        const { turn_id: turnId } = await sendChat(payload, controller.signal);
        setActiveTurnId(turnId);
        setContextNodes([]);
        setComposerResetVersion((current) => current + 1);
        void queryClient.invalidateQueries({ queryKey: ["chat"] });
        void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      } catch (error) {
        setIsChatLoading(false);
        setActiveTurnId(null);
        if (!isAbortError(error)) {
          console.error("Chat request failed", error);
        }
      } finally {
        sendAbortControllerRef.current = null;
        requestInFlightRef.current = false;
      }
    },
    [
      activeTurnId,
      contextNodes,
      isChatBusy,
      pinnedNodes,
      promptOverride,
      queryClient,
      selectedGroupLabel,
      selectedModel,
      sessionEnvironment,
      sessionEnvironmentAuto,
      sessionParameters,
    ],
  );

  const handleStopResponse = useCallback(() => {
    void stopActiveChatTurn();
  }, [stopActiveChatTurn]);

  const handleSelectAllGroups = useCallback(() => {
    setSelectedGroup(GROUP_SELECTION_ALL);
  }, []);

  const handleSelectCurrentContext = useCallback(() => {
    setSelectedGroup(GROUP_SELECTION_CURRENT_CONTEXT);
  }, []);

  const handleSelectArchiveGroup = useCallback((groupLabel: string) => {
    setSelectedGroup(groupLabel);
  }, []);

  const handleCreateGroup = useCallback(async (label: string) => {
    await createGroupMutation.mutateAsync(label);
  }, [createGroupMutation]);

  const handleRenameGroup = useCallback(async (pk: number, label: string) => {
    await renameGroupMutation.mutateAsync({ pk, label });
  }, [renameGroupMutation]);

  const handleDeleteGroups = useCallback(async (pks: number[]) => {
    const normalizedPks = [...new Set(pks.filter((pk) => Number.isFinite(pk) && pk > 0))];
    if (normalizedPks.length === 0) {
      return;
    }
    const deletedGroups = groups.filter((group) => normalizedPks.includes(group.pk));
    const result = await deleteGroupsMutation.mutateAsync(normalizedPks);
    const deletedLabels = deletedGroups
      .filter((group) => result.deletedPks.includes(group.pk))
      .map((group) => group.label);
    if (deletedLabels.includes(selectedGroup)) {
      setSelectedGroup(currentContextGroupLabel ? GROUP_SELECTION_CURRENT_CONTEXT : GROUP_SELECTION_ALL);
    }
    if (result.failed.length > 0) {
      throw new Error(result.failed.map((entry) => entry.message).join("\n"));
    }
  }, [currentContextGroupLabel, deleteGroupsMutation, groups, selectedGroup]);

  const handleAssignNodesToGroup = useCallback(async (groupPk: number, nodePks: number[]) => {
    await addNodesToGroupMutation.mutateAsync({ groupPk, nodePks });
  }, [addNodesToGroupMutation]);

  const handleSoftDeleteNode = useCallback(async (pk: number) => {
    await softDeleteNodeMutation.mutateAsync(pk);
    setContextNodes((current) => current.filter((node) => node.pk !== pk));
  }, [softDeleteNodeMutation]);

  const handleExportGroup = useCallback(async (group: GroupItem) => {
    const payload = await exportGroup(group.pk);
    const blob = payload.blob;
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = payload.filename || `${group.label.replace(/[^\w.-]+/g, "_") || `group-${group.pk}`}.aiida`;
      anchor.click();
    } finally {
      URL.revokeObjectURL(url);
    }
  }, []);

  const handleConsultFailedProcess = useCallback((process: ProcessItem, diagnostics?: ProcessDiagnosticsResponse | null) => {
    const prompt = buildFailureConsultPrompt(process, diagnostics);
    void handleSendMessage(prompt);
  }, [handleSendMessage]);

  const handleCloneProcess = useCallback(async (process: ProcessItem) => {
    setIsCloneDraftLoading(true);
    try {
      const payload = await getProcessCloneDraft(process.pk);
      setCloneDraft(payload as SubmissionDraftPayload);
      setCloneTurnId(process.pk);
      setCloneModalState({ status: "idle", processPk: null, processPks: [], errorText: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to clone process #${process.pk}.`;
      window.alert(message);
    } finally {
      setIsCloneDraftLoading(false);
    }
  }, []);

  const handleCloseCloneModal = useCallback(() => {
    if (cloneModalState.status === "submitting") {
      return;
    }
    setCloneDraft(null);
    setCloneTurnId(null);
    setCloneModalState({ status: "idle", processPk: null, processPks: [], errorText: null });
  }, [cloneModalState.status]);

  const handleConfirmCloneDraft = useCallback(
    async (draftPayload: SubmissionSubmitDraft) => {
      if (!cloneDraft || cloneTurnId === null || cloneModalState.status !== "idle") {
        return;
      }
      setCloneModalState({ status: "submitting", processPk: null, processPks: [], errorText: null });
      try {
        const response = await submitPreviewDraft(draftPayload);
        const rawSubmitted = response.submitted_pks ?? response.process_pks ?? response.pk;
        const processPks = Array.isArray(rawSubmitted)
          ? rawSubmitted.map((value) => Number.parseInt(String(value), 10)).filter((value) => Number.isFinite(value) && value > 0)
          : (() => {
              const parsed = Number.parseInt(String(rawSubmitted ?? ""), 10);
              return Number.isFinite(parsed) && parsed > 0 ? [parsed] : [];
            })();
        setCloneModalState({
          status: "submitted",
          processPk: processPks[0] ?? null,
          processPks,
          errorText: null,
        });
        void queryClient.invalidateQueries({ queryKey: ["processes"] });
        void queryClient.invalidateQueries({ queryKey: ["groups"] });
      } catch (error) {
        const errorText = error instanceof Error ? error.message : "Failed to submit cloned workflow.";
        setCloneModalState({ status: "error", processPk: null, processPks: [], errorText });
      }
    },
    [cloneDraft, cloneModalState.status, cloneTurnId, queryClient],
  );

  const handleCancelCloneDraft = useCallback(async () => {
    if (cloneModalState.status !== "idle") {
      return;
    }
    setCloneModalState({ status: "cancelled", processPk: null, processPks: [], errorText: null });
    try {
      await cancelPendingSubmission();
    } catch (error) {
      console.error("Failed to clear pending submission", error);
    }
  }, [cloneModalState.status]);

  return (
    <main className="dashboard-shell h-screen overflow-hidden">
      <div className="flex h-full min-h-0 w-full flex-col xl:flex-row">
        <section className="flex h-full min-h-0 w-full shrink-0 overflow-hidden border-r border-zinc-200/80 bg-white lg:w-[360px] dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex h-full w-12 flex-col items-center justify-between border-r border-zinc-200/70 bg-zinc-50/85 px-1.5 py-3 dark:border-zinc-800/70 dark:bg-zinc-900/60">
            <div className="flex flex-col items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-9 w-9 rounded-xl text-zinc-500 hover:bg-white hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
                  sidebarView === "explorer" &&
                    "bg-white text-zinc-900 shadow-[0_10px_20px_-16px_rgba(15,23,42,0.45)] dark:bg-zinc-800 dark:text-zinc-100",
                )}
                onClick={() => setSidebarView("explorer")}
                aria-label="AiiDA Explorer"
              >
                <Database className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-9 w-9 rounded-xl text-zinc-500 hover:bg-white hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
                  sidebarView === "history" &&
                    "bg-white text-zinc-900 shadow-[0_10px_20px_-16px_rgba(15,23,42,0.45)] dark:bg-zinc-800 dark:text-zinc-100",
                )}
                onClick={() => setSidebarView("history")}
                aria-label="Chat History"
              >
                <History className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-9 w-9 rounded-xl text-zinc-500 hover:bg-white hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
                  sidebarView === "workspace" &&
                    "bg-white text-zinc-900 shadow-[0_10px_20px_-16px_rgba(15,23,42,0.45)] dark:bg-zinc-800 dark:text-zinc-100",
                )}
                onClick={() => {
                  setActiveWorkspaceProjectId((current) => current ?? activeProjectId ?? null);
                  setSidebarView("workspace");
                }}
                aria-label="Workspace Explorer"
              >
                <FolderOpen className="h-4 w-4" />
              </Button>
            </div>
            <div className="flex flex-col items-center">
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-xl text-zinc-500 hover:bg-white hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                onClick={() => setTheme((value) => (value === "dark" ? "light" : "dark"))}
                aria-label="Toggle color mode"
              >
                {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </Button>
            </div>
          </div>

          <div className="flex min-w-0 flex-1 flex-col bg-transparent px-2.5 py-0">
            {sidebarView === "explorer" ? (
              <Sidebar
                activeProject={activeSessionProject ?? null}
                processes={processes}
                groups={groups}
                selectedGroupLabel={selectedGroupLabel}
                isAllGroupsSelected={selectedGroup === GROUP_SELECTION_ALL || (!selectedGroup && !currentContextGroupLabel)}
                isCurrentContextSelected={selectedGroup === GROUP_SELECTION_CURRENT_CONTEXT}
                currentContextGroupLabel={currentContextGroupLabel}
                processLimit={processLimit}
                contextNodeIds={contextNodeIds}
                selectedProcess={activeProcess}
                isUpdatingProcessLimit={pendingProcessLimit !== null}
                onSelectAllGroups={handleSelectAllGroups}
                onSelectCurrentContext={handleSelectCurrentContext}
                onGroupChange={handleSelectArchiveGroup}
                nodeTypeFilter={nodeTypeFilter}
                onNodeTypeFilterChange={setNodeTypeFilter}
                onProcessLimitChange={(nextLimit) => {
                  if (nextLimit === processLimit) {
                    return;
                  }
                  setProcessLimit(nextLimit);
                  setPendingProcessLimit(nextLimit);
                }}
                onAddContextNode={handleAddContextNode}
                onOpenProcessDetail={setActiveProcess}
                onCreateGroup={handleCreateGroup}
                onRenameGroup={handleRenameGroup}
                onDeleteGroups={handleDeleteGroups}
                onAssignNodesToGroup={handleAssignNodesToGroup}
                onSoftDeleteNode={handleSoftDeleteNode}
                onExportGroup={handleExportGroup}
                onConsultFailedProcess={handleConsultFailedProcess}
                onCloneProcess={handleCloneProcess}
                onOpenProjectWorkspace={handleOpenProjectWorkspace}
              />
            ) : sidebarView === "history" ? (
              <HistorySidebar
                projects={chatProjects}
                sessions={chatSessions}
                activeProjectId={activeProjectId}
                activeSessionId={activeChatSessionId}
                isBusy={isChatBusy}
                onActivateSession={(sessionId) => {
                  void handleActivateChatSession(sessionId);
                }}
                onRenameSession={(sessionId, title) => {
                  void handleRenameChatSession(sessionId, title);
                }}
                onCreateProject={({ name, rootPath }) => {
                  void handleCreateProject({ name, rootPath });
                }}
                onDeleteItems={({ projectIds, sessionIds }) => {
                  void handleDeleteChatItems({ projectIds, sessionIds });
                }}
                onOpenProjectWorkspace={(projectId) => {
                  handleOpenProjectWorkspace(projectId);
                }}
              />
            ) : (
              <WorkspaceExplorerSidebar
                project={selectedWorkspaceProject}
                onOpenFile={handleOpenWorkspaceFile}
              />
            )}
          </div>
        </section>

        <MainWorkspace
          activeView={activeView}
          viewerFile={viewerFile}
          theme={theme}
          onCloseViewer={closeViewer}
          chatContent={
            isReady ? (
              <ChatPanel
                activeProject={activeSessionProject ?? null}
                messages={chatMessages}
                models={models}
                selectedModel={selectedModel}
                composerResetVersion={composerResetVersion}
                currentProjectName={activeChatSession?.project_label ?? null}
                currentSessionName={activeChatSession?.title ?? null}
                isLoading={isChatBusy}
                activeTurnId={activeTurnId}
                onNewConversation={() => {
                  void handleCreateChatSession();
                }}
                contextNodes={contextNodes}
                pinnedNodes={pinnedNodes}
                sessionEnvironment={sessionEnvironment}
                sessionEnvironmentAuto={sessionEnvironmentAuto}
                promptOverride={promptOverride}
                sessionParameters={sessionParameters}
                selectedGroup={resolveSelectedGroupDisplayLabel(selectedGroup, currentContextGroupLabel) ?? selectedGroupLabel ?? undefined}
                onSendMessage={handleSendMessage}
                onStopResponse={handleStopResponse}
                onModelChange={setSelectedModel}
                onAttachFile={(file) => uploadMutation.mutate(file)}
                onAddContextNode={appendContextNode}
                onPinNode={handlePinNode}
                onUnpinNode={handleUnpinNode}
                onRemoveContextNode={handleRemoveContextNode}
                onOpenDetail={handleOpenDetail}
                onRestoreContextNodes={handleRestoreContextNodes}
                onSessionEnvironmentChange={setSessionEnvironment}
                onSessionEnvironmentAutoChange={setSessionEnvironmentAuto}
                onPromptOverrideChange={setPromptOverride}
                onSessionParametersChange={setSessionParameters}
              />
            ) : (
              <section className="flex flex-1 items-center justify-center rounded-2xl border border-white/40 bg-white/70 shadow-glass backdrop-blur dark:border-white/10 dark:bg-zinc-950/40">
                <p className="text-sm text-zinc-600 dark:text-zinc-300">{loadingMessage}</p>
              </section>
            )
          }
          terminalContent={<RuntimeTerminal lines={logs} />}
        />
      </div>
      <ProcessDetailDrawer
        process={activeProcess}
        onClose={() => setActiveProcess(null)}
        onAddContextNode={appendContextNode}
        onExplainFailure={handleConsultFailedProcess}
      />
      <SubmissionModal
        open={Boolean(cloneDraft) && cloneTurnId !== null}
        turnId={cloneTurnId}
        submissionDraft={cloneDraft}
        state={cloneModalState}
        isBusy={isCloneDraftLoading || cloneModalState.status === "submitting"}
        onToggleExpanded={undefined}
        onClose={handleCloseCloneModal}
        onConfirm={(draftPayload) => {
          void handleConfirmCloneDraft(draftPayload);
        }}
        onCancel={() => {
          void handleCancelCloneDraft();
        }}
        onOpenDetail={handleOpenDetail}
      />
    </main>
  );
}
