import { API_BASE_URL } from "./index";

async function fetchProjectApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `Project request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export interface ProjectAiiDAConfig {
  enabled: boolean;
  profile: string;
  group_uuid: string | null;
  group_label: string | null;
  status: string;
}

export interface ProjectRuntimeConfig {
  python_interpreter: string | null;
}

export interface Project {
  project_id: string;
  name: string;
  canonical_path: string;
  created_at: string;
  updated_at: string;
  last_opened_at: string;
  aiida: ProjectAiiDAConfig;
  runtime: ProjectRuntimeConfig;
  is_legacy_unbound: boolean;
}

export interface CreateProjectRequest {
  name: string;
  folder_path: string;
  aiida_enabled?: boolean;
  aiida_profile?: string;
}

export interface LoadProjectRequest {
  folder_path: string;
}

export interface RenameProjectRequest {
  new_name: string;
}

export interface RelinkGroupRequest {
  group_uuid: string;
}

export const projectsApi = {
  listProjects: () => fetchProjectApi<Project[]>("/api/projects"),

  getProject: (projectId: string) => fetchProjectApi<Project>(`/api/projects/${projectId}`),

  createProject: (req: CreateProjectRequest) =>
    fetchProjectApi<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  loadProject: (req: LoadProjectRequest) =>
    fetchProjectApi<Project>("/api/projects/load", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  renameProject: (projectId: string, req: RenameProjectRequest) =>
    fetchProjectApi<Project>(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    }),

  removeProjectRegistration: (projectId: string) =>
    fetchProjectApi<{ status: string }>(`/api/projects/${projectId}/registration`, {
      method: "DELETE",
    }),

  relinkProjectGroup: (projectId: string, req: RelinkGroupRequest) =>
    fetchProjectApi<Project>(`/api/projects/${projectId}/relink_group`, {
      method: "POST",
      body: JSON.stringify(req),
    }),
};
