# ARIS 2.0 Architecture

This document defines the target architecture for ARIS and the migration rules
used to reach it without replacing working product behavior all at once.

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
                                  HTTP adapter now
                                  MCP adapter later
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

Text markers such as `[SUBMISSION_DRAFT]` remain compatibility transport, not a
replacement for the structured protocol. Domain phrases must not be used to
infer topology.

### AiiDA Capability

Application and agent code depend on an `AiiDACapability` protocol. The current
adapter delegates to `AiiDAWorkerClient` over HTTP. A future MCP facade may
expose agent-facing tools, resources, and prompts while deterministic UI routes
continue to use HTTP.

## Versioned UI events

Internal event creation uses a typed `UIEventEnvelope` with:

- `protocol_version`
- `type`
- `payload`
- `event_id`
- `created_at`
- optional `correlation_id`

During migration, the SSE compatibility adapter emits the existing event names
and payload bodies so the current frontend does not need a flag-day rewrite.
Clients may opt into the AG-UI transport with
`GET /api/aiida/frontend/chat/stream?protocol=ag-ui`. It publishes a
`RUN_STARTED` lifecycle event followed by atomic `STATE_SNAPSHOT` events. The
ARIS frontend now requests this transport first and sends both snapshots through
the same state application functions previously used by legacy SSE. If no valid
AG-UI state arrives, it falls back to `protocol=legacy`; HTTP polling remains a
last-resort recovery path. The endpoint default stays `protocol=legacy` for
external clients that have not migrated.

## Submission approval

Every new UI confirmation emits a typed `ApprovalDecision` for the
`submission.execute` action. Its scope is explicit (`single`, `batch`, or
`pending` for cancellation), and chat-generated approval requests bind the
decision to the actionable draft with a stable digest. The API rejects a
mismatched scope, a rejected execution decision, or a draft modified after
approval.

Direct legacy API callers remain temporarily supported. Their implicit approval
is marked as `compatibility_implicit` in the response and logs so it can be
measured and removed in a later migration.

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

## Environment boundaries

The repository may become a monorepo, but runtime environments remain separate:

- ARIS application environment: API, agent runtime, UI support
- compute environment: AiiDA, scientific plugins, codes, schedulers

Sharing a repository does not imply sharing a Python virtual environment.

## Migration sequence

1. Introduce typed protocols and compatibility adapters.
2. Move provider-specific model invocation behind `AgentRuntime`.
3. Extract pure submission rules from the chat service.
4. Route application code through `AiiDACapability`.
5. Add an MCP facade for agent-facing AiiDA capabilities.
6. Consolidate repositories only after service boundaries are stable.
7. Evaluate an OpenAI Agents SDK adapter after the provider-neutral contract is
   exercised by the current implementation.

## Change rules

- Protocol changes update schema, parser/handler, and regression tests together.
- New AI-driven UI branches require explicit structured fields or markers.
- Adapters may preserve legacy payloads, but domain services must consume typed
  values.
- Provider-specific errors and settings stay inside provider/runtime adapters.
- A migration step must leave the application runnable and testable.
