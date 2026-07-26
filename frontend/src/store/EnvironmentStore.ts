import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { ChatProject } from "@/types/aiida";
import type {
  EnvironmentInspectionCode,
  EnvironmentInspectionComputer,
  EnvironmentInspectionResponse,
  EnvironmentPluginGroups,
} from "@/types/aiida";

const API_BASE_URL = import.meta.env.DEV ? "http://localhost:8000" : "";
const FRONTEND_API_PREFIX = "/api/aiida/frontend";
export type EnvironmentInspectionStatus = "idle" | "loading" | "ready" | "error";
export type PythonPathSource = "auto" | "manual";
export type ProjectEnvironmentDefaultMode = "worker-default" | "project-auto";

export type EnvironmentState = {
  currentProjectPath: string | null;
  projectDefaultMode: ProjectEnvironmentDefaultMode;
  pythonPath: string | null;
  pythonPathSource: PythonPathSource;
  useWorkerDefault: boolean;
  inspectionStatus: EnvironmentInspectionStatus;
  inspection: EnvironmentInspectionResponse | null;
  availablePlugins: string[];
  availableCodes: EnvironmentInspectionCode[];
  availableComputers: EnvironmentInspectionComputer[];
  lastError: string | null;
  lastInspectedAt: string | null;
};

type EnvironmentInspectRequestPayload = {
  python_path: string | null;
  workspace_path: string | null;
  use_worker_default: boolean;
};

type EnvironmentStoreApi = {
  getState: () => EnvironmentState;
  subscribe: (listener: () => void) => () => void;
  setProjectContext: (project: ChatProject | null) => void;
  setUseWorkerDefault: (useWorkerDefault: boolean) => void;
  setPythonPath: (pythonPath: string | null) => void;
  resetPythonPath: () => void;
  refreshInspection: () => Promise<void>;
};

function normalizePath(value: string | null | undefined): string | null {
  const cleaned = String(value || "").trim();
  return cleaned || null;
}

function looksLikeWindowsPath(targetPath: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(targetPath) || targetPath.includes("\\");
}

function buildAutoPythonPath(projectPath: string | null): string | null {
  const normalized = normalizePath(projectPath);
  if (!normalized) {
    return null;
  }
  if (looksLikeWindowsPath(normalized)) {
    return `${normalized.replace(/[\\/]+$/, "")}\\.venv\\Scripts\\python.exe`;
  }
  return `${normalized.replace(/\/+$/, "")}/.venv/bin/python`;
}

function resolveErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }
  return "Environment inspection failed.";
}

function isMissingInterpreterError(error: unknown): boolean {
  return resolveErrorMessage(error).includes("Python interpreter not found");
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function normalizePluginGroups(
  rawValue: Partial<EnvironmentPluginGroups> | string[] | null | undefined,
): EnvironmentPluginGroups {
  if (Array.isArray(rawValue)) {
    return {
      calculations: uniqueSorted(rawValue.map((value) => String(value))),
      workflows: [],
      data: [],
    };
  }
  const groups = rawValue && typeof rawValue === "object" ? rawValue : {};
  const readGroup = (key: keyof EnvironmentPluginGroups): string[] => (
    Array.isArray(groups[key])
      ? uniqueSorted(groups[key]!.map((value) => String(value)))
      : []
  );
  return {
    calculations: readGroup("calculations"),
    workflows: readGroup("workflows"),
    data: readGroup("data"),
  };
}

function buildInspectionUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalized}`;
}

async function postInspectionRequest(
  path: string,
  payload: EnvironmentInspectRequestPayload,
): Promise<EnvironmentInspectionResponse> {
  const response = await fetch(buildInspectionUrl(path), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Environment inspect failed (${response.status})${body ? `: ${body}` : ""}`);
  }

  return (await response.json()) as EnvironmentInspectionResponse;
}

function normalizeInspectionResponse(
  rawValue: EnvironmentInspectionResponse,
  request: EnvironmentInspectRequestPayload,
): EnvironmentInspectionResponse {
  const pluginGroups = normalizePluginGroups(rawValue.plugin_groups ?? rawValue.plugins);
  const plugins = Array.isArray(rawValue.plugins)
    ? uniqueSorted(rawValue.plugins.map((value) => String(value)))
    : uniqueSorted([
        ...pluginGroups.calculations,
        ...pluginGroups.workflows,
        ...pluginGroups.data,
      ]);

  return {
    success: Boolean(rawValue.success),
    mode: rawValue.mode === "worker-default" || request.use_worker_default ? "worker-default" : "project",
    source: typeof rawValue.source === "string" && rawValue.source.trim() ? rawValue.source.trim() : "worker",
    python_path: normalizePath(rawValue.python_path ?? rawValue.python_interpreter_path ?? request.python_path),
    workspace_path: normalizePath(rawValue.workspace_path ?? request.workspace_path),
    python_interpreter_path: normalizePath(rawValue.python_interpreter_path ?? rawValue.python_path ?? request.python_path),
    python_version: typeof rawValue.python_version === "string" ? rawValue.python_version : null,
    aiida_core_version: typeof rawValue.aiida_core_version === "string" ? rawValue.aiida_core_version : null,
    profile: typeof rawValue.profile === "string" ? rawValue.profile : null,
    plugins,
    plugin_groups: pluginGroups,
    codes: Array.isArray(rawValue.codes) ? rawValue.codes : [],
    computers: Array.isArray(rawValue.computers) ? rawValue.computers : [],
    errors: Array.isArray(rawValue.errors) ? rawValue.errors : [],
    cached: Boolean(rawValue.cached),
    cached_at: typeof rawValue.cached_at === "string" ? rawValue.cached_at : null,
  };
}

function createInitialState(): EnvironmentState {
  return {
    currentProjectPath: null,
    projectDefaultMode: "worker-default",
    pythonPath: null,
    pythonPathSource: "auto",
    useWorkerDefault: false,
    inspectionStatus: "idle",
    inspection: null,
    availablePlugins: [],
    availableCodes: [],
    availableComputers: [],
    lastError: null,
    lastInspectedAt: null,
  };
}

function createEnvironmentStore(): EnvironmentStoreApi {
  let state = createInitialState();
  let inspectionToken = 0;
  const listeners = new Set<() => void>();

  const emit = () => {
    listeners.forEach((listener) => listener());
  };

  const setState = (nextState: EnvironmentState) => {
    state = nextState;
    emit();
  };

  const getInspectionRequestPayload = (snapshot: EnvironmentState): EnvironmentInspectRequestPayload => ({
    python_path: snapshot.useWorkerDefault ? null : normalizePath(snapshot.pythonPath),
    workspace_path: normalizePath(snapshot.currentProjectPath),
    use_worker_default: snapshot.useWorkerDefault,
  });

  const refreshInspection = async (): Promise<void> => {
    const snapshot = state;
    const request = getInspectionRequestPayload(snapshot);
    const token = ++inspectionToken;

    if (!request.use_worker_default && !request.python_path) {
      setState({
        ...snapshot,
        inspectionStatus: "error",
        inspection: null,
        availablePlugins: [],
        availableCodes: [],
        availableComputers: [],
        lastError: request.workspace_path
          ? `No project interpreter detected at ${buildAutoPythonPath(request.workspace_path)}`
          : "Select a project to derive a Python interpreter.",
        lastInspectedAt: new Date().toISOString(),
      });
      return;
    }

    setState({
      ...snapshot,
      inspectionStatus: "loading",
      lastError: null,
    });

    try {
      const payload = await postInspectionRequest(`${FRONTEND_API_PREFIX}/environment/inspect`, request);
      if (token !== inspectionToken) {
        return;
      }
      const inspection = normalizeInspectionResponse(payload, request);
      setState({
        ...snapshot,
        inspectionStatus: "ready",
        inspection,
        availablePlugins: inspection.plugins,
        availableCodes: inspection.codes,
        availableComputers: inspection.computers,
        lastError: null,
        lastInspectedAt: new Date().toISOString(),
      });
    } catch (error) {
      if (token !== inspectionToken) {
        return;
      }
      if (
        !request.use_worker_default
        && snapshot.pythonPathSource === "auto"
        && Boolean(request.python_path)
        && isMissingInterpreterError(error)
      ) {
        const fallbackRequest: EnvironmentInspectRequestPayload = {
          python_path: null,
          workspace_path: request.workspace_path,
          use_worker_default: true,
        };

        setState({
          ...snapshot,
          useWorkerDefault: true,
          inspectionStatus: "loading",
          lastError: null,
        });

        try {
          const fallbackPayload = await postInspectionRequest(`${FRONTEND_API_PREFIX}/environment/inspect`, fallbackRequest);
          if (token !== inspectionToken) {
            return;
          }
          const inspection = normalizeInspectionResponse(fallbackPayload, fallbackRequest);
          setState({
            ...snapshot,
            useWorkerDefault: true,
            inspectionStatus: "ready",
            inspection,
            availablePlugins: inspection.plugins,
            availableCodes: inspection.codes,
            availableComputers: inspection.computers,
            lastError: null,
            lastInspectedAt: new Date().toISOString(),
          });
          return;
        } catch (fallbackError) {
          if (token !== inspectionToken) {
            return;
          }
          setState({
            ...snapshot,
            useWorkerDefault: true,
            inspectionStatus: "error",
            inspection: null,
            availablePlugins: [],
            availableCodes: [],
            availableComputers: [],
            lastError: resolveErrorMessage(fallbackError),
            lastInspectedAt: new Date().toISOString(),
          });
          return;
        }
      }
      setState({
        ...snapshot,
        inspectionStatus: "error",
        inspection: null,
        availablePlugins: [],
        availableCodes: [],
        availableComputers: [],
        lastError: resolveErrorMessage(error),
        lastInspectedAt: new Date().toISOString(),
      });
    }
  };

  const updateProjectState = (project: ChatProject | null) => {
    const normalizedProjectPath = normalizePath(project?.root_path ?? null);
    const nextDefaultMode: ProjectEnvironmentDefaultMode =
      project?.environment_mode_default === "project-auto" ? "project-auto" : "worker-default";
    const shouldUseWorkerDefault = nextDefaultMode === "worker-default";
    const autoPythonPath = buildAutoPythonPath(normalizedProjectPath);
    const projectChanged = normalizedProjectPath !== state.currentProjectPath;
    const shouldResetToAuto = projectChanged || state.pythonPathSource === "auto";

    setState({
      ...state,
      currentProjectPath: normalizedProjectPath,
      projectDefaultMode: nextDefaultMode,
      pythonPath: shouldResetToAuto ? autoPythonPath : state.pythonPath,
      pythonPathSource: shouldResetToAuto ? "auto" : state.pythonPathSource,
      useWorkerDefault: shouldResetToAuto ? shouldUseWorkerDefault : state.useWorkerDefault,
    });
    void refreshInspection();
  };

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setProjectContext: (project) => {
      const normalizedProjectPath = normalizePath(project?.root_path ?? null);
      const nextDefaultMode: ProjectEnvironmentDefaultMode =
        project?.environment_mode_default === "project-auto" ? "project-auto" : "worker-default";
      const shouldUseWorkerDefault = nextDefaultMode === "worker-default";
      const autoPythonPath = buildAutoPythonPath(normalizedProjectPath);
      const nextPythonPath = state.pythonPathSource === "manual" && normalizedProjectPath === state.currentProjectPath
        ? state.pythonPath
        : autoPythonPath;
      const nextPythonSource = state.pythonPathSource === "manual" && normalizedProjectPath === state.currentProjectPath
        ? state.pythonPathSource
        : "auto";
      if (
        normalizedProjectPath === state.currentProjectPath
        && nextDefaultMode === state.projectDefaultMode
        && nextPythonPath === state.pythonPath
        && nextPythonSource === state.pythonPathSource
        && (nextPythonSource !== "auto" || shouldUseWorkerDefault === state.useWorkerDefault)
      ) {
        return;
      }
      updateProjectState(project);
    },
    setUseWorkerDefault: (useWorkerDefault) => {
      if (useWorkerDefault === state.useWorkerDefault) {
        return;
      }
      setState({
        ...state,
        useWorkerDefault,
      });
      void refreshInspection();
    },
    setPythonPath: (pythonPath) => {
      const normalizedPythonPath = normalizePath(pythonPath);
      if (normalizedPythonPath === state.pythonPath && state.pythonPathSource === "manual") {
        return;
      }
      setState({
        ...state,
        pythonPath: normalizedPythonPath,
        pythonPathSource: "manual",
      });
      void refreshInspection();
    },
    resetPythonPath: () => {
      const autoPythonPath = buildAutoPythonPath(state.currentProjectPath);
      if (state.pythonPath === autoPythonPath && state.pythonPathSource === "auto") {
        return;
      }
      setState({
        ...state,
        pythonPath: autoPythonPath,
        pythonPathSource: "auto",
      });
      void refreshInspection();
    },
    refreshInspection,
  };
}

const environmentStore = createEnvironmentStore();
const EnvironmentContext = createContext<EnvironmentStoreApi>(environmentStore);

export function EnvironmentStoreProvider({ children }: { children: ReactNode }) {
  return createElement(EnvironmentContext.Provider, { value: environmentStore }, children);
}

export function useEnvironmentStore<T>(selector: (state: EnvironmentState) => T): T {
  const store = useContext(EnvironmentContext);
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.getState()),
    () => selector(store.getState()),
  );
}

export function useEnvironmentActions() {
  const store = useContext(EnvironmentContext);
  return useMemo(
    () => ({
      setProjectContext: store.setProjectContext,
      setUseWorkerDefault: store.setUseWorkerDefault,
      setPythonPath: store.setPythonPath,
      resetPythonPath: store.resetPythonPath,
      refreshInspection: store.refreshInspection,
    }),
    [store],
  );
}

export function useProjectEnvironmentSync(project: ChatProject | null): void {
  const { setProjectContext } = useEnvironmentActions();
  useEffect(() => {
    setProjectContext(project);
  }, [project, setProjectContext]);
}

export function getEnvironmentState(): EnvironmentState {
  return environmentStore.getState();
}
