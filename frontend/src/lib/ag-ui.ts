import type { ChatSessionsResponse, ChatSnapshot } from "@/types/aiida";

export type ArisAgUiStateEvent = {
  kind: "state";
  chat: ChatSnapshot;
  sessions: ChatSessionsResponse;
};

export type ArisAgUiLifecycleEvent = {
  kind: "lifecycle";
  type: "RUN_STARTED" | "RUN_FINISHED";
};

export type ArisAgUiErrorEvent = {
  kind: "error";
  message: string;
  code: string | null;
};

export type ArisAgUiEvent =
  | ArisAgUiStateEvent
  | ArisAgUiLifecycleEvent
  | ArisAgUiErrorEvent;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function parseStateSnapshot(event: Record<string, unknown>): ArisAgUiStateEvent | null {
  const snapshot = asRecord(event.snapshot);
  const aris = asRecord(snapshot?.aris);
  const chat = asRecord(aris?.chat);
  const sessions = asRecord(aris?.sessions);
  if (
    !chat ||
    !sessions ||
    !Array.isArray(chat.messages) ||
    !Array.isArray(sessions.items) ||
    !Array.isArray(sessions.projects)
  ) {
    return null;
  }
  return {
    kind: "state",
    chat: chat as ChatSnapshot,
    sessions: sessions as ChatSessionsResponse,
  };
}

export function parseArisAgUiEvent(payload: string): ArisAgUiEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch {
    return null;
  }
  const event = asRecord(parsed);
  const type = typeof event?.type === "string" ? event.type : "";
  if (!event || !type) {
    return null;
  }
  if (type === "STATE_SNAPSHOT") {
    return parseStateSnapshot(event);
  }
  if (type === "RUN_STARTED" || type === "RUN_FINISHED") {
    return { kind: "lifecycle", type };
  }
  if (type === "RUN_ERROR") {
    return {
      kind: "error",
      message: typeof event.message === "string" ? event.message : "ARIS state stream failed",
      code: typeof event.code === "string" ? event.code : null,
    };
  }
  return null;
}

export function buildAgUiChatStreamUrl(legacyUrl: string): string {
  const separator = legacyUrl.includes("?") ? "&" : "?";
  return `${legacyUrl}${separator}protocol=ag-ui`;
}

