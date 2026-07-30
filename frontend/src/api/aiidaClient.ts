import { aiidaApi, frontendApi, specializationsApi, buildInterpreterInfo, buildEnvironmentMetadata, createSubmissionApprovalDecision, createPendingCancellationDecision } from "@/lib/api";
import type { 
  ProcessCloneDraftResponse, 
  SubmissionSubmitDraftPayload, 
  SubmissionApprovalRequest, 
  SSHHostDetails 
} from "@/lib/api";
import type {
  ProcessesResponse,
  ProcessDetailResponse,
  ProcessDiagnosticsResponse,
  ProcessWorkgraphResponse,
  BandsPlotResponse,
  GroupsResponse,
  InfrastructureCapabilitiesResponse,
  
  ProfileSetupRequest,
  ProcessLogsResponse,
  UploadArchiveResponse,
  GroupDeleteResponse,
  SubmissionResponse,
  ImportDataResponse,
  ActiveSpecializationsResponse,
  BridgeStatusResponse,
  BridgeProfilesResponse,
  BridgeSwitchProfileResponse,
  BridgeResourcesResponse,
  BridgeComputerResource,
  InfrastructureComputer,
  InfrastructureSetupPayload,
  InfrastructureExportResponse,
  ParseInfrastructureResponse,
  UserInfoResponse
} from "@/types/aiida";

export const DEFAULT_BRIDGE_PROFILES: BridgeProfilesResponse = { current_profile: null, default_profile: null, profiles: [] };
export const DEFAULT_BRIDGE_RESOURCES: BridgeResourcesResponse = { computers: [], codes: [] };

export const aiidaClient = {
  async getProcesses(
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
  ,
  
    async getProcessLogs(identifier: number | string): Promise<ProcessLogsResponse> {
    const { data } = await aiidaApi.get<ProcessLogsResponse>(`/process/${identifier}/logs`);
    return data;
  }
  ,
  
    async getProcessDetail(identifier: number | string): Promise<ProcessDetailResponse> {
    const { data } = await aiidaApi.get<ProcessDetailResponse>(`/process/${identifier}`);
    return data;
  }
  ,
  
    async getProcessDiagnostics(identifier: number | string): Promise<ProcessDiagnosticsResponse> {
    const { data } = await frontendApi.get<ProcessDiagnosticsResponse>(`/processes/${identifier}/diagnostics`);
    return data;
  }
  ,
  
    async getProcessWorkgraph(identifier: number | string): Promise<ProcessWorkgraphResponse> {
    const { data } = await aiidaApi.get<ProcessWorkgraphResponse>(`/process/${identifier}/workgraph`);
    return data;
  }
  ,
  
    async getProcessCloneDraft(identifier: number | string): Promise<ProcessCloneDraftResponse> {
    const { data } = await frontendApi.get<ProcessCloneDraftResponse>(`/processes/${identifier}/clone-draft`);
    return data;
  }
  ,
  
    async getGroups(): Promise<GroupsResponse> {
    const { data } = await frontendApi.get<GroupsResponse>("/groups");
    return data;
  }
  ,
  
    async uploadArchive(file: File): Promise<UploadArchiveResponse> {
    const formData = new FormData();
    formData.append("file", file);
  
    const { data } = await frontendApi.post<UploadArchiveResponse>("/archives/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return data;
  }
  ,
  
    async deleteGroup(pk: number): Promise<GroupDeleteResponse> {
    const { data } = await frontendApi.delete<GroupDeleteResponse>(`/groups/${pk}`);
    return data;
  }
  ,
  
    async submitPreviewDraft(
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
  ,
  
    async importData(
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
  ,
  
    async getActiveSpecializations(params: {
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
  ,
  
    async cancelPendingSubmission(): Promise<{ status: string }> {
    const { data } = await frontendApi.post<{ status: string }>("/submission/pending/cancel", {
      approval: createPendingCancellationDecision(),
    });
    return data;
  },
  async getBridgeStatus(): Promise<BridgeStatusResponse> {
    const { data } = await aiidaApi.get<BridgeStatusResponse>("/status");
    return data;
  }
  ,
  
    async getBridgeProfiles(): Promise<BridgeProfilesResponse> {
    try {
      const { data } = await aiidaApi.get<BridgeProfilesResponse>("/profiles");
      return data;
    } catch {
      return DEFAULT_BRIDGE_PROFILES;
    }
  }
  ,
  
    async switchBridgeProfile(profile: string): Promise<BridgeSwitchProfileResponse> {
    const { data } = await aiidaApi.post<BridgeSwitchProfileResponse>("/profiles/switch", { profile });
    return data;
  }
  ,
  
    async getBridgeResources(): Promise<BridgeResourcesResponse> {
    try {
      const { data } = await aiidaApi.get<BridgeResourcesResponse>("/resources");
      return data;
    } catch {
      return DEFAULT_BRIDGE_RESOURCES;
    }
  }
  ,
  
    async getInfrastructure(): Promise<InfrastructureComputer[]> {
    const { data } = await aiidaApi.get<InfrastructureComputer[]>("/management/infrastructure");
    return data;
  }
  ,
  
    async getInfrastructureCapabilities(): Promise<InfrastructureCapabilitiesResponse> {
    const { data } = await aiidaApi.get<InfrastructureCapabilitiesResponse>("/management/infrastructure/capabilities");
    return data;
  }
  ,
  
    async setupInfrastructure(config: InfrastructureSetupPayload): Promise<any> {
    const { data } = await aiidaApi.post("/management/infrastructure/setup", config);
    return data;
  }
  ,
  
    async exportComputerConfig(computerPk: number): Promise<InfrastructureExportResponse> {
    const { data } = await aiidaApi.get<InfrastructureExportResponse>(
      `/management/infrastructure/computer/pk/${computerPk}/export`,
    );
    return data;
  }
  ,
  
    async exportCodeConfig(codePk: number): Promise<InfrastructureExportResponse> {
    const { data } = await aiidaApi.get<InfrastructureExportResponse>(`/management/infrastructure/code/${codePk}/export`);
    return data;
  }
  ,
  
    async getSshHosts(): Promise<SSHHostDetails[]> {
    const { data } = await frontendApi.get<{ items: SSHHostDetails[] }>("/ssh-hosts");
    return data.items;
  }
  ,
  
    async parseInfrastructure(text: string, sshHostDetails?: SSHHostDetails | null): Promise<ParseInfrastructureResponse> {
    const { data } = await frontendApi.post<ParseInfrastructureResponse>("/parse-infrastructure", {
      text,
      ssh_host_details: sshHostDetails || null
    });
    return data;
  }
  ,
  
    async getCurrentUserInfo(): Promise<UserInfoResponse> {
    const { data } = await aiidaApi.get<UserInfoResponse>("/management/profiles/current-user-info");
    return data;
  }
  ,
  
    async setupProfile(payload: ProfileSetupRequest): Promise<{ status: string; profile_name: string }> {
    const { data } = await aiidaApi.post<{ status: string; profile_name: string }>("/management/profiles/setup", payload);
    return data;
  }
  
};
