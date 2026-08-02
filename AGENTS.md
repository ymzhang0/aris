# ARIS Agent Rules

## Protocol First

- When ARIS behavior depends on AI intent, use an explicit machine-readable protocol instead of semantic keyword heuristics.
- Define the protocol in schema first, then parse and handle it in code. Current examples:
  - structured response field `task_mode`
  - structured message field `data_payload.submission_draft`
- Do not infer workflow topology from domain phrases such as `EOS`, `状态方程`, `缩放比例`, or `parameter sweep` when an explicit protocol field can carry that meaning.

## Workflow Topology

- Use `task_mode="single"` for one runnable submission preview.
- Use `task_mode="batch"` for multi-structure, parameter-grid, or high-throughput preparation.
- Use `task_mode="none"` for analysis-only or non-submission turns.
- If a new UI or backend branch needs AI classification, add a new explicit field and a tested handler instead of adding phrase lists.

## Change Discipline

- For new AI-visible protocols, update prompt/specification, parser/handler, and regression tests together.
- If you are about to add business-specific keyword matching to recover AI intent, stop and replace it with an explicit structured field unless there is a documented blocker.

## ARIS Responsibilities

- ARIS is the application boundary for browser and Desktop App clients.
- Keep browser-facing FastAPI routes, HTTP APIs, SSE streams, and WebSocket endpoints when they have active frontend consumers.
- ARIS must start, monitor, stop, and recover the managed aiida-worker subprocess.
- All ARIS-to-worker calls must go through the canonical stdio JSON-RPC client. Do not introduce worker HTTP URLs, fake HTTP endpoint paths, or a second worker client.
- ARIS owns sessions, projects, permissions, submission previews and confirmation, UI state, retry/error recovery, and runtime selection.
- Desktop App and browser modes must share the same frontend source and backend API. Do not maintain separate layouts or duplicated feature implementations.

## Projects and Chat Ownership

- A project is the ownership boundary for a local workspace, its AiiDA project Group metadata, and its chat sessions.
- Every chat session must persist an explicit `project_id`. Use that field as the only source of truth for grouping a chat under a project; do not infer ownership from titles, paths, Group labels, the currently active session, or UI proximity.
- When the user creates a chat from a selected project, the frontend must send that project's ID explicitly. Backend fallback to the active session/project is only for callers that genuinely omit project context.
- Project selection and active-session selection are distinct UI states. Selecting a project may change the workspace being browsed without silently moving or reparenting the active chat.
- Activating a session must select its persisted project. Renaming or auto-titling a session may update its title, slug, workspace directory, and session Group label, but must not change its `project_id`.
- Project-oriented navigation must render sessions from `session.project_id` beneath their owning project. A flat recent-chat view may be supplemental, but must not replace or contradict the project hierarchy.
- Project AiiDA Groups mirror project identity for scientific resources; they are not a replacement for the persisted project/session relationship.

## ARIS Code Structure

- Keep one canonical frontend API implementation per endpoint. Do not duplicate requests across `frontend/src/api` and `frontend/src/lib`.
- FastAPI routers should translate HTTP input/output and delegate application behavior; they should not absorb repository, worker transport, or domain logic.
- Application services should not become re-export barrels for unrelated adapters.
- Internal worker errors must be transport-neutral and may be mapped to HTTP errors only at the FastAPI boundary.
- Worker calls must use a registered JSON-RPC method name and a JSON-serializable parameter object. Do not pass HTTP verbs, URL paths, URL-quoted identifiers, multipart requests, or query-string parameters to the worker client.
- Encode binary worker payloads explicitly in the protocol, currently with base64 fields such as `content_base64`; decode or encode them in one canonical transport helper.
- Optional worker reads must use the canonical optional-RPC helper and only translate documented not-found/unsupported RPC outcomes to `None`.
- Do not retain Bridge naming for components that now exclusively represent the managed worker or stdio RPC.
- Do not retain deprecated aliases, fake HTTP paths, unused schemas, compatibility wrappers, or legacy configuration without a current in-repository consumer.
- When replacing an interface, migrate all current consumers in the same change and remove the obsolete interface, tests, fixtures, configuration, documentation, and dependencies.
- Before deleting code, check imports, dynamic registration, decorators, registries, string references, tests, public API consumers, and startup wiring.
- Preserve unrelated user changes and never reset, overwrite, or broadly reformat a dirty worktree.
- UI layout and visual behavior must remain unchanged unless the task explicitly requests UI changes.

## ARIS Verification

- Run `uv run pytest -q` for Python changes.
- Run `npm test` and `npm run build` from `frontend` for frontend or API-contract changes.
- For worker lifecycle or transport changes, verify startup, online status, resource discovery, offline reporting, and recovery with the real managed worker.
- Before completing worker-client changes, search production code for legacy HTTP-shaped calls, including HTTP method strings, worker URL paths, `request_multipart`, URL quoting, and removed client method names.
