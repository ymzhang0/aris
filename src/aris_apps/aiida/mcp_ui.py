"""MCP Apps UI resources for the AiiDA plugin.

The first widget is intentionally dependency-free so the MCP server can be
used from a packaged ARIS environment without a separate frontend build step.
It uses the MCP Apps bridge and therefore remains portable to compatible MCP
hosts.
"""

from __future__ import annotations


AIIDA_EXPLORER_RESOURCE_URI = "ui://aiida/explorer/v1.html"
AIIDA_WORKSPACE_RESOURCE_URI = "ui://aiida/workspace/v1.html"


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


AIIDA_WORKSPACE_HTML = r"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
      * { box-sizing: border-box; }
      body { margin: 0; background: #f8fafc; color: #172033; }
      header { padding: 16px; background: #123c68; color: #fff; }
      h1 { margin: 0; font-size: 18px; } .subtitle { margin-top: 4px; opacity: .78; font-size: 12px; }
      main { padding: 14px; } .toolbar, .tabs, .form-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
      .toolbar { margin-bottom: 12px; } button, select, input { font: inherit; border: 1px solid #cbd5e1; border-radius: 7px; padding: 7px 9px; background: #fff; color: inherit; }
      button { cursor: pointer; } button.active { background: #1d5d99; border-color: #1d5d99; color: #fff; } button.primary { background: #1d5d99; border-color: #1d5d99; color: #fff; }
      .tabs { border-bottom: 1px solid #cbd5e1; margin-bottom: 12px; padding-bottom: 8px; } .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 9px; }
      .card, .item, .detail { border: 1px solid #d8e0ea; border-radius: 9px; background: #fff; padding: 11px; } .item { cursor: pointer; } .item:hover { border-color: #5890c5; }
      .title { font-weight: 650; font-size: 13px; overflow-wrap: anywhere; } .muted { color: #64748b; font-size: 12px; } .status { font-size: 12px; font-weight: 600; }
      .detail { margin-top: 12px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 360px; overflow: auto; margin: 8px 0 0; padding: 10px; border-radius: 7px; background: #eef3f8; font-size: 11px; }
      .error { color: #b42318; } .success { color: #067647; } .hidden { display: none; } label { display: grid; gap: 4px; font-size: 12px; }
      @media (prefers-color-scheme: dark) { body { background: #0e1621; color: #e5edf7; } button, select, input, .card, .item, .detail { background: #172433; color: #e5edf7; border-color: #314256; } .tabs { border-color: #314256; } .muted { color: #a4b2c2; } pre { background: #0e1621; } }
    </style>
  </head>
  <body>
    <header><h1>AiiDA Workspace</h1><div class="subtitle">Project-scoped scientific data, workflows, and submission previews</div></header>
    <main>
      <div class="toolbar"><label>Project<select id="projects"><option value="">Choose an ARIS project…</option></select></label><button id="refresh" type="button">Refresh</button><span id="state" class="muted">Loading projects…</span></div>
      <nav id="tabs" class="tabs"></nav><section id="content"></section><section id="detail" class="detail hidden"></section>
    </main>
    <script>
      const state = { projects: [], projectId: null, tab: "overview", pending: new Map(), nextId: 1, draft: null };
      const tabLabels = { overview: "Overview", processes: "Processes", nodes: "Nodes", resources: "Resources", workflows: "Workflows", preview: "Preview" };
      const content = document.getElementById("content"), detail = document.getElementById("detail"), status = document.getElementById("state"), selector = document.getElementById("projects");
      function call(name, args = {}) { const id = state.nextId++; window.parent.postMessage({ jsonrpc: "2.0", id, method: "tools/call", params: { name, arguments: args } }, "*"); return new Promise((resolve, reject) => state.pending.set(id, { resolve, reject })); }
      function payload(result) { const value = result && (result.structuredContent || result.structured_content || result); return value && value.result ? payload(value.result) : value; }
      function asArray(value, key) { return Array.isArray(value) ? value : Array.isArray(value && value[key]) ? value[key] : []; }
      function text(value, fallback = "—") { return value === undefined || value === null || value === "" ? fallback : String(value); }
      function clearDetail() { detail.classList.add("hidden"); detail.replaceChildren(); }
      function showDetail(title, value) { detail.classList.remove("hidden"); detail.replaceChildren(); const heading = document.createElement("div"); heading.className = "title"; heading.textContent = title; const body = document.createElement("pre"); body.textContent = JSON.stringify(value, null, 2); detail.append(heading, body); }
      function renderTabs() { const root = document.getElementById("tabs"); root.replaceChildren(); Object.entries(tabLabels).forEach(([id, label]) => { const button = document.createElement("button"); button.textContent = label; button.className = state.tab === id ? "active" : ""; button.onclick = () => { state.tab = id; clearDetail(); renderTabs(); loadTab(); }; root.append(button); }); }
      function selectedArgs() { return state.projectId ? { project_id: state.projectId } : {}; }
      async function selectProject(projectId) { state.projectId = projectId || null; clearDetail(); if (!state.projectId) { status.textContent = "Choose a project to inspect AiiDA."; content.innerHTML = ""; return; } status.textContent = "Preparing project runtime…"; try { await call("aiida_select_project", { project_id: state.projectId }); status.textContent = "Project selected."; await loadTab(); } catch (error) { showError(error); } }
      function showError(error) { status.innerHTML = "<span class='error'>Unable to load AiiDA data.</span>"; showDetail("Error", { message: error && (error.message || error.error) ? error.message || error.error : String(error) }); }
      function cards(rows, title, subtitle, onClick) { const grid = document.createElement("div"); grid.className = "grid"; rows.forEach((row, index) => { const item = document.createElement("article"); item.className = "item"; item.innerHTML = "<div class='title'></div><div class='muted'></div>"; item.children[0].textContent = title(row, index); item.children[1].textContent = subtitle(row, index); if (onClick) item.onclick = () => onClick(row); grid.append(item); }); return grid; }
      async function loadOverview() { const data = await call("aiida_status", selectedArgs()); const system = await call("aiida_system_info", selectedArgs()); const snapshot = payload(data), info = payload(system); content.replaceChildren(cards([{ label: "Worker", value: snapshot.status || snapshot.state || "unknown" }, { label: "Profile", value: snapshot.profile || snapshot.profile_name || "unknown" }, { label: "AiiDA", value: info.aiida_version || info.version || "available" }, { label: "Project", value: state.projects.find(p => p.id === state.projectId)?.name || state.projectId }], row => row.label, row => row.value)); showDetail("Runtime details", { status: snapshot, system: info }); }
      async function loadProcesses() { const result = payload(await call("aiida_recent_processes", { limit: 50, ...selectedArgs() })); const rows = asArray(result, "processes"); content.replaceChildren(cards(rows, row => `${text(row.process_label || row.process_type || "Process")} #${text(row.pk || row.id)}`, row => `${text(row.process_state || row.state || row.status)} · ${text(row.ctime || row.created, "")}`, async row => { const id = row.pk || row.id || row.uuid; try { const inspected = payload(await call("aiida_inspect_process", { identifier: String(id), ...selectedArgs() })); showDetail(`Process ${id}`, inspected); } catch (error) { showError(error); } })); status.textContent = `${rows.length} recent processes`; }
      async function loadNodes() { const result = payload(await call("aiida_recent_nodes", { limit: 100, ...selectedArgs() })); const rows = asArray(result, "nodes"); content.replaceChildren(cards(rows, row => `${text(row.label || row.node_type || "Node")} #${text(row.pk || row.id)}`, row => `${text(row.node_type || row.type)} · ${text(row.ctime || row.created, "")}`, row => showDetail(`Node ${text(row.pk || row.id)}`, row))); status.textContent = `${rows.length} recent nodes`; }
      async function loadResources() { const [resources, profiles] = await Promise.all([call("aiida_resources", selectedArgs()), call("aiida_profiles", selectedArgs())]); const value = { resources: payload(resources), profiles: payload(profiles) }; content.replaceChildren(); const card = document.createElement("article"); card.className = "card"; card.innerHTML = "<div class='title'>Configured resources</div><div class='muted'>Computers, codes, profiles, and plugins</div>"; card.onclick = () => showDetail("Resources", value); content.append(card); showDetail("Resources", value); status.textContent = "Resources loaded"; }
      async function loadWorkflows() { const result = payload(await call("aiida_workflow_catalog", selectedArgs())); const rows = asArray(result, "workflows"); content.replaceChildren(cards(rows, row => text(row.entry_point || row.name || row.label), row => text(row.description || row.package || row.builder_strategy, "AiiDA WorkChain"), async row => { const workchain = row.entry_point || row.name; if (!workchain) return; try { const spec = payload(await call("aiida_submission_spec", { workchain, ...selectedArgs() })); showDetail(`Submission spec: ${workchain}`, spec); } catch (error) { showError(error); } })); status.textContent = `${rows.length} workflows`; }
      function loadPreview() { content.innerHTML = ""; const form = document.createElement("form"); form.className = "card"; form.innerHTML = "<div class='title'>Structured submission preview</div><p class='muted'>This creates and validates a preview only. It never launches a calculation.</p><div class='form-row'><label>Mode<select name='mode'><option value='single'>single</option><option value='batch'>batch</option></select></label><label>WorkChain<input name='workchain' required placeholder='quantumespresso.pw.base'></label><label>Code<input name='code' required placeholder='pw@localhost'></label><label>Structure PK(s)<input name='structures' required placeholder='12 or 12,13'></label><button class='primary' type='submit'>Build preview</button></div>"; form.onsubmit = async event => { event.preventDefault(); const values = new FormData(form), mode = values.get("mode"), ids = String(values.get("structures")).split(",").map(v => Number(v.trim())).filter(Number.isInteger); const request = { mode, builder_strategy: "protocol", workchain: String(values.get("workchain")).trim(), code: String(values.get("code")).trim(), ...(mode === "single" ? { structure_pk: ids[0] } : { structure_pks: ids }) }; try { const preview = payload(await call("aiida_build_submission_preview", { request, ...selectedArgs() })); state.draft = preview; showDetail("Submission preview (not submitted)", preview); status.innerHTML = "<span class='success'>Preview built. It has not been submitted.</span>"; } catch (error) { showError(error); } }; content.append(form); }
      async function loadTab() { if (!state.projectId) return; status.textContent = "Loading…"; try { if (state.tab === "overview") await loadOverview(); else if (state.tab === "processes") await loadProcesses(); else if (state.tab === "nodes") await loadNodes(); else if (state.tab === "resources") await loadResources(); else if (state.tab === "workflows") await loadWorkflows(); else loadPreview(); } catch (error) { showError(error); } }
      async function loadProjects() { try { const result = payload(await call("aiida_list_projects")); state.projects = asArray(result, "projects"); const selected = result && result.selected_project_id; selector.replaceChildren(new Option("Choose an ARIS project…", "")); state.projects.forEach(project => selector.add(new Option(`${project.name} (${project.session_count || 0} sessions)`, project.id, false, project.id === selected))); if (selected) { selector.value = selected; await selectProject(selected); } else { status.textContent = state.projects.length ? "Choose a project to begin." : "No ARIS projects found."; } } catch (error) { showError(error); } }
      selector.onchange = () => selectProject(selector.value); document.getElementById("refresh").onclick = () => state.projectId ? loadTab() : loadProjects();
      window.addEventListener("message", event => { if (event.source !== window.parent || !event.data || event.data.jsonrpc !== "2.0") return; const message = event.data; if (message.id !== undefined && state.pending.has(message.id)) { const request = state.pending.get(message.id); state.pending.delete(message.id); message.error ? request.reject(message.error) : request.resolve(message.result); } });
      renderTabs(); call("ui/initialize", { protocolVersion: "2026-01-26", capabilities: {}, clientInfo: { name: "aiida-workspace", version: "1.0.0" } }).then(() => { window.parent.postMessage({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} }, "*"); loadProjects(); }).catch(() => loadProjects());
    </script>
  </body>
</html>
"""


__all__ = [
    "AIIDA_EXPLORER_HTML",
    "AIIDA_EXPLORER_RESOURCE_URI",
    "AIIDA_WORKSPACE_HTML",
    "AIIDA_WORKSPACE_RESOURCE_URI",
]
