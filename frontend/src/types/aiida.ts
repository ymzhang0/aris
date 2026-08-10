export type ProcessItem = {
  pk: number;
  label: string;
  state: string;
  status_color: "running" | "success" | "error" | "idle" | string;
  node_type: string;
  process_label?: string | null;
  process_state: string | null;
  formula: string | null;
  preview_info?: Record<string, unknown> | null;
};

export type GroupItem = {
  pk: number;
  label: string;
  count: number;
  type_string?: string | null;
};

export type FocusNode = {
  pk: number;
  label: string;
  formula: string | null;
  node_type: string;
};

export type SessionParameter = {
  key: string;
  value: string;
};

export type ResourceAttachmentKind = "computer" | "code" | "plugin";

export type ResourceAttachment = {
  kind: ResourceAttachmentKind;
  value: string;
  label: string;
  plugin: string | null;
  computerLabel: string | null;
  hostname: string | null;
};

export type ChatMessage = {
  role: "user" | "assistant" | string;
  text: string;
  status: "thinking" | "done" | "error" | string;
  turn_id: number;
  payload?: Record<string, unknown> | null;
};

export type ChatSnapshot = {
  version: number;
  session_id: string | null;
  messages: ChatMessage[];
  snapshot: ChatSessionSnapshot;
};

export type ChatSessionSnapshot = {
  context_nodes: FocusNode[];
  pinned_nodes: FocusNode[];
  selected_group: string | null;
  selected_model: string | null;
  session_environment: string | null;
  session_environment_auto: boolean;
  environment_active_python_path?: string | null;
  prompt_override: string | null;
  session_parameters: SessionParameter[];
};

export type ChatSessionSummary = {
  id: string;
  project_id: string;
  title: string;
  auto_title: boolean;
  title_state: "idle" | "pending" | "ready" | "failed" | string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  tags: string[];
  project_label: string | null;
  project_group_label?: string | null;
  session_group_label?: string | null;
  workspace_path: string;
  node_count: number;
  preview: string;
  message_count: number;
  snapshot: ChatSessionSnapshot;
};

export type ChatSessionBatchProgressItem = {
  pk: number;
  label: string;
  process_label?: string | null;
  state: string;
  exit_status: number | null;
  status: "success" | "running" | "queued" | "failed" | string;
};

export type ChatSessionBatchProgress = {
  session_id: string;
  label: string;
  group_label: string;
  total: number;
  done: number;
  percent: number;
  success: number;
  running: number;
  queued: number;
  failed: number;
  items: ChatSessionBatchProgressItem[];
};

export type ChatSessionDetail = ChatSessionSummary & {
  version: number;
  messages: ChatMessage[];
};

export type ChatSessionsResponse = {
  version: number;
  active_session_id: string | null;
  active_project_id: string | null;
  projects: ChatProject[];
  items: ChatSessionSummary[];
};

export type ChatSessionMutationResponse = {
  version: number;
  active_session_id: string | null;
  active_project_id: string | null;
  projects: ChatProject[];
  items: ChatSessionSummary[];
  session: ChatSessionDetail;
  chat: ChatSnapshot;
};

export type ChatDeleteResponse = {
  version: number;
  active_session_id: string | null;
  active_project_id: string | null;
  projects: ChatProject[];
  items: ChatSessionSummary[];
  chat: ChatSnapshot;
  deleted_project_ids: string[];
  deleted_session_ids: string[];
};

export type ChatProject = {
  id: string;
  name: string;
  group_uuid?: string | null;
  group_label?: string | null;
  root_path: string;
  created_at: string;
  updated_at: string;
  session_count: number;
  active: boolean;
  environment_mode_default?: "worker-default" | "project-auto" | string;
  python_interpreter_path?: string | null;
  aiida_profile?: string | null;
};

export type ChatProjectMutationResponse = {
  project: ChatProject;
  active_project_id: string | null;
  projects: ChatProject[];
};

export type ProjectPythonPackage = {
  name: string;
  version: string;
  editable: boolean;
  source?: string | null;
};

export type ProjectPackagesResponse = {
  project_id: string;
  configured: boolean;
  python_interpreter_path: string | null;
  suggested_python_interpreter_path: string | null;
  aiida_profile: string | null;
  runtime_ready: boolean;
  packages: ProjectPythonPackage[];
};

export type WorkspaceEntry = {
  name: string;
  path: string;
  relative_path: string;
  is_dir: boolean;
  size: number | null;
  updated_at: string;
};

export type ChatSessionWorkspaceResponse = {
  session_id: string;
  project_id: string;
  project_name: string;
  workspace_path: string;
  relative_path: string;
  entries: WorkspaceEntry[];
};

export type ChatProjectWorkspaceResponse = {
  project_id: string;
  project_name: string;
  workspace_path: string;
  relative_path: string;
  entries: WorkspaceEntry[];
};

export type ChatProjectFileWriteRequest = {
  relative_path: string;
  content: string;
  overwrite?: boolean;
};

export type ChatProjectFileWriteResponse = {
  project_id: string;
  project_name: string;
  workspace_path: string;
  path: string;
  relative_path: string;
  directory_path: string;
  filename: string;
  size: number;
  updated_at: string;
  created: boolean;
};

export type ChatProjectFileContentResponse = {
  project_id: string;
  project_name: string;
  workspace_path: string;
  path: string;
  relative_path: string;
  content: string;
};

export type ChatProjectFileExecuteResponse = {
  project_id: string;
  project_name: string;
  workspace_path: string;
  path: string;
  relative_path: string;
  status: "completed" | "failed" | string;
  output: string;
};

export type LogsSnapshot = {
  version: number;
  lines: string[];
};

export type BootstrapResponse = {
  processes: ProcessItem[];
  groups: GroupItem[];
  chat: ChatSnapshot;
  logs: LogsSnapshot;
  models: string[];
  selected_model: string;
  quick_prompts: Array<{ label: string; prompt: string }>;
  authorization: {
    protocol_version: "1";
    subject: string;
    roles: string[];
    policy_provider: string;
    permissions: Record<string, boolean>;
  };
};

export type SpecializationAction = {
  id: string;
  label: string;
  prompt: string;
  description: string | null;
  icon: string | null;
  command: string | null;
  section: string;
  placements: string[];
  specialization: string;
  specialization_label: string;
  accent: string;
  variant: "general" | "specialized";
  enabled: boolean;
  disabled_reason: string | null;
};

export type SpecializationMenuSection = {
  id: string;
  label: string;
  items: SpecializationAction[];
};

export type SpecializationSummary = {
  name: string;
  label: string;
  description: string | null;
  accent: string;
  variant: "general" | "specialized";
  active: boolean;
  reasons: string[];
};

export type ActiveSpecializationsResponse = {
  chips: SpecializationAction[];
  slash_menu: SpecializationMenuSection[];
  active_specializations: SpecializationSummary[];
  inactive_specializations: SpecializationSummary[];
  environment: {
    selected: string | null;
    resolved: string;
    auto_switch: boolean;
  };
  context: {
    context_node_ids: number[];
    context_node_types: string[];
    project_tags: string[];
    resource_plugins: string[];
    worker_plugins: string[];
    worker_plugins_available: boolean;
  };
};

export type ProcessesResponse = {
  items: ProcessItem[];
};

export type GroupsResponse = {
  items: GroupItem[];
};

export type UploadArchiveResponse = {
  status: string;
  profile_name: string;
  stored_path: string;
};

export type LogsResponse = LogsSnapshot;

export type ChatResponse = ChatSnapshot;

export type SendChatRequest = {
  intent: string;
  session_id?: string;
  model_name?: string;
  context_archive?: string | null;
  context_node_ids?: number[];
  context_pks?: number[];
  metadata?: Record<string, unknown>;
};

export type InterpreterInfo = {
  python_path: string | null;
  workspace_path: string | null;
};

export type EnvironmentPluginGroups = {
  calculations: string[];
  workflows: string[];
  data: string[];
};

export type EnvironmentInspectionCode = {
  label?: string | null;
  default_plugin?: string | null;
  computer_label?: string | null;
  [key: string]: unknown;
};

export type EnvironmentInspectionComputer = {
  label?: string | null;
  hostname?: string | null;
  description?: string | null;
  is_enabled?: boolean | null;
  [key: string]: unknown;
};

export type EnvironmentInspectionResponse = {
  success: boolean;
  mode: "project" | "worker-default";
  source: string;
  python_path: string | null;
  workspace_path: string | null;
  python_interpreter_path?: string | null;
  python_version?: string | null;
  aiida_core_version?: string | null;
  profile?: string | null;
  plugins: string[];
  plugin_groups?: Partial<EnvironmentPluginGroups> | null;
  codes: EnvironmentInspectionCode[];
  computers: EnvironmentInspectionComputer[];
  errors?: Array<Record<string, unknown>>;
  cached?: boolean;
  cached_at?: string | null;
};

export type SubmissionResponse = Record<string, unknown>;

export type NodeHoverMetadataResponse = {
  pk: number;
  formula: string | null;
  spacegroup: string | null;
  node_type: string;
};

export type NodeScriptResponse = {
  pk: number;
  node_type: string;
  language: string;
  script: string;
};

export type GroupMutationResponse = {
  item: GroupItem | null;
};

export type GroupAssignNodesResponse = {
  group: GroupItem | null;
  added: number[];
  missing: number[];
};

export type GroupDeleteResponse = {
  status: string;
  pk: number;
  label?: string;
  count?: number;
};

export type GroupExportDownload = {
  blob: Blob;
  filename: string;
  contentType: string;
};

export type SoftDeleteNodeResponse = {
  pk: number;
  soft_deleted: boolean;
};

export type WorkerStatusResponse = {
  status: "online" | "offline";
  url: string;
  environment: string;
  transport?: "stdio" | "http";
  worker_mode?: string | null;
  profile: string;
  daemon_status: boolean;
  resources: BridgeSystemCounts;
  plugins: string[];
};

export type BridgeProfileItem = {
  name: string;
  is_default: boolean;
  is_active: boolean;
};

export type WorkerProfilesResponse = {
  current_profile: string | null;
  default_profile: string | null;
  profiles: BridgeProfileItem[];
};

export type WorkerSwitchProfileResponse = {
  status: string;
  current_profile: string | null;
};

export type BridgeSystemCounts = {
  computers: number;
  codes: number;
  workchains: number;
};

export type BridgeSystemInfoResponse = {
  profile: string;
  counts: BridgeSystemCounts;
  daemon_status: boolean;
};

export type WorkerComputerResource = {
  label: string;
  hostname: string;
  description: string | null;
};

export type WorkerCodeResource = {
  label: string;
  default_plugin: string | null;
  computer_label: string | null;
};

export type WorkerResourcesResponse = {
  computers: WorkerComputerResource[];
  codes: WorkerCodeResource[];
};

export type ProcessTreeNode = {
  pk: number;
  process_label: string;
  state: string;
  exit_status: number | null;
  inputs?: Record<string, ProcessNodeLink>;
  outputs?: Record<string, ProcessNodeLink>;
  direct_inputs?: Record<string, ProcessNodeLink>;
  direct_outputs?: Record<string, ProcessNodeLink>;
  children: Record<string, ProcessTreeNode>;
};

export type ProcessNodeLinkPreview = {
  formula?: string | null;
  atom_count?: number | null;
  remote_path?: string | null;
  computer_name?: string | null;
  computer?: string | null;
  path?: string | null;
  filenames?: string[];
  files?: string[];
  file_count?: number | null;
  mesh?: number[];
  offset?: number[];
  mode?: string | null;
  num_points?: number | null;
  has_labels?: boolean | null;
  num_kpoints?: number | null;
  num_bands?: number | null;
  arrays?: Array<{ name?: string; label?: string; shape?: number[] | null }>;
  x_label?: string | null;
  x_length?: number | null;
  y_labels?: string[];
  y_arrays?: Array<{ label: string; length: number | null }>;
  summary?: string | null;
  value?: string | number | boolean | null;
  count?: number | null;
  keys?: string[] | null;
};

export type ProcessNodeLink = {
  link_label: string;
  node_type: string;
  pk: number;
  label?: string | null;
  preview_info?: ProcessNodeLinkPreview | null;
};

export type ProcessLogsResponse = {
  pk: number;
  lines: string[];
  reports: string[];
  stderr_excerpt: string | null;
  text: string;
};

export type ProcessWorkgraphNode = {
  id: string;
  label: string;
  identifier: string;
  task_type: string;
  state: string;
  position?: number[] | null;
  children: string[];
  inputs: string[];
  outputs: string[];
  incoming: string[];
  outgoing: string[];
  process_pk: number | null;
  process_uuid: string | null;
  process_label: string | null;
  process_node_type: string | null;
  process_state: string | null;
  process_exit_status: number | null;
};

export type ProcessWorkgraphEdge = {
  id: string;
  source: string;
  target: string;
  source_socket: string | null;
  target_socket: string | null;
  label: string | null;
};

export type ProcessWorkgraphResponse = {
  pk: number;
  label: string;
  state: string;
  name: string;
  roots: string[];
  topological_order: string[];
  levels: string[][];
  nodes: ProcessWorkgraphNode[];
  edges: ProcessWorkgraphEdge[];
};

export type ProcessDetailResponse = {
  summary?: {
    pk?: number;
    uuid?: string;
    type?: string;
    node_type?: string;
    full_type?: string;
    label?: string;
    state?: string;
    process_label?: string;
    exit_status?: number | null;
    ctime?: string | null;
    preview_info?: ProcessNodeLinkPreview | null;
  };
  inputs?: Record<string, ProcessNodeLink>;
  outputs?: Record<string, ProcessNodeLink>;
  direct_inputs?: Record<string, ProcessNodeLink>;
  direct_outputs?: Record<string, ProcessNodeLink>;
  workchain?: {
    provenance_tree?: ProcessTreeNode;
  };
  logs?: ProcessLogsResponse;
  calculation?: Record<string, unknown>;
};

export type ComputeHealthQueueSnapshot = {
  running: number;
  pending: number;
  queued: number;
  total: number;
  congested: boolean;
  threshold: number;
};

export type ComputeHealthEstimate = {
  available: boolean;
  duration_seconds: number | null;
  display: string | null;
  num_machines: number | null;
  sample_size: number;
  basis: string | null;
  matched_process_label: string | null;
};

export type ComputeHealthResponse = {
  available: boolean;
  source: string;
  computer_label: string | null;
  scheduler_type: string | null;
  warning_message: string | null;
  queue: ComputeHealthQueueSnapshot;
  estimate: ComputeHealthEstimate;
  reference_process_pk: number | null;
};

export type ProcessDiagnosticsExcerpt = {
  source: string;
  filename: string | null;
  line_count: number;
  text: string | null;
};

export type ProcessDiagnosticsResponse = {
  available: boolean;
  process_pk: number;
  state: string | null;
  node_type: string | null;
  process_label: string | null;
  label: string | null;
  exit_status: number | null;
  exit_message: string | null;
  computer_label: string | null;
  is_calcjob: boolean;
  stdout_excerpt: ProcessDiagnosticsExcerpt;
  log_excerpt: ProcessDiagnosticsExcerpt;
  stderr_excerpt: string | null;
};

export type NodeFileListResponse = {
  pk: number;
  files: string[];
  source?: string | null;
};

export type NodeFileContentResponse = {
  pk: number;
  filename: string;
  content: string;
  source?: string | null;
};

export type BandsPlotPath = {
  length?: number | null;
  from?: string | null;
  to?: string | null;
  values?: number[][];
  x?: number[];
  two_band_types?: boolean | null;
};

export type BandsPlotData = {
  paths?: BandsPlotPath[];
  band_type_idx?: number[];
  tick_pos?: number[];
  tick_labels?: string[];
  legend_text?: string | null;
  legend_text2?: string | null;
  yaxis_label?: string | null;
  title?: string | null;
  x_min_lim?: number | null;
  x_max_lim?: number | null;
  y_min_lim?: number | null;
  y_max_lim?: number | null;
  plot_zero_axis?: boolean | null;
};

export type BandsPlotResponse = {
  pk: number;
  data: BandsPlotData;
};

export type InfrastructureComputerCode = {
  pk: number;
  label: string;
  description: string | null;
  default_calc_job_plugin: string | null;
};

export type InfrastructureComputer = {
  pk: number;
  label: string;
  hostname: string;
  description: string | null;
  scheduler_type: string;
  transport_type: string;
  is_enabled: boolean;
  codes: InfrastructureComputerCode[];
};

export type InfrastructureExportResponse = {
  kind: string;
  label: string;
  filename: string;
  format: string;
  content: string;
};

export type InfrastructureCapabilitiesResponse = {
  aiida_core_version: string;
  available_transports: string[];
  recommended_transport: string;
  supports_async_ssh: boolean;
  transport_auth_fields: Record<string, string[]>;
};

export type InfrastructureComputerFormData = {
  label?: string;
  hostname?: string;
  user?: string;
  username?: string;
  description?: string;
  transport_type?: string;
  scheduler_type?: string;
  shebang?: string;
  work_dir?: string;
  mpiprocs_per_machine?: number;
  mpirun_command?: string;
  default_memory_per_machine?: number | null;
  use_double_quotes?: boolean;
  prepend_text?: string;
  append_text?: string;
  port?: number | null;
  look_for_keys?: boolean | null;
  key_filename?: string;
  timeout?: number | null;
  allow_agent?: boolean | null;
  proxy_command?: string;
  proxy_jump?: string;
  compress?: boolean | null;
  gss_auth?: boolean | null;
  gss_kex?: boolean | null;
  gss_deleg_creds?: boolean | null;
  gss_host?: string;
  load_system_host_keys?: boolean | null;
  key_policy?: string;
  safe_interval?: number | null;
  use_login_shell?: boolean;
  host?: string;
  max_io_allowed?: number | null;
  authentication_script?: string;
  backend?: string;
};

export type InfrastructureSetupPayload = {
  computer_label: string;
  hostname: string;
  user?: string;
  username?: string;
  computer_description?: string;
  transport_type: string;
  scheduler_type: string;
  shebang?: string;
  work_dir?: string;
  mpiprocs_per_machine?: number;
  mpirun_command?: string;
  default_memory_per_machine?: number | null;
  use_double_quotes?: boolean;
  prepend_text?: string;
  append_text?: string;
  port?: number | null;
  look_for_keys?: boolean | null;
  key_filename?: string;
  timeout?: number | null;
  allow_agent?: boolean | null;
  proxy_command?: string;
  proxy_jump?: string;
  compress?: boolean | null;
  gss_auth?: boolean | null;
  gss_kex?: boolean | null;
  gss_deleg_creds?: boolean | null;
  gss_host?: string;
  load_system_host_keys?: boolean | null;
  key_policy?: string;
  safe_interval?: number | null;
  use_login_shell?: boolean;
  host?: string;
  max_io_allowed?: number | null;
  authentication_script?: string;
  backend?: string;
  code_label?: string;
  code_description?: string;
  default_calc_job_plugin?: string;
  remote_abspath?: string;
  code_prepend_text?: string;
  code_append_text?: string;
};

export type ParseInfrastructureResponse = {
  status: string;
  data: {
    type: "computer" | "code" | "both";
    preset_matched?: boolean;
    preset_domain?: string;
    computer?: InfrastructureComputerFormData;
    code?: {
      label?: string;
      description?: string;
      default_calc_job_plugin?: string;
      remote_abspath?: string;
      prepend_text?: string;
      append_text?: string;
    };
  };
};

export type UserInfoResponse = {
  first_name: string;
  last_name: string;
  email: string;
  institution: string;
};

export type ProfileSetupRequest = {
  profile_name: string;
  first_name: string;
  last_name: string;
  email: string;
  institution: string;
  filepath: string;
  backend: string;
  set_as_default: boolean;
};

export type ImportDataResponse = {
  status: string;
  pk: number;
  uuid: string;
  type: string;
};
