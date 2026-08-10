# AiiDA MCP App

The ARIS AiiDA MCP server exposes deterministic AiiDA tools and an interactive
`AiiDA Explorer` MCP App widget. The widget currently lists recent processes
and can inspect a process from inside the component.

## Local checks

Run the stdio server for local MCP clients:

```bash
uv run aris-aiida-mcp
```

The standalone server reads the ARIS project catalog from the configured ARIS
memory directory. It does not bind to one workspace. Use
`aiida_list_projects` followed by `aiida_select_project`, or pass `project_id`
explicitly to each AiiDA tool. The worker interpreter, workspace, and profile
come from the selected ARIS project record.

Run the same server over streamable HTTP when a host needs an MCP endpoint:

```bash
ARIS_MCP_HOST=127.0.0.1 ARIS_MCP_PORT=8000 uv run aris-aiida-mcp-http
```

The endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The HTTP entrypoint is an MCP transport for ARIS. It does not add an HTTP
server to `aiida-worker`; ARIS still owns the worker and communicates with it
using the existing managed stdio JSON-RPC process.

## Connect to ChatGPT in development

ChatGPT Developer Mode requires a reachable HTTPS streamable MCP endpoint or a
Secure MCP Tunnel. Start `aris-aiida-mcp-http`, expose `/mcp` through the
approved tunnel, then add that endpoint from ChatGPT's Plugins/Developer Mode
connection flow. Start a new conversation, enable the AiiDA connection, and
ask for recent calculations.

The model should call `aiida_recent_processes` and then
`render_aiida_explorer`. The widget's Refresh button and process rows call the
read-only tools through the MCP Apps bridge. Submission tools remain preview
only and do not launch calculations.

For production, put authentication and authorization in front of the MCP
endpoint and scope every request to the intended ARIS project, profile, and
user. Do not expose a worker port directly.
