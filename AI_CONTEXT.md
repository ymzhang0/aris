# ARIS Architecture & Code Review Context

## Overview
This document serves as context transfer for agents working across different machines, preserving the review of the ARIS architecture.

## 1. Core Architecture: Brain-Body Split
ARIS operates as the **Brain**. It communicates with the AiiDA-Worker (**Body**) entirely via REST APIs.
**Review finding**: ARIS application code does not import the AiiDA runtime.
AiiDA operations are delegated to the worker over HTTP. Python snippets sent to
the worker may import `aiida` because they execute in the compute environment.

## 2. Key Design Patterns Analyzed

### Presenter Pattern (Demonstration Layer)
**Location:** `src/aris_apps/aiida/presenters/` (`node_view.py`, `workflow_view.py`)
**Implementation:** Takes raw JSON payloads returned by the Worker's API and recursively formats/ flattens them for the React frontend. It handles previews, link dereferencing, and stripping complex nested attributes into primitive JSON dictionaries.
- **Dual Link Support:** Enriches both `inputs`/`outputs` (Verbose provenance) and `direct_inputs`/`direct_outputs` (Concise port-based) payloads for presentation.

### Bridge/Proxy Pattern
**Location:** `src/aris_apps/aiida/client.py`
**Implementation:** Wraps all `httpx` logic dynamically. It implements connection state caching, infrastructure introspection (counting codes/computers), connection offline awareness (`BridgeOfflineError`), and error payload normalization (`_extract_error_payload`).

### Registry & Analysis Integration (Agent Capability Growth)
**Location:** `src/aris_apps/aiida/agent/tools.py`, `researcher.py`
**Implementation:** ARIS interacts with the Worker's `core.scripts` and `repository/analysis/` via the REST bridge. The agent can execute standardized analysis modules (for example `run_born`) on the worker to retrieve complex physical insights without implementing the parsing logic locally. This preserves the Brain-Body split while enabling sophisticated scientific reasoning.

### Observer Pattern (Streaming)
**Location:** `src/aris_apps/aiida/router.py`, `deps.py` (`log_step`)
**Implementation:** Chat uses the AG-UI event schema over an SSE transport.
Process, infrastructure, group, and log feeds also use SSE for live updates.

## Data Flow
User -> React Frontend -> FastAPI ARIS Routers -> ARIS Agent -> Tool Call -> `AiiDAWorkerClient` -> AiiDA-Worker REST API -> ARIS Presenter -> SSE/JSON Frontend Render.

## 3. Frontend Architecture Insights
### Submission Review & Draft Builders
**Location:** `frontend/src/components/dashboard/submission-modal.tsx`, `process-detail-drawer.tsx`
**Implementation:** The submission UI dynamically reads AiiDA Builder outputs. For WorkChains that wrap one or more child calculations, specific port parameters like `metadata.options` (e.g., `workdir`, `account`, `resources`) may need to be mapped into nested child namespaces instead of the root directory. The mapping should always come from the actual builder/spec shape returned by the worker rather than plugin-specific assumptions.
- **Process Detail Dual-View:** `ProcessDetailDrawer` and `ProcessTreeNodeView` implement a "Verbose Mode" toggle. By default, they display `direct_inputs` (clean port names) and fallback to the full provenance `inputs` graph when toggled.
- **State management:** Form state hooks relying on `metadata` or `inputs` (like global code inheritance) require stable references, avoiding immediate resets upon edits.
