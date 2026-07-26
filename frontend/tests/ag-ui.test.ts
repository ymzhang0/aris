import assert from "node:assert/strict";
import test from "node:test";

import { parseArisAgUiEvent } from "../src/lib/ag-ui.ts";

test("parses an atomic ARIS state snapshot", () => {
  const parsed = parseArisAgUiEvent(JSON.stringify({
    type: "STATE_SNAPSHOT",
    snapshot: {
      aris: {
        chat: {
          version: 3,
          session_id: "session-1",
          messages: [],
          snapshot: {},
        },
        sessions: {
          version: 2,
          active_session_id: "session-1",
          active_project_id: "project-1",
          projects: [],
          items: [],
        },
      },
    },
  }));

  assert.equal(parsed?.kind, "state");
  if (parsed?.kind === "state") {
    assert.equal(parsed.chat.version, 3);
    assert.equal(parsed.sessions.active_project_id, "project-1");
  }
});

test("rejects malformed and partial snapshots", () => {
  assert.equal(parseArisAgUiEvent("not-json"), null);
  assert.equal(parseArisAgUiEvent(JSON.stringify({
    type: "STATE_SNAPSHOT",
    snapshot: { aris: { chat: { messages: [] } } },
  })), null);
});

test("parses lifecycle and error events", () => {
  assert.deepEqual(
    parseArisAgUiEvent(JSON.stringify({ type: "RUN_STARTED", threadId: "thread-1", runId: "run-1" })),
    { kind: "lifecycle", type: "RUN_STARTED" },
  );
  assert.deepEqual(
    parseArisAgUiEvent(JSON.stringify({ type: "RUN_ERROR", message: "offline", code: "ARIS_OFFLINE" })),
    { kind: "error", message: "offline", code: "ARIS_OFFLINE" },
  );
});

