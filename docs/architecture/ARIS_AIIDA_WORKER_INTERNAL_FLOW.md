# ARIS and aiida-worker internal flow

This document describes the implementation that exists on `main` at commit
`3d77acc`. It is a code map, not a target-state proposal.

The canonical editable overview is
[`diagrams/aris-aiida-worker-internals.mmd`](./diagrams/aris-aiida-worker-internals.mmd).
The compact pre-rendered version is
[`diagrams/aris-aiida-worker-internals.svg`](./diagrams/aris-aiida-worker-internals.svg).
Solid arrows are active runtime paths. Dashed arrows are optional, development,
or prepared-but-not-default paths.

## System overview

```mermaid
flowchart LR
    USER["User"] --> SURFACE{"Application surface"}
    SURFACE --> BROWSER["Browser"]
    SURFACE --> MAC["ARIS.app<br/>AppKit + WKWebView"]

    BROWSER --> REACT["Shared React frontend"]
    MAC --> REACT

    REACT -->|"REST"| BFF["ARIS FastAPI BFF<br/>127.0.0.1:8000"]
    BFF -->|"AG-UI over data-only SSE"| REACT
    BFF --> CHAT["Chat/session/approval<br/>application services"]
    CHAT --> RUNTIME["AgentRuntime protocol"]
    RUNTIME --> GEMINI["PydanticAI + Gemini"]
    GEMINI --> TOOLS["AiiDA researcher tools"]
    TOOLS -->|"current path: HTTP"| CAP["AiiDAWorkerClient / capability"]
    BFF -->|"deterministic UI commands"| CAP
    CAP -->|"HTTP bridge"| WORKER["aiida-worker FastAPI<br/>127.0.0.1:8001"]
    GEMINI -->|"submit_validated_workflow / run_aiida_code_script<br/>remaining direct execution path"| WORKER
    WORKER --> AIIDA["AiiDA profile, ORM,<br/>engine, daemon and repository"]
    AIIDA --> REMOTE["local/SSH computer<br/>and scheduler"]

    MCP["FastMCP facade<br/>inspect + preview only"] --> CAP
    MCP_CLIENT["External/future MCP client"] -.-> MCP
    GEMINI -. "not currently an MCP client" .-> MCP

    CHAT --> ARIS_STORE["ARIS JSON sessions<br/>and project workspace"]
    AIIDA --> AIIDA_STORE["AiiDA database<br/>and object repository"]
```

The two persistence areas are intentionally separate:

- ARIS owns conversations, projects, UI/application state, generated files and
  the approval workflow.
- `aiida-worker` owns access to AiiDA profiles, nodes, groups, provenance,
  computers, codes and process execution.

The macOS application is a native launcher and WebKit shell, not a second
frontend implementation. Production browser and desktop surfaces both load the
same React build served by ARIS on port 8000. Development mode swaps only the
frontend origin for Vite on port 5173.

## Process and repository boundaries

| Boundary | Repository / environment | Responsibility | Important entry points |
|---|---|---|---|
| Native shell | `aris`, system Objective-C toolchain | Start services, host the shared frontend in `WKWebView` | `desktop/macos/main.m`, `scripts/aris-local.sh` |
| UI | `aris/frontend`, Node build environment | Layout, user interaction, state projection, explicit approval decision | `frontend/src/App.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/ag-ui.ts` |
| ARIS host | `aris`, ARIS `.venv` | FastAPI BFF, agent orchestration, sessions, policy, AG-UI, payload presentation | `src/app_api.py`, `src/aris_apps/aiida/router.py` |
| Agent adapter | `aris`, ARIS `.venv` | Provider-neutral runtime contract and current Gemini implementation | `src/aris_core/agent/runtime.py`, `src/aris_apps/aiida/agent/runtime.py` |
| Capability facade | `aris`, ARIS `.venv` | Stable AiiDA application port, HTTP adapter, optional MCP facade | `capabilities.py`, `client.py`, `mcp_facade.py` |
| Execution worker | `aiida-worker`, worker `uv` environment | Deterministic AiiDA REST API and selected-interpreter subprocess execution | `main.py`, `routers/`, `core/` |
| Scientific runtime | active AiiDA profile and compute environment | ORM, provenance, engine/daemon, transports, scheduler jobs and repositories | AiiDA configuration, storage and remote computers |

PM2 starts ARIS and `aiida-worker` as separate processes. This is why the ARIS
Python environment and the calculation/plugin environment do not have to be the
same environment.

## Application startup

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as ARIS.app
    participant Launcher as scripts/aris-local.sh
    participant PM2
    participant Worker as aiida-worker :8001
    participant API as aris-api :8000
    participant Web as Shared React frontend

    User->>App: Open ARIS
    App->>Launcher: start
    Launcher->>PM2: start core
    par Worker process
        PM2->>Worker: uv run uvicorn main:app
        Launcher->>Worker: poll GET /status
    and ARIS process
        PM2->>API: ARIS .venv/bin/python app_api.py
        API->>API: load settings + JSONMemory
        API->>API: load AiiDA app manifest
        API->>API: build PydanticAIGeminiRuntime + AiiDADeps
        Launcher->>API: poll health and SPA URL
    end
    Launcher-->>App: services ready
    App->>API: GET /?desktop=1
    API-->>App: frontend/dist/index.html + assets
    App->>Web: render in WKWebView
    Web->>API: frontend bootstrap and state requests
    API->>Worker: status/resources/profile requests
    Worker-->>API: deterministic worker snapshot
    API-->>Web: UI-oriented bootstrap payload
```

Closing the app window does not stop PM2 services. That is deliberate: AiiDA
workflows and the daemon must be able to continue after the UI closes.

## Chat turn and state synchronization

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as React chat panel
    participant Router as ARIS frontend router
    participant Chat as chat/service.py
    participant Repo as Session repository
    participant Machine as ChatTurnStateMachine
    participant Runtime as AgentRuntime
    participant Agent as PydanticAI researcher
    participant Worker as aiida-worker
    participant Stream as AG-UI state stream

    UI->>Stream: GET /frontend/chat/stream
    Stream-->>UI: RUN_STARTED
    Stream-->>UI: STATE_SNAPSHOT(chat + sessions)

    User->>UI: Send intent + selected context node PKs
    UI->>Router: POST /frontend/chat
    Router->>Chat: start_chat_turn(...)
    Chat->>Repo: ensure session, append user + queued assistant
    Chat->>Machine: create state=queued
    Chat-->>Router: turn_id
    Router-->>UI: 202-style queued payload

    Chat->>Machine: queued -> running
    Chat->>Runtime: AgentRunRequest(prompt, deps, model, metadata)
    Runtime->>Agent: run with current Gemini model

    loop Agent tool calls
        Agent->>Worker: HTTP through researcher tools and AiiDAWorkerClient
        Worker-->>Agent: profiles/nodes/processes/spec/preview/data
        Chat->>Repo: update step history and tool-call status
        Stream-->>UI: atomic STATE_SNAPSHOT
    end

    alt Provider temporarily unavailable
        Runtime-->>Machine: retryable unavailable error
        Machine->>Machine: running -> retry_wait
        Stream-->>UI: snapshot with wait and attempt count
        Machine->>Machine: retry_wait -> running
        Machine->>Runtime: retry with exponential backoff
    else Cancelled
        UI->>Router: POST /frontend/chat/stop
        Router->>Chat: cancel task
        Chat->>Machine: active -> cancelled
        Chat->>Repo: persist cancelled message state
    else Model returns structured output
        Runtime-->>Chat: AgentRunResult(ARISResponse)
        Chat->>Machine: running -> processing
        Chat->>Chat: normalize task_mode and submission payload
        Chat->>Repo: persist final assistant message
        Chat->>Machine: processing -> completed
        Stream-->>UI: final STATE_SNAPSHOT
    else Unrecoverable error
        Chat->>Machine: active -> recovering -> failed
        Chat->>Repo: persist failure_kind and recovery state
        Stream-->>UI: failure STATE_SNAPSHOT
    end
```

`POST /frontend/chat` does not hold the HTTP request open for model completion.
It queues an `asyncio.Task`, returns the `turn_id`, and lets the AG-UI stream
project the authoritative server state into React.

The state machine accepts only these transitions:

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running
    queued --> recovering
    queued --> cancelled
    running --> retry_wait: provider unavailable
    retry_wait --> running: retry budget remains
    running --> processing: model output returned
    running --> recovering: error
    processing --> completed
    processing --> recovering: normalization/persistence error
    recovering --> failed
    queued --> cancelled
    running --> cancelled
    retry_wait --> cancelled
    processing --> cancelled
    recovering --> cancelled
    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

## Protocol-first preview and approval flow

The normal React submission path does not let the AI control UI topology
through keywords. It returns a validated `ARISResponse`:

- `task_mode="none"`: no runnable preview.
- `task_mode="single"`: exactly one runnable preview.
- `task_mode="batch"`: multi-structure, parameter-grid or high-throughput
  preview.
- A runnable mode must carry either a structured `submission_request` or a
  ready `data_payload.submission_draft`.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Agent
    participant Preview as SubmissionPreviewService
    participant Capability as AiiDACapability
    participant Worker as aiida-worker
    participant UI as React submission modal
    participant Gate as ARIS approval + policy gate
    participant AiiDA

    Agent-->>Preview: ARISResponse(task_mode, submission_request/data_payload)
    alt submission_request needs preparation
        Preview->>Capability: build_submission_draft(request)
        Capability->>Worker: POST /submission/draft-builder
        Worker->>Worker: resolve interpreter + WorkChain spec + builder
        Worker-->>Capability: structured draft
        Preview->>Capability: validate_submission_draft(draft)
        Capability->>Worker: POST /submission/validate
        Worker-->>Preview: validation + recovery plan
    end
    Preview->>Preview: normalize preview for single/batch UI
    Preview->>Preview: SHA-256 digest exact execution resource
    Preview-->>UI: submission_draft + ApprovalRequest(id, scope, digest)
    User->>UI: Review/edit and explicitly click submit
    UI->>Gate: draft + ApprovalDecision(id, approved, scope, digest)
    Gate->>Gate: require permission
    Gate->>Gate: require approved decision
    Gate->>Gate: recompute digest and compare exact draft
    alt Gate rejects
        Gate-->>UI: 4xx/409 and no worker submission
    else Single approval
        Gate->>Worker: POST /submission/submit
        Worker->>AiiDA: validate builder and engine.submit
        AiiDA-->>Worker: submitted process PK
        Worker-->>UI: normalized submitted result
    else Batch approval
        Gate->>Worker: submit with batch topology
        Worker->>Worker: product/zip expansion and max_jobs guard
        loop Each expanded request
            Worker->>AiiDA: validate and submit
        end
        Worker-->>UI: submitted_pks + per-item failures
    end
```

If the UI changes the draft after the server created the request, the digest no
longer matches and the approval is invalid. A fresh approval must be generated
for the changed resource.

### Current approval-boundary exception

The typed gate above is authoritative for the React submission and clone
dialogs, but it is not yet the only execution path in the repository.
`aiida_researcher` still registers:

- `submit_validated_workflow`, which reads `aiida_pending_submission` from the
  dependency registry or global `JSONMemory` and calls worker
  `/submission/submit` through `agent/tools.py`.
- `run_aiida_code_script`, which calls worker `/management/run-python` and can
  execute AiiDA-aware Python.

Those calls go directly from the agent tool layer to `aiida-worker`; they do not
carry `ApprovalDecision` and are not checked by the BFF's
`require_permission("/aris/submissions/current", "execute")` dependency.
Their safety currently depends on the agent prompt and model behavior. This is
an important remaining architecture gap, not part of the desired approval
design.

```mermaid
flowchart LR
    SAFE["React submission modal"] --> DECISION["Typed ApprovalDecision"]
    DECISION --> GATE["BFF policy + id/scope/digest gate"]
    GATE --> WORKER["aiida-worker /submission/submit"]

    AGENT["PydanticAI researcher"] --> DIRECT1["submit_validated_workflow"]
    AGENT --> DIRECT2["run_aiida_code_script"]
    DIRECT1 -->|"no typed decision"| WORKER
    DIRECT2 -->|"no typed decision"| RUNPY["aiida-worker /management/run-python"]
    RUNPY --> AIIDA["AiiDA runtime"]
    WORKER --> AIIDA
```

## Worker router and core-module map

```mermaid
flowchart LR
    CLIENT["ARIS AiiDAWorkerClient"] --> APP["aiida-worker/main.py"]

    APP --> MGMT["/management"]
    APP --> DATA["/data"]
    APP --> PROCESS["/process"]
    APP --> SUB["/submission"]
    APP --> EXEC["/execution"]
    APP --> REG["/registry"]

    MGMT --> M1["profiles / archives / system / resources"]
    MGMT --> M2["groups / recent nodes / context / soft delete"]
    MGMT --> M3["computers / codes / SSH / connection tests"]
    MGMT --> M4["environment inspect / run-python"]

    DATA --> D1["BandsData"]
    DATA --> D2["RemoteData files"]
    DATA --> D3["repository files"]

    PROCESS --> P1["process detail + logs"]
    PROCESS --> P2["provenance workgraph"]
    PROCESS --> P3["clone-draft"]
    PROCESS --> P4["process event SSE"]

    SUB --> S1["WorkChain spec"]
    SUB --> S2["draft-builder + validate"]
    SUB --> S3["single/batch submit"]
    SUB --> S4["generated submission script"]

    EXEC --> E1["inline or registered script"]
    EXEC --> E2["JSON response or output SSE"]
    REG --> R1["script list/register/read"]

    M1 --> ENGINE["core/engine.py"]
    M2 --> NODE["node_utils/process_utils"]
    M3 --> ENGINE
    M4 --> DYNAMIC["DynamicExecutionRuntime"]
    D1 --> NODE
    D2 --> NODE
    D3 --> NODE
    P1 --> NODE
    P2 --> NODE
    P3 --> NODE
    S1 --> INJECT["injected_submission.py"]
    S2 --> INJECT
    S3 --> UTILS["submission_utils.py"]
    S4 --> UTILS
    E1 --> DYNAMIC
    E2 --> DYNAMIC
    R1 --> SCRIPTS["core/scripts.py + repository/scripts"]

    ENGINE --> AIIDA["AiiDA profile / ORM / storage"]
    NODE --> AIIDA
    UTILS --> AIIDA
    INJECT --> DYNAMIC
```

`SessionCleanupAPIRouter` wraps ORM-facing endpoints so thread-local storage
sessions and backend caches are released after requests. `db_access_guard`
limits concurrent database access and returns a controlled 503 instead of
letting requests exhaust the storage pool.

## Worker interpreter selection

```mermaid
flowchart TD
    REQUEST["ARIS request"] --> HEADERS["Context<br/>X-ARIS-Active-Workspace-Path<br/>X-ARIS-Active-Python-Path"]
    HEADERS --> SELECT{"Explicit validated<br/>project Python?"}
    SELECT -->|"No"| DEFAULT["worker-default interpreter<br/>aiida-worker uv environment"]
    SELECT -->|"Yes"| PROJECT["project interpreter<br/>project .venv/conda environment"]
    DEFAULT --> RUNTIME["DynamicExecutionRuntime"]
    PROJECT --> RUNTIME
    RUNTIME --> ACTION{"Action"}
    ACTION --> INLINE["inline Python"]
    ACTION --> REGISTERED["registered script"]
    ACTION --> SPEC["injected WorkChain spec"]
    ACTION --> BUILD["injected draft/validate/submit"]
    INLINE --> SUBPROCESS["managed subprocess"]
    REGISTERED --> SUBPROCESS
    SPEC --> SUBPROCESS
    BUILD --> SUBPROCESS
    SUBPROCESS --> OUTPUT["stdout/stderr events<br/>+ machine-readable result marker"]
    OUTPUT --> WORKER["worker router response"]
    WORKER --> ARIS["ARIS presenter / chat tool"]
```

The selected project interpreter does not replace the worker service
environment. The worker remains alive in its own `uv` environment and launches
a bounded subprocess using the selected interpreter. The project workspace is
passed separately and remains an ARIS-owned filesystem location.

## AiiDA execution and feedback path

```mermaid
sequenceDiagram
    autonumber
    participant Worker as aiida-worker
    participant Profile as AiiDA profile
    participant ORM as ORM / QueryBuilder
    participant Engine as AiiDA engine
    participant Daemon as daemon + communicator
    participant Transport as local/SSH transport
    participant Scheduler as remote scheduler
    participant Store as DB + object repository
    participant ARIS
    participant UI

    Worker->>Profile: ensure_profile_loaded / switch_profile
    Profile->>Store: open configured storage
    Worker->>ORM: resolve node, code, computer and group references
    Worker->>Engine: submit validated builder
    Engine->>Store: create ProcessNode + provenance inputs
    Engine-->>Worker: process PK
    Worker-->>ARIS: submitted result
    ARIS-->>UI: process PK and submission status

    Engine->>Daemon: hand off process execution
    Daemon->>Transport: open computer transport
    Transport->>Scheduler: upload/submit/poll/retrieve
    Scheduler-->>Transport: state + remote output
    Transport-->>Daemon: retrieved files and scheduler result
    Daemon->>Store: process state, logs, outputs, provenance

    loop UI monitoring
        UI->>ARIS: process list/detail or domain stream
        ARIS->>Worker: deterministic process/data request
        Worker->>ORM: query latest state
        ORM->>Store: read metadata/repository
        Store-->>Worker: nodes, logs and files
        Worker-->>ARIS: worker payload
        ARIS->>ARIS: presenter normalization
        ARIS-->>UI: UI payload
    end
```

## MCP status

`uv run aris-aiida-mcp` starts a stdio FastMCP server in the ARIS repository.
It exposes ten inspect/preview tools, three resources and one protocol prompt.
Every operation delegates to the same `AiiDACapability` port used by the
application.

It intentionally has no submit tool. The current `PydanticAIGeminiRuntime` also
does not connect to this MCP server: its registered PydanticAI tools call the
HTTP worker client directly. Therefore:

```mermaid
flowchart LR
    CURRENT["Current Gemini agent"] -->|"PydanticAI tool function"| HTTP["AiiDAWorkerClient"]
    HTTP --> WORKER["aiida-worker HTTP API"]

    EXTERNAL["External/future MCP client"] -. "stdio" .-> MCP["aris-aiida-mcp"]
    MCP --> CAP["AiiDACapability"]
    CAP --> HTTP

    APPROVAL["ARIS typed UI approval gate"] -->|"approved UI launch path"| WORKER
    AGENT_EXEC["Existing execution-capable agent tools"] -->|"current direct HTTP path"| WORKER
    MCP -. "no submit capability" .-> APPROVAL
```

The MCP facade is an alternate protocol surface over AiiDA capabilities, not a
second model orchestrator. It does not introduce an approval bypass; the
existing agent tool layer described above is the current bypass.

## Current code-level gaps exposed by this map

These are observations from the current call graph, not target-state elements:

1. **Typed approval is not yet universal.** The execution-capable researcher
   tools described above can reach worker submission or Python execution
   without an `ApprovalDecision`.
2. **The MCP facade is not connected to the current agent runtime.** It is a
   runnable stdio server for an external/future MCP client, while the current
   Gemini agent uses in-process PydanticAI tool functions and HTTP.
3. **One MCP capability route does not match the worker router.**
   `HttpAiiDACapability.list_submission_plugins()` requests
   `/submission/plugins`, while the current worker exposes `GET /plugins`.
   The MCP `aiida_submission_plugins` tool therefore needs an adapter or route
   correction before it can work against this worker unchanged.
4. **The worker process-event producer is not started by `main.py`.**
   `/process/events` subscribes clients to `BroadcastManager`, and
   `core/events.py` defines `aiida_event_listener()`, but no current code calls
   that listener. The ARIS frontend process stream uses its own refresh logic;
   developers should not assume the worker event stream has an active producer.
5. **A worker compatibility entry remains.** `aiida_bridge.py` only re-exports
   `main.app`; PM2 starts `main:app`, so the re-export is not part of the normal
   launch path.

## Developer tracing guide

For a chat request, trace in this order:

1. `frontend/src/lib/api.ts` and `frontend/src/components/dashboard/chat-panel.tsx`
2. `src/aris_apps/aiida/router.py`
3. `src/aris_apps/aiida/chat/service.py`
4. `src/aris_apps/aiida/chat/turn_state_machine.py`
5. `src/aris_core/agent/runtime.py`
6. `src/aris_apps/aiida/agent/runtime.py`
7. `src/aris_apps/aiida/agent/researcher.py` and `agent/tools.py`
8. `src/aris_apps/aiida/client.py`
9. `aiida-worker/routers/*`
10. `aiida-worker/core/*`

For a submission, trace in this order:

1. `ARISResponse.task_mode` and `submission_request` / `data_payload`
2. `SubmissionPreviewService`
3. worker `/submission/draft-builder` and `/submission/validate`
4. `ApprovalRequest` rendered by React
5. `ApprovalDecision` constructed by `frontend/src/lib/api.ts`
6. ARIS policy and digest verification
7. worker `/submission/submit`
8. `core/injected_submission.py` or `core/submission_utils.py`
9. AiiDA `engine.submit`

For process inspection, trace:

1. React process/detail components
2. ARIS frontend process routes
3. ARIS presenter layer
4. `AiiDAWorkerClient`
5. worker `routers/process.py` or `routers/data.py`
6. `core/process_utils.py` / `core/node_utils.py`
7. AiiDA ORM and repository

## Important invariants

- Browser and macOS must keep one shared React codebase.
- AI intent that changes workflow topology must use explicit structured fields,
  especially `task_mode`; domain keyword matching is not an acceptable
  substitute.
- Preview construction and workflow execution are separate operations.
- The intended workflow-launch invariant is an explicit typed user decision
  bound to the exact draft digest. Current execution-capable agent tools violate
  this invariant and should be removed or routed through the same gate.
- MCP must not gain a submit tool unless the ARIS approval boundary is preserved
  by design.
- ARIS session JSON/workspace files and AiiDA storage are different persistence
  domains.
- The ARIS Python environment, worker service environment and selected project
  interpreter are separate runtime concerns.
