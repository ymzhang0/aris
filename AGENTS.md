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
- Select a worker runtime from explicit project metadata: `project_id`, `python_interpreter_path`, and `aiida_profile`. Do not infer a Python environment from a workspace path, virtual-environment directory name, session prose, or tool parameters.
- Run aiida-worker with the selected project Python. ARIS must not import project packages into its own process, and the worker must not switch to a second Python environment for submission.
- Keep one centrally owned, versioned worker source/artifact and execute it with the selected project Python. Do not install or update `aris-aiida-worker` separately in every project environment.
- Treat `(project_id, python_interpreter_path, aiida_profile)` as the worker lifecycle identity. Verify the worker-reported interpreter and profile before serving project requests.
- Desktop App and browser modes must share the same frontend source and backend API. Do not maintain separate layouts or duplicated feature implementations.

## Projects and Chat Ownership

- A project is the ownership boundary for a local workspace, its AiiDA project Group metadata, and its chat sessions.
- Every chat session must persist an explicit `project_id`. Use that field as the only source of truth for grouping a chat under a project; do not infer ownership from titles, paths, Group labels, the currently active session, or UI proximity.
- When the user creates a chat from a selected project, the frontend must send that project's ID explicitly. Backend fallback to the active session/project is only for callers that genuinely omit project context.
- Project selection and active-session selection are distinct UI states. Selecting a project may change the workspace being browsed without silently moving or reparenting the active chat.
- Activating a session must select its persisted project. Renaming or auto-titling a session may update its title, slug, workspace directory, and session Group label, but must not change its `project_id`.
- Project-oriented navigation must render sessions from `session.project_id` beneath their owning project. A flat recent-chat view may be supplemental, but must not replace or contradict the project hierarchy.
- Project AiiDA Groups mirror project identity for scientific resources; they are not a replacement for the persisted project/session relationship.

## Chat Interaction, Latency, and Concurrency

- “New conversation” is a client-side draft navigation state. Do not create, persist, activate, or list a chat session until the first message has been accepted for submission; repeated clicks must reuse/reset the draft page rather than create empty sessions.
- The first send from a draft must create the session with the selected `project_id`, submit the turn with the returned `session_id`, and only then expose the session in the project sidebar. If session creation or turn submission fails, keep the draft editable and remove any empty session created by the failed attempt.
- Chat submission must include the originating `session_id` in the frontend/backend schema. The backend must append the turn to that explicit session even if the active session changes before the request is handled.
- Never route a delayed request, worker result, title update, attachment, or cleanup operation by reading the current active session. Capture explicit ownership before the asynchronous boundary and carry it through every layer.
- Sending a message must immediately show a local user message and queued/thinking state, clear the composer, and transition an empty conversation into the conversation view. Replace the optimistic turn with the authoritative server/SSE turn and remove it on failure.
- Busy state is session-scoped. A running or queueing turn may prevent another send in the same session, but session switching and unrelated project navigation must remain available. Switching sessions must not cancel the original turn unless the user explicitly requests cancellation.
- When a user returns to a session with a thinking turn, reconstruct that session's loading/stop state from its persisted messages or explicit turn state; do not rely on one global boolean left over from another session.
- Session activation is navigation, not content modification. It must not update `updated_at`, reorder the conversation list, archive another session, or trigger full-history persistence.
- Create, activate, update, and delete responses must return one atomic sessions/chat snapshot with a monotonic version. The frontend should apply that response directly and reject older SSE snapshots rather than immediately invalidating and refetching the same query.
- Do not archive the previous conversation merely because the user creates a new one. Archiving is an explicit lifecycle action, not a side effect of navigation.
- Chat CRUD and queue acknowledgement must not await AiiDA Group creation/deletion, plugin discovery, worker startup, profile loading, title generation, or other optional scientific follow-up work.
- Async follow-up tasks that call synchronous worker or AiiDA helpers must run those calls through `asyncio.to_thread()` or a genuinely asynchronous API. `BackgroundTasks` and `asyncio.create_task()` are not sufficient if the coroutine itself performs blocking synchronous work.
- Keep strong references to detached tasks, log their failures, provide project-scoped worker context, and clean task registries when they finish. Detached work must not silently lose `project_id`, Python interpreter, or AiiDA profile context.
- Persist only changed session payloads for ordinary chat mutations. Updating one turn must not serialize, compare, and rewrite every conversation file.
- SSE loops must check versions before building full chat/session payloads. Do not serialize the complete history every polling interval when nothing changed, and do not duplicate an SSE stream with frequent full HTTP polling for the same state.

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
- Project package management is an ARIS application capability, not a worker RPC capability, because it must repair environments before the worker can start. Run package commands with argument arrays, validate registry requirements and local editable paths, persist the selected interpreter on the project, and restart only that project's worker after mutations.

## ARIS Verification

- Run `uv run pytest -q` for Python changes.
- Run `npm test` and `npm run build` from `frontend` for frontend or API-contract changes.
- Any frontend or Desktop App interaction change must be tested in the actual Electron/Desktop App after building. Start or reload the app from the current worktree and use real pointer/keyboard interaction to exercise the changed flow (including create, switch, send, delete, confirmation, and error paths where relevant). Verify the visible state, loading indicator, responsiveness, and browser/desktop console or network errors; automated tests and a successful build alone are insufficient.
- For create/activate/delete/chat latency changes, run a real desktop smoke test with the worker slow or unavailable and confirm that the UI acknowledges the action promptly and unrelated navigation still works. Include the observed result in the handoff.
- If the desktop app cannot be launched or controlled, state that the desktop smoke test is unverified and why. Do not claim full verification from tests/build output alone.
- Chat interaction changes must test: immediate optimistic send, send followed immediately by session activation, explicit-session routing when active selection changes, stale snapshot rejection, switching away from and back to a running turn, and rollback after queue failure.
- Exercise create, activate, delete, and chat queue acknowledgement with a slow or unavailable worker. These UI-critical endpoints must return without waiting for worker/profile/Group work; measure the real route when changing their execution path.
- Add a regression test whenever a global UI flag can disable navigation. The test must prove that only the owning operation/session is blocked and unrelated session/project actions remain usable.
- For worker lifecycle or transport changes, verify startup, online status, resource discovery, offline reporting, and recovery with the real managed worker.
- Before completing worker-client changes, search production code for legacy HTTP-shaped calls, including HTTP method strings, worker URL paths, `request_multipart`, URL quoting, and removed client method names.
