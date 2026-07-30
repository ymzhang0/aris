# ARIS 2.0 Architecture

This document defines the current ARIS architecture and its next evolution
points.

For a code-level map of the running processes, chat state machine, approval
flow, MCP facade, worker routers, interpreter selection and AiiDA execution
path, see
[`ARIS and aiida-worker internal flow`](ARIS_AIIDA_WORKER_INTERNAL_FLOW.md).

## Goals

- Keep one React product UI for browser and desktop delivery.
- Keep AiiDA as the source of truth for scientific data and durable workflows.
- Make the LLM provider and agent SDK replaceable.
- Give UI behavior an explicit, versioned protocol.
- Keep the compute environment isolated from the ARIS application environment.
- Make AiiDA capabilities available to both deterministic application code and
  agents without forcing the UI through an agent protocol.

## Target layers

The editable diagram sources live in
[`docs/architecture/diagrams/aris-control-plane.mmd`](diagrams/aris-control-plane.mmd)
and
[`docs/architecture/diagrams/aris-control-plane.dot`](diagrams/aris-control-plane.dot).

```text
React UI (browser + macOS shell)
        |
Application API / BFF
        |
        +-- Agent Runtime --------------------+
        |   (provider-neutral interface)      |
        |                                     v
        +-- Submission Domain Service --> AiiDA Capability
                                               |
                                  +-- JSON-RPC adapter (UI)
                                  +-- MCP facade (agents)
                                               |
                                          aiida-worker
                                               |
                                             AiiDA
```

### Product UI

The browser and desktop app use the same built frontend and the same layout.
Platform shells may provide window integration, but must not create a second
product UI implementation.

### Application API / BFF

FastAPI owns sessions, UI snapshots, event delivery, user preferences, and
coordination between deterministic services and the agent runtime. It does not
contain provider-specific model construction.

Session persistence is accessed through `ChatSessionRepository`. The current
`JsonChatSessionRepository` preserves the existing memory index plus
`sessions/*.json` files, performs atomic session-file replacement, and removes
orphaned files. A repository can be injected on
the application state, so a future SQLite or PostgreSQL adapter does not require
changes to chat behavior.

Persisted message, tag, and session-snapshot shapes are normalized by the pure
`chat.session_models` module. It has no filesystem, AiiDA, or model-runtime
dependencies; the chat service delegates these transformations to that module.

Session naming is separated into `chat.title_rules`: title sanitization, slug
generation, context fingerprints, prompt construction, and lifecycle scheduling
are deterministic rules. Provider calls, asynchronous task coordination,
persistence, and workspace/group renaming remain in the chat service.

Session commands and reads are separated into
`ChatSessionApplicationService` and `ChatSessionQueryService`. The original
chat module retains thin public entry points so API and UI callers do not depend
on persistence details.

One chat turn is driven by `ChatTurnStateMachine`. Model invocation, exponential
backoff, recovery, failure, and cancellation use explicit legal transitions;
the structured execution state is included in the assistant message payload.

Project filesystem behavior is owned by `ChatWorkspaceManager`. It defines the
shared `codes/` and `data/` layout, validates file targets against path and
symlink escapes, and only removes an entire project root when that root is
ARIS-managed. Chat sessions
share their project root rather than creating a second nested workspace.

AiiDA group access is routed through `ChatGroupGateway`. The default
`FrontendWorkerGroupGateway` owns worker-specific inspection and rename calls,
prevents a session rename from overwriting an existing group, and tolerates an
offline worker during best-effort title/group synchronization. A gateway can be
injected on application state for tests or a future MCP-backed implementation;
group-label construction remains deterministic and provider-independent.

### Agent Runtime

Application code calls an `AgentRuntime` protocol with an `AgentRunRequest`.
The initial adapter wraps the existing PydanticAI agent and Gemini provider.
Future adapters may wrap OpenAI Agents SDK or another runtime without changing
chat, submission, or AiiDA domain code.

### Submission Domain

Submission topology is controlled by explicit protocol values:

- `task_mode="none"`: analysis only
- `task_mode="single"`: one runnable preview
- `task_mode="batch"`: multiple structures, a parameter grid, or throughput work

Submission previews travel only through structured message payloads. Domain
phrases must not be used to infer topology.

### AiiDA Capability

Application and agent code depend on an `AiiDACapability` protocol. The current
adapter delegates to `AiiDAWorkerClient` over JSON-RPC. `AiiDAMCPFacade` and the
`aris-aiida-mcp` stdio server expose agent-facing inspection and submission
preview tools, resources, and a protocol prompt. The MCP surface intentionally
has no submission-execution tool: typed approval and execution remain in the
ARIS application. Deterministic UI routes continue to use JSON-RPC.

## UI events

`GET /api/aiida/frontend/chat/stream` is an AG-UI-only state stream. It
publishes a `RUN_STARTED` lifecycle event followed by atomic `STATE_SNAPSHOT`
events containing both chat and session state. Stream failures use
`RUN_ERROR`; there is no alternate event-name, payload protocol, or
`/chat/messages` polling fallback.

## Submission approval

Every new UI confirmation emits a typed `ApprovalDecision` for the
`submission.execute` action. Its scope is explicit (`single`, `batch`, or
`pending` for cancellation), and chat-generated approval requests bind the
decision to the actionable draft with a stable digest. The API rejects a
mismatched scope, a rejected execution decision, or a draft modified after
approval.

Submission and pending-cancellation endpoints require an explicit
`ApprovalDecision`. Missing decisions are rejected rather than inferred.
Execution decisions must reuse the server-issued approval ID and resource
digest; the browser cannot synthesize an execution approval when an approval
request is absent. Clone previews follow the same protocol.

## Authorization policy

Consequential API actions pass through the `AuthorizationPolicy` boundary. The
first adapter uses PyCasbin with the model and policies in `config/policy/`.
Submission execution/cancellation, profile and infrastructure configuration,
node/group deletion, and chat project/session deletion are currently protected.
Every decision is written to the structured application log.

ARIS is still a local single-user application, so the subject and role come from
`ARIS_LOCAL_ACTOR_ID` and `ARIS_LOCAL_ROLE`; the default role is `owner` and
therefore preserves current behavior. The shipped `operator` role can run or
cancel submissions and manage research objects, but cannot configure profiles,
computers, or codes. Unknown roles are denied mutations by default. A future
login/session provider can replace the subject resolver without changing
business routes or the Casbin policy adapter.

The frontend bootstrap contains a versioned authorization snapshot with named
permissions such as `submission.execute`, `chat.delete`, and `node.delete`.
Controls use this snapshot to disable unavailable actions, while the API
dependency remains the authoritative enforcement point.

## Environment boundaries

The repository may become a monorepo, but runtime environments remain separate:

- ARIS application environment: API, agent runtime, UI support
- compute environment: AiiDA, scientific plugins, codes, schedulers

Sharing a repository does not imply sharing a Python virtual environment.

## Next architecture steps

1. Replace JSON session persistence with a transactional repository.
2. Move runtime selection into the explicit turn state machine.
3. Connect the selected agent runtime to the AiiDA MCP server.
4. Consolidate repositories only after service boundaries are stable.
5. Evaluate an OpenAI Agents SDK adapter after the provider-neutral contract is
   exercised by the current implementation.

## Change rules

- Protocol changes update schema, parser/handler, and regression tests together.
- New AI-driven UI branches require explicit structured fields.
- Domain services consume typed protocol values.
- Provider-specific errors and settings stay inside provider/runtime adapters.
- Every architecture step must leave the application runnable and testable.
