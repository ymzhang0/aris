"""MCP Apps UI resources for the AiiDA plugin.

The first widget is intentionally dependency-free so the MCP server can be
used from a packaged ARIS environment without a separate frontend build step.
It uses the MCP Apps bridge and therefore remains portable to compatible MCP
hosts.
"""

from __future__ import annotations


AIIDA_EXPLORER_RESOURCE_URI = "ui://aiida/explorer/v1.html"


AIIDA_EXPLORER_HTML = r"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
      body { margin: 0; padding: 12px; color: #202124; background: #fff; }
      @media (prefers-color-scheme: dark) {
        body { color: #e8eaed; background: #202124; }
        .muted, .meta { color: #9aa0a6; }
        .row, .detail { border-color: #3c4043; }
        button { color: #e8eaed; background: #303134; border-color: #5f6368; }
      }
      h2 { margin: 0 0 10px; font-size: 16px; }
      .muted, .meta { color: #5f6368; font-size: 12px; }
      .toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
      button { border: 1px solid #dadce0; border-radius: 8px; padding: 6px 10px; background: #fff; cursor: pointer; }
      button:hover { background: #f8f9fa; }
      .list { display: grid; gap: 6px; }
      .row { display: flex; justify-content: space-between; gap: 10px; padding: 9px; border: 1px solid #dadce0; border-radius: 9px; cursor: pointer; }
      .row:hover { background: rgba(127, 127, 127, .09); }
      .title { font-weight: 600; font-size: 13px; overflow-wrap: anywhere; }
      .status { white-space: nowrap; font-size: 12px; }
      .detail { margin-top: 12px; padding-top: 12px; border-top: 1px solid #dadce0; }
      pre { margin: 8px 0 0; padding: 9px; overflow: auto; border-radius: 8px; background: rgba(127, 127, 127, .12); font-size: 11px; }
      .error { color: #b3261e; font-size: 12px; }
    </style>
  </head>
  <body>
    <div class="toolbar">
      <h2>AiiDA Explorer</h2>
      <span id="count" class="muted"></span>
      <button id="refresh" type="button">Refresh</button>
    </div>
    <div id="message" class="muted">Waiting for AiiDA data…</div>
    <div id="list" class="list"></div>
    <section id="detail" class="detail" hidden></section>
    <script>
      const pending = new Map();
      let nextId = 1;
      let latest = [];
      let selectedProjectId = null;

      function bridge(method, params) {
        const id = nextId++;
        window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
        return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
      }

      function notify(method, params) {
        window.parent.postMessage({ jsonrpc: "2.0", method, params }, "*");
      }

      function resultPayload(result) {
        return result && (result.structuredContent || result.structured_content || result);
      }

      function processItems(payload) {
        if (Array.isArray(payload)) return payload;
        if (!payload || typeof payload !== "object") return [];
        return Array.isArray(payload.processes) ? payload.processes : [];
      }

      function text(value, fallback = "—") {
        return value === undefined || value === null || value === "" ? fallback : String(value);
      }

      function render(payload) {
        selectedProjectId = payload && typeof payload === "object" ? payload.project_id || selectedProjectId : selectedProjectId;
        latest = processItems(payload);
        document.getElementById("count").textContent = latest.length ? `${latest.length} processes` : "";
        document.getElementById("message").textContent = latest.length ? "" : "No recent processes.";
        const list = document.getElementById("list");
        list.replaceChildren();
        latest.forEach((item, index) => {
          const row = document.createElement("div");
          row.className = "row";
          row.tabIndex = 0;
          row.innerHTML = `<div><div class="title"></div><div class="meta"></div></div><div class="status"></div>`;
          row.querySelector(".title").textContent = `${text(item.process_label || item.process_type || "Process")} #${text(item.pk || item.id || index + 1)}`;
          row.querySelector(".meta").textContent = text(item.ctime || item.created || item.process_state, "AiiDA process");
          row.querySelector(".status").textContent = text(item.process_state || item.state || item.status);
          row.addEventListener("click", () => inspect(item));
          row.addEventListener("keydown", (event) => { if (event.key === "Enter") inspect(item); });
          list.appendChild(row);
        });
      }

      async function inspect(item) {
        const identifier = item.pk || item.id || item.uuid;
        if (!identifier) return;
        const detail = document.getElementById("detail");
        detail.hidden = false;
        detail.innerHTML = `<div class="muted">Loading process ${text(identifier)}…</div>`;
        try {
          const response = await bridge("tools/call", {
            name: "aiida_inspect_process",
            arguments: { identifier: String(identifier), project_id: selectedProjectId },
          });
          const payload = resultPayload(response && response.result);
          detail.innerHTML = "";
          const heading = document.createElement("div");
          heading.className = "title";
          heading.textContent = `Process ${text(identifier)}`;
          const body = document.createElement("pre");
          body.textContent = JSON.stringify(payload, null, 2);
          detail.append(heading, body);
        } catch (error) {
          detail.innerHTML = `<div class="error">Unable to inspect process: ${text(error?.message, error)}</div>`;
        }
      }

      async function refresh() {
        document.getElementById("message").textContent = "Loading recent processes…";
        try {
          const response = await bridge("tools/call", {
            name: "aiida_recent_processes",
            arguments: { limit: 20, project_id: selectedProjectId },
          });
          render(resultPayload(response && response.result));
        } catch (error) {
          document.getElementById("message").innerHTML = `<span class="error">Unable to load AiiDA processes: ${text(error?.message, error)}</span>`;
        }
      }

      window.addEventListener("message", (event) => {
        if (event.source !== window.parent) return;
        const message = event.data;
        if (!message || message.jsonrpc !== "2.0") return;
        if (message.id !== undefined && pending.has(message.id)) {
          const request = pending.get(message.id);
          pending.delete(message.id);
          if (message.error) request.reject(message.error);
          else request.resolve(message.result);
          return;
        }
        if (message.method === "ui/notifications/tool-result") {
          render(message.params);
        }
      });

      document.getElementById("refresh").addEventListener("click", refresh);
      bridge("ui/initialize", { protocolVersion: "2026-01-26", capabilities: {}, clientInfo: { name: "aris-aiida-explorer", version: "1.0.0" } })
        .then(() => notify("ui/notifications/initialized", {}))
        .catch(() => undefined);
    </script>
  </body>
</html>
"""


__all__ = ["AIIDA_EXPLORER_HTML", "AIIDA_EXPLORER_RESOURCE_URI"]
