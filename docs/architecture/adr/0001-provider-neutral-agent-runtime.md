# ADR 0001: Provider-neutral agent runtime

Status: Accepted

## Context

ARIS currently constructs a PydanticAI Gemini agent and calls it from the chat
application service. This couples session, submission, and UI behavior to a
specific SDK and provider.

ARIS may move from Gemini to OpenAI later, but selecting an SDK before the
application boundary exists would spread a second provider implementation
through the same service.

## Decision

ARIS application code depends on the `AgentRuntime` protocol. PydanticAI and
Gemini are the first adapter. Provider-specific model construction, settings,
and rejection diagnostics belong to that adapter.

The runtime returns an `AgentRunResult` containing the typed output and optional
provider metadata. Application code must not inspect SDK-specific result
objects.

## Consequences

- The current behavior remains available through an adapter.
- OpenAI Agents SDK can be evaluated and introduced as a second adapter.
- SDK-specific tracing or handoffs may be exposed as optional metadata, not as
  requirements of the application service.
- The common contract intentionally stays small until both implementations
  demonstrate a need for additional operations.
