from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from src.aris_core.schema.approval import ApprovalDecision


class FrontendChatRequest(BaseModel):
    intent: str = Field(..., min_length=1, max_length=12000)
    model_name: str | None = None
    context_archive: str | None = None
    context_node_ids: list[int] | None = None
    context_pks: list[int] | None = None
    metadata: dict[str, Any] | None = None


class FrontendStopChatRequest(BaseModel):
    turn_id: int | None = None


class FrontendChatSessionCreateRequest(BaseModel):
    title: str | None = None
    snapshot: dict[str, Any] | None = None
    archive_session_id: str | None = None
    project_id: str | None = None


class FrontendChatSessionUpdateRequest(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    snapshot: dict[str, Any] | None = None


class FrontendChatSessionTitleUpdateRequest(BaseModel):
    title: str | None = None


class FrontendChatProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    root_path: str | None = None


class FrontendChatProjectUpdateRequest(BaseModel):
    python_env: str | None = None


class FrontendChatProjectFileWriteRequest(BaseModel):
    relative_path: str = Field(..., min_length=1, max_length=512)
    content: str = Field(default="")
    overwrite: bool = True


class FrontendChatProjectFileWriteResponse(BaseModel):
    project_id: str
    project_name: str
    workspace_path: str
    path: str
    relative_path: str
    directory_path: str
    filename: str
    size: int
    updated_at: str
    created: bool = False


class FrontendChatProjectFileReadResponse(BaseModel):
    project_id: str
    project_name: str
    workspace_path: str
    path: str
    relative_path: str
    content: str = Field(default="")


class FrontendChatProjectFileExecuteRequest(BaseModel):
  relative_path: str = Field(..., min_length=1, max_length=512)


class FrontendChatProjectFileExecuteResponse(BaseModel):
    project_id: str
    project_name: str
    workspace_path: str
    path: str
    relative_path: str
    status: str = "completed"
    output: str = Field(default="")


class FrontendChatDeleteRequest(BaseModel):
    project_ids: list[str] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)


class InterpreterInfoPayload(BaseModel):
    python_path: str | None = None
    workspace_path: str | None = None


class SubmissionDraftRequest(BaseModel):
    draft: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    interpreter_info: InterpreterInfoPayload | None = None
    metadata: dict[str, Any] | None = None
    approval: ApprovalDecision


class SubmissionApprovalCancelRequest(BaseModel):
    approval: ApprovalDecision


class EnvironmentInspectRequest(BaseModel):
    python_path: str | None = None
    workspace_path: str | None = None
    use_worker_default: bool = False


class SystemCountsResponse(BaseModel):
    computers: int = 0
    codes: int = 0
    workchains: int = 0


class WorkerStatusResponse(BaseModel):
    status: Literal["online", "offline"]
    url: str
    environment: str
    transport: Literal["stdio"] = "stdio"
    worker_mode: str | None = None
    profile: str = "unknown"
    daemon_status: bool = False
    resources: SystemCountsResponse = Field(default_factory=SystemCountsResponse)
    plugins: list[str] = Field(default_factory=list)


class WorkerSystemInfoResponse(BaseModel):
    profile: str = "unknown"
    counts: SystemCountsResponse = Field(default_factory=SystemCountsResponse)
    daemon_status: bool = False


class ComputerResourceResponse(BaseModel):
    label: str
    hostname: str
    description: str | None = None


class CodeResourceResponse(BaseModel):
    label: str
    default_plugin: str | None = None
    computer_label: str | None = None


class WorkerResourcesResponse(BaseModel):
    computers: list[ComputerResourceResponse] = Field(default_factory=list)
    codes: list[CodeResourceResponse] = Field(default_factory=list)


class BridgeProfileResponse(BaseModel):
    name: str
    is_default: bool = False
    is_active: bool = False


class WorkerProfilesResponse(BaseModel):
    current_profile: str | None = None
    default_profile: str | None = None
    profiles: list[BridgeProfileResponse] = Field(default_factory=list)


class BridgeSwitchProfileRequest(BaseModel):
    profile: str = Field(..., min_length=1)


class WorkerSwitchProfileResponse(BaseModel):
    status: str = "switched"
    current_profile: str | None = None


class FrontendGroupCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)


class FrontendGroupRenameRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)


class FrontendGroupAssignNodesRequest(BaseModel):
    node_pks: list[int] = Field(default_factory=list)


class FrontendNodeSoftDeleteRequest(BaseModel):
    deleted: bool = True


class NodeHoverMetadataResponse(BaseModel):
    pk: int
    formula: str | None = None
    spacegroup: str | None = None
    node_type: str = "Unknown"


class NodeScriptResponse(BaseModel):
    pk: int
    node_type: str
    language: str = "python"
    script: str


class InfrastructureComputerCode(BaseModel):
    pk: int
    label: str
    description: str | None = None
    default_calc_job_plugin: str | None = None


class InfrastructureComputer(BaseModel):
    pk: int
    label: str
    hostname: str
    description: str | None = None
    scheduler_type: str
    transport_type: str
    is_enabled: bool
    codes: list[InfrastructureComputerCode] = Field(default_factory=list)


class InfrastructureExportResponse(BaseModel):
    kind: str
    label: str
    filename: str
    format: str = "yaml"
    content: str


class InfrastructureCapabilitiesResponse(BaseModel):
    aiida_core_version: str
    available_transports: list[str] = Field(default_factory=list)
    recommended_transport: str = "core.ssh"
    supports_async_ssh: bool = False
    transport_auth_fields: dict[str, list[str]] = Field(default_factory=dict)


class ComputeHealthQueueSnapshot(BaseModel):
    running: int = 0
    pending: int = 0
    queued: int = 0
    total: int = 0
    congested: bool = False
    threshold: int = 1000


class ComputeHealthEstimateResponse(BaseModel):
    available: bool = False
    duration_seconds: float | None = None
    display: str | None = None
    num_machines: int | None = None
    sample_size: int = 0
    basis: str | None = None
    matched_process_label: str | None = None


class ComputeHealthResponse(BaseModel):
    available: bool = False
    source: str = "unavailable"
    computer_label: str | None = None
    scheduler_type: str | None = None
    warning_message: str | None = None
    queue: ComputeHealthQueueSnapshot = Field(default_factory=ComputeHealthQueueSnapshot)
    estimate: ComputeHealthEstimateResponse = Field(default_factory=ComputeHealthEstimateResponse)
    reference_process_pk: int | None = None


class ProcessDiagnosticsExcerpt(BaseModel):
    source: str = "none"
    filename: str | None = None
    line_count: int = 0
    text: str | None = None


class ProcessDiagnosticsResponse(BaseModel):
    available: bool = False
    process_pk: int
    state: str | None = None
    node_type: str | None = None
    process_label: str | None = None
    label: str | None = None
    exit_status: int | None = None
    exit_message: str | None = None
    computer_label: str | None = None
    is_calcjob: bool = False
    stdout_excerpt: ProcessDiagnosticsExcerpt = Field(default_factory=ProcessDiagnosticsExcerpt)
    log_excerpt: ProcessDiagnosticsExcerpt = Field(
        default_factory=lambda: ProcessDiagnosticsExcerpt(source="logs")
    )
    stderr_excerpt: str | None = None


class ParseInfrastructureRequest(BaseModel):
    text: str = Field(...)
    ssh_host_details: dict[str, Any] | None = None
class UserInfoResponse(BaseModel):
    first_name: str
    last_name: str
    email: str
    institution: str


class ProfileSetupRequest(BaseModel):
    profile_name: str
    first_name: str
    last_name: str
    email: str
    institution: str
    filepath: str
    backend: str = "core.sqlite_dos"
    set_as_default: bool = True

class CodeSetupRequest(BaseModel):
    computer_label: str
    label: str
    description: str | None = None
    default_calc_job_plugin: str
    remote_abspath: str
    prepend_text: str | None = None
    append_text: str | None = None
    with_mpi: bool | None = True
    use_double_quotes: bool = False

class CodeDetailedResponse(BaseModel):
    pk: int
    label: str
    description: str | None = None
    default_calc_job_plugin: str
    remote_abspath: str
    prepend_text: str | None = None
    append_text: str | None = None
    with_mpi: bool | None
    use_double_quotes: bool
