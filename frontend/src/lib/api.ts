import axios from "axios";

import type {
  BridgeProfilesResponse,
  BridgeResourcesResponse,
  BridgeStatusResponse,
  BridgeSwitchProfileResponse,
  BootstrapResponse,
  BandsPlotResponse,
  ChatProjectMutationResponse,
  ChatProjectWorkspaceResponse,
  ChatDeleteResponse,
  ChatProjectFileContentResponse,
  ChatProjectFileExecuteResponse,
  ChatProjectFileWriteRequest,
  ChatProjectFileWriteResponse,
  ChatSessionBatchProgress,
  ChatSessionMutationResponse,
  ChatSessionWorkspaceResponse,
  ChatSessionsResponse,
  ComputeHealthResponse,
  GroupAssignNodesResponse,
  GroupDeleteResponse,
  GroupExportDownload,
  GroupMutationResponse,
  GroupsResponse,
  ActiveSpecializationsResponse,
  InfrastructureComputer,
  InfrastructureCapabilitiesResponse,
  InfrastructureSetupPayload,
  InfrastructureExportResponse,
  LogsResponse,
  NodeHoverMetadataResponse,
  NodeScriptResponse,
  NodeFileContentResponse,
  NodeFileListResponse,
  ParseInfrastructureResponse,
  ProcessDetailResponse,
  ProcessDiagnosticsResponse,
  ProcessLogsResponse,
  ProcessWorkgraphResponse,
  ProcessesResponse,
  SendChatRequest,
  SoftDeleteNodeResponse,
  SubmissionResponse,
  InterpreterInfo,
  UploadArchiveResponse,
  UserInfoResponse,
  ProfileSetupRequest,
  ImportDataResponse,
} from "@/types/aiida";
import { buildProjectLayoutSystemPrompt, buildProjectScriptSaveTarget } from "@/lib/FileManager";
import { getEnvironmentState } from "@/store/EnvironmentStore";

export const API_BASE_URL = import.meta.env.DEV ? "http://localhost:8000" : "";
export const FRONTEND_API_PREFIX = "/api/aiida/frontend";
export const AIIDA_API_PREFIX = "/api/aiida";
const frontendBaseURL = `${API_BASE_URL}${FRONTEND_API_PREFIX}`;
const aiidaBaseURL = `${API_BASE_URL}${AIIDA_API_PREFIX}`;
const specializationsBaseURL = `${API_BASE_URL}/api/specializations`;
const sessionsBaseURL = `${API_BASE_URL}/api`;

function resolveHttpOrigin(): string {
  if (import.meta.env.DEV) {
    return "http://localhost:8000";
  }
  if (typeof window === "undefined") {
    return "";
  }
  return `${window.location.protocol}//${window.location.host}`;
}

function resolveWsOrigin(): string {
  if (import.meta.env.DEV) {
    return "ws://localhost:8000";
  }
  if (typeof window === "undefined") {
    return "";
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

export function getFrontendStreamUrl(path: string): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${resolveHttpOrigin()}${cleanPath}`;
}

export function getTerminalWsUrl(path = "/api/terminal"): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${resolveWsOrigin()}${cleanPath}`;
}

export const LOGS_STREAM_URL = getFrontendStreamUrl(`${FRONTEND_API_PREFIX}/logs/stream`);
export const CHAT_STREAM_URL = getFrontendStreamUrl(`${FRONTEND_API_PREFIX}/chat/stream`);
export const PROCESS_EVENTS_URL = getFrontendStreamUrl(`${AIIDA_API_PREFIX}/process/events`);
export const GROUPS_STREAM_URL = getFrontendStreamUrl(`${FRONTEND_API_PREFIX}/groups/stream`);
export const PROCESSES_STREAM_URL = getFrontendStreamUrl(`${FRONTEND_API_PREFIX}/processes/stream`);
export const INFRASTRUCTURE_STREAM_URL = getFrontendStreamUrl(`${FRONTEND_API_PREFIX}/infrastructure/stream`);
export const TERMINAL_WS_URL = getTerminalWsUrl("/api/terminal");

export const frontendApi = axios.create({
  baseURL: frontendBaseURL,
  timeout: 15000,
});

const aiidaApi = axios.create({
  baseURL: aiidaBaseURL,
  timeout: 5000,
});

const specializationsApi = axios.create({
  baseURL: specializationsBaseURL,
  timeout: 8000,
});

export type SubmissionSubmitDraftPayload =
  | Record<string, unknown>
  | Array<Record<string, unknown>>;

export type SubmissionExecutionApprovalDecision = {
  protocol_version: "1";
  approval_id: string;
  action: "submission.execute";
  decision: "approved";
  scope: "single" | "batch";
  actor_type: "user";
  decided_at: string;
  resource_digest: string;
};

export type SubmissionCancellationDecision = {
  protocol_version: "1";
  approval_id: string;
  action: "submission.execute";
  decision: "rejected";
  scope: "pending";
  actor_type: "user";
  decided_at: string;
};

export type SubmissionApprovalDecision =
  | SubmissionExecutionApprovalDecision
  | SubmissionCancellationDecision;

export type SubmissionApprovalRequest = {
  protocol_version: "1";
  approval_id: string;
  action: "submission.execute";
  status: "pending";
  scope: "single" | "batch";
  resource_digest: string;
  created_at: string;
  summary?: string | null;
};

function createApprovalId(): string {
  const localId = `approval-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : localId;
}

function createSubmissionApprovalDecision(
  request: SubmissionApprovalRequest,
): SubmissionExecutionApprovalDecision {
  return {
    protocol_version: "1",
    approval_id: request.approval_id,
    action: "submission.execute",
    decision: "approved",
    scope: request.scope,
    actor_type: "user",
    decided_at: new Date().toISOString(),
    resource_digest: request.resource_digest,
  };
}

function createPendingCancellationDecision(): SubmissionCancellationDecision {
  return {
    protocol_version: "1",
    approval_id: createApprovalId(),
    action: "submission.execute",
    decision: "rejected",
    scope: "pending",
    actor_type: "user",
    decided_at: new Date().toISOString(),
  };
}

export type ProcessCloneDraftResponse = {
  submission_draft: Record<string, unknown>;
  approval_request: SubmissionApprovalRequest;
};

function basenamePath(value: string | null | undefined): string {
  const normalized = String(value || "").trim().replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || normalized;
}

function splitPromptBlocks(value: unknown): string[] {
  if (typeof value !== "string") {
    return [];
  }
  return value
    .split(/\n\s*\n+/)
    .map((block) => block.trim())
    .filter(Boolean);
}

function isAutoEnvironmentPromptBlock(block: string): boolean {
  const lowered = block.trim().toLowerCase();
  if (!lowered.includes("current environment is") || !lowered.includes("available aiida")) {
    return false;
  }
  return (
    lowered.includes("submission draft generation is supported") ||
    lowered.includes("standard project layout") ||
    lowered.includes("codes/<filename>.py")
  );
}

function stripAutoEnvironmentPrompt(value: unknown): string | undefined {
  const cleaned = splitPromptBlocks(value).filter((block) => !isAutoEnvironmentPromptBlock(block)).join("\n\n");
  return cleaned || undefined;
}

function mergePromptOverride(...values: Array<unknown>): string | undefined {
  const mergedBlocks: string[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    splitPromptBlocks(value).forEach((block) => {
      if (seen.has(block)) {
        return;
      }
      seen.add(block);
      mergedBlocks.push(block);
    });
  });
  return mergedBlocks.join("\n\n") || undefined;
}

function summarizePluginFamily(family: string, plugins: string[]): string {
  const uniquePlugins = [...new Set(plugins.map((plugin) => plugin.trim()).filter(Boolean))];
  if (uniquePlugins.length === 0) {
    return `${family}.*`;
  }

  const preferredQuantumespresso = [
    "quantumespresso.pw.base",
    "quantumespresso.pw.relax",
    "quantumespresso.pw.bands",
    "quantumespresso.ph.base",
    "quantumespresso.dos",
    "quantumespresso.pdos",
  ];
  const examples = family === "quantumespresso"
    ? preferredQuantumespresso.filter((plugin) => uniquePlugins.includes(plugin))
    : uniquePlugins.slice(0, 3);
  const extraCount = Math.max(0, uniquePlugins.length - examples.length);
  const detail = examples.length > 0 ? `: ${examples.join(", ")}` : "";
  const suffix = extraCount > 0 ? ` (+${extraCount} more)` : "";
  return `${family}.*${detail}${suffix}`;
}

function summarizeEnvironmentPlugins(plugins: string[]): string {
  const uniquePlugins = [...new Set(plugins.map((plugin) => plugin.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right));
  if (uniquePlugins.length === 0) {
    return "aiida-core only";
  }

  const nonCorePlugins = uniquePlugins.filter((plugin) => !plugin.startsWith("core."));
  if (nonCorePlugins.length === 0) {
    return "aiida-core only";
  }

  const families = new Map<string, string[]>();
  nonCorePlugins.forEach((plugin) => {
    const family = plugin.split(".")[0]?.trim() || plugin;
    const familyPlugins = families.get(family) ?? [];
    familyPlugins.push(plugin);
    families.set(family, familyPlugins);
  });

  const orderedFamilies = [...families.keys()].sort((left, right) => {
    if (left === right) {
      return 0;
    }
    if (left === "quantumespresso") {
      return -1;
    }
    if (right === "quantumespresso") {
      return 1;
    }
    return left.localeCompare(right);
  });

  const visibleFamilies = orderedFamilies.slice(0, 4).map((family) => summarizePluginFamily(family, families.get(family) ?? []));
  const hiddenCount = orderedFamilies.length - visibleFamilies.length;
  return hiddenCount > 0 ? `${visibleFamilies.join("; ")}; +${hiddenCount} more families` : visibleFamilies.join("; ");
}

function buildInterpreterInfo(): InterpreterInfo {
  const state = getEnvironmentState();
  return {
    python_path: state.useWorkerDefault ? null : state.pythonPath,
    workspace_path: state.currentProjectPath,
  };
}

function buildEnvironmentSystemPrompt(): string | null {
  const state = getEnvironmentState();
  const projectName = basenamePath(state.currentProjectPath) || (state.useWorkerDefault ? "worker-global" : "current-project");
  const pluginSummary = summarizeEnvironmentPlugins(state.availablePlugins);
  const modeLabel = state.useWorkerDefault ? "worker default interpreter" : "project interpreter";
  return `Context: Current environment is ${projectName}. Mode: ${modeLabel}. Available AiiDA plugins: ${pluginSummary}. Submission draft generation is supported in both worker-default and project-interpreter modes when the worker can validate the request. Please generate code compatible with these plugins. ${buildProjectLayoutSystemPrompt()}`;
}

function buildEnvironmentMetadata(): Record<string, unknown> {
  const state = getEnvironmentState();
  const interpreterInfo = buildInterpreterInfo();
  const inspection = state.inspection;
  const activePythonPath = (
    typeof inspection?.python_interpreter_path === "string" && inspection.python_interpreter_path.trim()
      ? inspection.python_interpreter_path.trim()
      : typeof inspection?.python_path === "string" && inspection.python_path.trim()
        ? inspection.python_path.trim()
        : interpreterInfo.python_path
  );
  return {
    interpreter_info: interpreterInfo,
    environment_mode: state.useWorkerDefault ? "worker-default" : "project",
    environment_status: state.inspectionStatus,
    environment_project_path: state.currentProjectPath,
    environment_python_path: interpreterInfo.python_path,
    environment_active_python_path: activePythonPath,
    environment_plugins: state.availablePlugins,
    environment_codes: state.availableCodes,
    environment_computers: state.availableComputers,
    environment_last_error: state.lastError,
  };
}

export async function getBootstrap(): Promise<BootstrapResponse> {
  const { data } = await frontendApi.get<BootstrapResponse>("/bootstrap");
  return data;
}

export async function getActiveSpecializations(params: {
  contextNodeIds?: number[];
  projectTags?: string[];
  resourcePlugins?: string[];
  selectedEnvironment?: string | null;
  autoSwitch?: boolean;
}): Promise<ActiveSpecializationsResponse> {
  const searchParams = new URLSearchParams();
  (params.contextNodeIds ?? []).forEach((value) => {
    searchParams.append("context_node_ids", String(value));
  });
  (params.projectTags ?? []).forEach((value) => {
    searchParams.append("project_tags", value);
  });
  (params.resourcePlugins ?? []).forEach((value) => {
    searchParams.append("resource_plugins", value);
  });
  if (params.selectedEnvironment?.trim()) {
    searchParams.append("selected_environment", params.selectedEnvironment.trim());
  }
  if (typeof params.autoSwitch === "boolean") {
    searchParams.append("auto_switch", String(params.autoSwitch));
  }

  const { data } = await specializationsApi.get<ActiveSpecializationsResponse>("/active", {
    params: searchParams,
  });
  return data;
}

export async function uploadArchive(file: File): Promise<UploadArchiveResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await frontendApi.post<UploadArchiveResponse>("/archives/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
  return data;
}

export async function getProcesses(
  limit = 15,
  groupLabel?: string,
  nodeType?: string,
  label?: string,
  processState?: string,
  rootOnly = true,
): Promise<ProcessesResponse> {
  const { data } = await frontendApi.get<ProcessesResponse>("/processes", {
    params: { limit, group_label: groupLabel, node_type: nodeType, label, process_state: processState, root_only: rootOnly },
  });
  return data;
}

export async function getNodeHoverMetadata(pk: number): Promise<NodeHoverMetadataResponse> {
  const { data } = await frontendApi.get<NodeHoverMetadataResponse>(`/nodes/${pk}/metadata`);
  return data;
}

export async function getNodeScript(pk: number): Promise<NodeScriptResponse> {
  const { data } = await frontendApi.get<NodeScriptResponse>(`/nodes/${pk}/script`);
  return data;
}

export async function getProcessCloneDraft(identifier: number | string): Promise<ProcessCloneDraftResponse> {
  const { data } = await frontendApi.get<ProcessCloneDraftResponse>(`/processes/${identifier}/clone-draft`);
  return data;
}

export async function getGroups(): Promise<GroupsResponse> {
  const { data } = await frontendApi.get<GroupsResponse>("/groups");
  return data;
}

export async function createGroup(label: string): Promise<GroupMutationResponse> {
  const { data } = await frontendApi.post<GroupMutationResponse>("/groups/create", { label });
  return data;
}

export async function renameGroup(pk: number, label: string): Promise<GroupMutationResponse> {
  const { data } = await frontendApi.put<GroupMutationResponse>(`/groups/${pk}/label`, { label });
  return data;
}

export async function deleteGroup(pk: number): Promise<GroupDeleteResponse> {
  const { data } = await frontendApi.delete<GroupDeleteResponse>(`/groups/${pk}`);
  return data;
}

export async function addNodesToGroup(pk: number, nodePks: number[]): Promise<GroupAssignNodesResponse> {
  const { data } = await frontendApi.post<GroupAssignNodesResponse>(`/groups/${pk}/nodes`, {
    node_pks: nodePks,
  });
  return data;
}

export async function removeNodeFromGroup(pk: number, nodePk: number): Promise<GroupMutationResponse> {
  const { data } = await frontendApi.delete<GroupMutationResponse>(`/groups/${pk}/nodes/${nodePk}`);
  return data;
}

function parseDownloadFilename(contentDisposition: string | undefined, fallback: string): string {
  const raw = contentDisposition?.trim() ?? "";
  if (!raw) {
    return fallback;
  }
  const utf8Match = raw.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]).trim() || fallback;
    } catch {
      return utf8Match[1].trim() || fallback;
    }
  }
  const simpleMatch = raw.match(/filename\s*=\s*"?([^"]+)"?/i);
  if (simpleMatch?.[1]) {
    return simpleMatch[1].trim() || fallback;
  }
  return fallback;
}

export async function exportGroup(pk: number): Promise<GroupExportDownload> {
  const response = await frontendApi.get<Blob>(`/groups/${pk}/export`, {
    responseType: "blob",
  });
  return {
    blob: response.data,
    filename: parseDownloadFilename(response.headers["content-disposition"], `group-${pk}.aiida`),
    contentType: response.headers["content-type"] ?? "application/octet-stream",
  };
}

export async function softDeleteNode(pk: number, deleted = true): Promise<SoftDeleteNodeResponse> {
  const { data } = await frontendApi.post<SoftDeleteNodeResponse>(`/nodes/${pk}/soft-delete`, {
    deleted,
  });
  return data;
}

export async function getLogs(limit = 240): Promise<LogsResponse> {
  const { data } = await frontendApi.get<LogsResponse>("/logs", {
    params: { limit },
  });
  return data;
}

export async function getChatSessions(): Promise<ChatSessionsResponse> {
  const { data } = await frontendApi.get<ChatSessionsResponse>("/chat/sessions");
  return data;
}

export async function getChatSessionBatchProgress(sessionId: string): Promise<ChatSessionBatchProgress | null> {
  try {
    const { data } = await frontendApi.get<{ item: ChatSessionBatchProgress | null }>(
      `/chat/sessions/${sessionId}/batch-progress`,
    );
    return data.item ?? null;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null;
    }
    throw error;
  }
}

export async function createChatProject(payload: {
  name: string;
  root_path?: string;
}): Promise<ChatProjectMutationResponse> {
  const { data } = await frontendApi.post<ChatProjectMutationResponse>("/chat/projects", payload);
  return data;
}

export async function createChatSession(payload?: {
  title?: string;
  snapshot?: Record<string, unknown>;
  archive_session_id?: string;
  project_id?: string;
}): Promise<ChatSessionMutationResponse> {
  const { data } = await frontendApi.post<ChatSessionMutationResponse>("/chat/sessions", payload ?? {});
  return data;
}

export async function activateChatSession(sessionId: string): Promise<ChatSessionMutationResponse> {
  const { data } = await frontendApi.post<ChatSessionMutationResponse>(`/chat/sessions/${sessionId}/activate`);
  return data;
}

export async function deleteChatSession(sessionId: string): Promise<ChatDeleteResponse> {
  const { data } = await frontendApi.delete<ChatDeleteResponse>(`/chat/sessions/${sessionId}`);
  return data;
}

export async function deleteChatProject(projectId: string): Promise<ChatDeleteResponse> {
  const { data } = await frontendApi.delete<ChatDeleteResponse>(`/chat/projects/${projectId}`);
  return data;
}

export async function deleteChatItems(payload: {
  project_ids?: string[];
  session_ids?: string[];
}): Promise<ChatDeleteResponse> {
  const { data } = await frontendApi.post<ChatDeleteResponse>("/chat/delete", payload);
  return data;
}

export async function updateChatSession(
  sessionId: string,
  payload: { title?: string | null; tags?: string[] | null; snapshot?: Record<string, unknown> | null },
): Promise<ChatSessionMutationResponse> {
  const { data } = await frontendApi.patch<ChatSessionMutationResponse>(`/chat/sessions/${sessionId}`, payload);
  return data;
}

export async function updateChatSessionTitle(
  sessionId: string,
  payload: { title?: string | null },
): Promise<ChatSessionMutationResponse> {
  const { data } = await axios.put<ChatSessionMutationResponse>(
    `${sessionsBaseURL}/sessions/${encodeURIComponent(sessionId)}/title`,
    payload,
    { timeout: 15000 },
  );
  return data;
}

export async function getChatSessionWorkspace(
  sessionId: string,
  relativePath?: string,
): Promise<ChatSessionWorkspaceResponse> {
  const { data } = await frontendApi.get<ChatSessionWorkspaceResponse>(`/chat/sessions/${sessionId}/workspace`, {
    params: relativePath ? { relative_path: relativePath } : undefined,
  });
  return data;
}

export async function getChatProjectWorkspace(
  projectId: string,
  relativePath?: string,
): Promise<ChatProjectWorkspaceResponse> {
  const { data } = await frontendApi.get<ChatProjectWorkspaceResponse>(`/chat/projects/${projectId}/workspace`, {
    params: relativePath ? { relative_path: relativePath } : undefined,
  });
  return data;
}

export async function saveChatProjectFile(
  projectId: string,
  payload: ChatProjectFileWriteRequest,
): Promise<ChatProjectFileWriteResponse> {
  const { data } = await frontendApi.post<ChatProjectFileWriteResponse>(`/chat/projects/${projectId}/files`, payload);
  return data;
}

export async function fetchFileContent(
  projectId: string,
  relativePath: string,
): Promise<ChatProjectFileContentResponse> {
  const { data } = await frontendApi.get<ChatProjectFileContentResponse>(`/chat/projects/${projectId}/files/content`, {
    params: { relative_path: relativePath },
  });
  return data;
}

export async function executeChatProjectFile(
  projectId: string,
  relativePath: string,
): Promise<ChatProjectFileExecuteResponse> {
  const { data } = await frontendApi.post<ChatProjectFileExecuteResponse>(`/chat/projects/${projectId}/execute`, {
    relative_path: relativePath,
  });
  return data;
}

export async function saveProjectScript(
  projectId: string,
  payload: {
    intent: string;
    content: string;
    filename?: string | null;
    overwrite?: boolean;
  },
): Promise<ChatProjectFileWriteResponse> {
  const target = buildProjectScriptSaveTarget({
    projectPath: getEnvironmentState().currentProjectPath,
    intent: payload.intent,
    filename: payload.filename,
  });
  return saveChatProjectFile(projectId, {
    relative_path: target.relativePath,
    content: payload.content,
    overwrite: payload.overwrite ?? true,
  });
}

export async function sendChat(
  payload: SendChatRequest,
  signal?: AbortSignal,
): Promise<{ turn_id: number }> {
  const payloadMetadata = payload.metadata && typeof payload.metadata === "object" && !Array.isArray(payload.metadata)
    ? payload.metadata
    : {};
  const environmentMetadata = buildEnvironmentMetadata();
  const environmentPrompt = buildEnvironmentSystemPrompt();
  const sessionPromptOverride = stripAutoEnvironmentPrompt(payloadMetadata.prompt_override);
  const promptOverride = mergePromptOverride(sessionPromptOverride, environmentPrompt);
  const metadata = {
    ...environmentMetadata,
    ...payloadMetadata,
    ...(sessionPromptOverride ? { session_prompt_override: sessionPromptOverride } : {}),
    ...(promptOverride ? { prompt_override: promptOverride } : {}),
  };
  const { data } = await frontendApi.post<{ turn_id: number }>("/chat", {
    ...payload,
    metadata,
  }, { signal });
  return data;
}

export async function stopChat(turnId?: number): Promise<{ status: string; turn_id: number | null }> {
  const { data } = await frontendApi.post<{ status: string; turn_id: number | null }>("/chat/stop", {
    turn_id: turnId,
  });
  return data;
}

export async function getProcessDetail(identifier: number | string): Promise<ProcessDetailResponse> {
  const { data } = await aiidaApi.get<ProcessDetailResponse>(`/process/${identifier}`);
  return data;
}

export async function getProcessLogs(identifier: number | string): Promise<ProcessLogsResponse> {
  const { data } = await aiidaApi.get<ProcessLogsResponse>(`/process/${identifier}/logs`);
  return data;
}

export async function getProcessWorkgraph(identifier: number | string): Promise<ProcessWorkgraphResponse> {
  const { data } = await aiidaApi.get<ProcessWorkgraphResponse>(`/process/${identifier}/workgraph`);
  return data;
}

export async function getComputeHealth(params?: {
  reference_process_pk?: number;
  computer_label?: string | null;
}): Promise<ComputeHealthResponse> {
  const { data } = await frontendApi.get<ComputeHealthResponse>("/compute-health", {
    params: {
      reference_process_pk: params?.reference_process_pk,
      computer_label: params?.computer_label ?? undefined,
    },
  });
  return data;
}

export async function getProcessDiagnostics(identifier: number | string): Promise<ProcessDiagnosticsResponse> {
  const { data } = await frontendApi.get<ProcessDiagnosticsResponse>(`/processes/${identifier}/diagnostics`);
  return data;
}

export async function getBandsPlotData(pk: number): Promise<BandsPlotResponse> {
  const { data } = await aiidaApi.get<BandsPlotResponse>(`/data/bands/${pk}`);
  return data;
}

export async function getRemoteFiles(pk: number): Promise<NodeFileListResponse> {
  const { data } = await aiidaApi.get<NodeFileListResponse>(`/data/remote/${pk}/files`);
  return data;
}

export async function getRemoteFileContent(pk: number, filename: string): Promise<NodeFileContentResponse> {
  const { data } = await aiidaApi.get<NodeFileContentResponse>(`/data/remote/${pk}/files/${encodeURIComponent(filename)}`);
  return data;
}

export async function getRepositoryFiles(
  pk: number,
  source: "folder" | "repository" = "folder",
): Promise<NodeFileListResponse> {
  const { data } = await aiidaApi.get<NodeFileListResponse>(`/data/repository/${pk}/files`, {
    params: { source },
  });
  return data;
}

export async function getRepositoryFileContent(
  pk: number,
  filename: string,
  source: "folder" | "repository" = "folder",
): Promise<NodeFileContentResponse> {
  const { data } = await aiidaApi.get<NodeFileContentResponse>(
    `/data/repository/${pk}/files/${encodeURIComponent(filename)}`,
    {
      params: { source },
    },
  );
  return data;
}

export async function submitPreviewDraft(
  draft: SubmissionSubmitDraftPayload,
  approvalRequest: SubmissionApprovalRequest,
): Promise<SubmissionResponse> {
  const isBatch = Array.isArray(draft);
  const expectedScope = isBatch ? "batch" : "single";
  if (approvalRequest.scope !== expectedScope) {
    throw new Error(
      `Submission approval scope must be ${expectedScope}.`,
    );
  }
  const endpoint = isBatch ? "/submission/submit_batch" : "/submission/submit";
  const { data } = await aiidaApi.post<SubmissionResponse>(endpoint, {
    draft,
    interpreter_info: buildInterpreterInfo(),
    metadata: buildEnvironmentMetadata(),
    approval: createSubmissionApprovalDecision(approvalRequest),
  });
  return data;
}

export async function cancelPendingSubmission(): Promise<{ status: string }> {
  const { data } = await frontendApi.post<{ status: string }>("/submission/pending/cancel", {
    approval: createPendingCancellationDecision(),
  });
  return data;
}

const DEFAULT_BRIDGE_PROFILES: BridgeProfilesResponse = {
  current_profile: null,
  default_profile: null,
  profiles: [],
};

const DEFAULT_BRIDGE_RESOURCES: BridgeResourcesResponse = {
  computers: [],
  codes: [],
};

export async function getBridgeStatus(): Promise<BridgeStatusResponse> {
  const { data } = await aiidaApi.get<BridgeStatusResponse>("/status");
  return data;
}

export async function getBridgeProfiles(): Promise<BridgeProfilesResponse> {
  try {
    const { data } = await aiidaApi.get<BridgeProfilesResponse>("/profiles");
    return data;
  } catch {
    return DEFAULT_BRIDGE_PROFILES;
  }
}

export async function getCurrentUserInfo(): Promise<UserInfoResponse> {
  const { data } = await aiidaApi.get<UserInfoResponse>("/management/profiles/current-user-info");
  return data;
}

export async function setupProfile(payload: ProfileSetupRequest): Promise<{ status: string; profile_name: string }> {
  const { data } = await aiidaApi.post<{ status: string; profile_name: string }>("/management/profiles/setup", payload);
  return data;
}

export async function switchBridgeProfile(profile: string): Promise<BridgeSwitchProfileResponse> {
  const { data } = await aiidaApi.post<BridgeSwitchProfileResponse>("/profiles/switch", { profile });
  return data;
}

export async function getBridgeResources(): Promise<BridgeResourcesResponse> {
  try {
    const { data } = await aiidaApi.get<BridgeResourcesResponse>("/resources");
    return data;
  } catch {
    return DEFAULT_BRIDGE_RESOURCES;
  }
}

export async function getInfrastructure(): Promise<InfrastructureComputer[]> {
  const { data } = await aiidaApi.get<InfrastructureComputer[]>("/management/infrastructure");
  return data;
}

export async function getInfrastructureCapabilities(): Promise<InfrastructureCapabilitiesResponse> {
  const { data } = await aiidaApi.get<InfrastructureCapabilitiesResponse>("/management/infrastructure/capabilities");
  return data;
}

export async function setupInfrastructure(config: InfrastructureSetupPayload): Promise<any> {
  const { data } = await aiidaApi.post("/management/infrastructure/setup", config);
  return data;
}

export async function exportComputerConfig(computerPk: number): Promise<InfrastructureExportResponse> {
  const { data } = await aiidaApi.get<InfrastructureExportResponse>(
    `/management/infrastructure/computer/pk/${computerPk}/export`,
  );
  return data;
}

export async function exportCodeConfig(codePk: number): Promise<InfrastructureExportResponse> {
  const { data } = await aiidaApi.get<InfrastructureExportResponse>(`/management/infrastructure/code/${codePk}/export`);
  return data;
}

export interface SSHHostDetails {
  alias: string;
  hostname?: string;
  username?: string;
  port?: number;
  proxy_jump?: string;
  proxy_command?: string;
  identity_file?: string;
}

export async function getSshHosts(): Promise<SSHHostDetails[]> {
  const { data } = await frontendApi.get<{ items: SSHHostDetails[] }>("/ssh-hosts");
  return data.items;
}

export async function parseInfrastructure(text: string, sshHostDetails?: SSHHostDetails | null): Promise<ParseInfrastructureResponse> {
  const { data } = await frontendApi.post<ParseInfrastructureResponse>("/parse-infrastructure", {
    text,
    ssh_host_details: sshHostDetails || null
  });
  return data;
}

export async function importData(
  dataType: string,
  file?: File | null,
  label?: string,
  description?: string,
  sourceType: "file" | "raw_text" = "file",
  rawText?: string
): Promise<ImportDataResponse> {
  const formData = new FormData();
  if (file) formData.append("file", file);
  if (label) formData.append("label", label);
  if (description) formData.append("description", description);
  formData.append("source_type", sourceType);
  if (rawText) formData.append("raw_text", rawText);

  const { data } = await aiidaApi.post<ImportDataResponse>(
    `/data/import/${dataType}`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );
  return data;
}
