import type {
  User,
  Project,
  ProjectListItem,
  ChatResponse,
  Conversation,
  CallSpec,
  GeneratedDoc,
  ProjectDocuments,
  CyranoEvaluation,
} from "./types";

const API_BASE = "/api";

/**
 * Typed HTTP error that carries the response status code alongside the
 * human-readable message coming from the backend's ``detail`` field.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Users
export const createUser = (data: { name: string; email: string; organization?: string; sector?: string; territory?: string }) =>
  request<User>("/users/", { method: "POST", body: JSON.stringify(data) });

export const getUser = (id: string) => request<User>(`/users/${id}`);

export const updateUser = (id: string, data: Partial<User>) =>
  request<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(data) });

// Projects
export const createProject = (data: { title: string; user_id: string; language?: string }) =>
  request<Project>("/projects/", { method: "POST", body: JSON.stringify(data) });

export const listProjects = (userId: string) =>
  request<ProjectListItem[]>(`/projects/?user_id=${userId}`);

export const getProject = (id: string) => request<Project>(`/projects/${id}`);

export const updateProject = (id: string, data: Partial<Project>) =>
  request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteProject = (id: string) =>
  request<void>(`/projects/${id}`, { method: "DELETE" });

// Chat
export const sendMessage = (data: {
  user_id: string;
  message: string;
  conversation_id?: string;
  project_id?: string;
}) => request<ChatResponse>("/chat/", { method: "POST", body: JSON.stringify(data) });

export async function sendMessageStream(
  data: {
    user_id: string;
    message: string;
    conversation_id?: string;
    project_id?: string;
  },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
    signal,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Request failed");
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        const payload = trimmed.slice(6);
        if (payload === "[DONE]") return;
        try {
          const event = JSON.parse(payload);
          onEvent(event);
        } catch {
          // skip malformed JSON
        }
      }
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}

export type StreamEvent =
  | { type: "meta"; conversation_id: string }
  | { type: "delta"; content: string }
  | { type: "tool"; name: string; status: string }
  | { type: "done"; conversation_id: string; message_id: string; tool_calls: unknown; cyrano_score: number | null }
  | { type: "error"; content: string };

export const listConversations = (userId: string) =>
  request<Conversation[]>(`/chat/conversations/${userId}`);

export const getConversation = (userId: string, conversationId: string) =>
  request<Conversation>(`/chat/conversations/${userId}/${conversationId}`);

export const deleteConversation = (userId: string, conversationId: string) =>
  request<void>(`/chat/conversations/${userId}/${conversationId}`, { method: "DELETE" });

export const saveConversation = (userId: string, conversationId: string, projectId?: string) =>
  request<{ id: string; filename: string; version: number; message: string }>(
    `/chat/conversations/${userId}/${conversationId}/save${projectId ? `?project_id=${projectId}` : ''}`,
    { method: "POST" },
  );

// Call Specs
export const createCallSpec = (data: { title: string; source_url?: string }) =>
  request<CallSpec>("/calls/", { method: "POST", body: JSON.stringify(data) });

export const listCallSpecs = () => request<CallSpec[]>("/calls/");

export const uploadCallDocument = async (callSpecId: string, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/calls/${callSpecId}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
};

// Documents
export const listProjectDocuments = (projectId: string) =>
  request<GeneratedDoc[]>(`/documents/project/${projectId}`);

export const listAllProjectDocuments = (projectId: string) =>
  request<ProjectDocuments>(`/documents/project/${projectId}/all`);

export const downloadDocument = (documentId: string) =>
  `${API_BASE}/documents/${documentId}/download`;

// Cyrano evaluations
export const listCyranoEvaluations = (projectId: string) =>
  request<CyranoEvaluation[]>(`/projects/${projectId}/evaluations`);

export const deleteDocument = (documentId: string) =>
  request<void>(`/documents/${documentId}`, { method: "DELETE" });

export const uploadDocument = async (projectId: string, userId: string, file: File): Promise<UploadedDocument> => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("project_id", projectId);
  formData.append("user_id", userId);
  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Upload failed");
  }
  return res.json();
};

/**
 * Polls until the uploaded document reaches "indexed" (or "failed") status.
 * Resolves as soon as indexing completes or the timeout expires.
 * Returns the final indexing_status.
 */
export async function waitForDocumentIndexed(
  projectId: string,
  documentId: string,
  timeoutMs = 120_000,
  intervalMs = 3_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const docs = await listAllProjectDocuments(projectId);
      const doc = docs.uploaded.find((d) => d.id === documentId);
      if (doc && doc.indexing_status !== "pending") {
        return doc.indexing_status;
      }
    } catch {
      // ignore transient errors, keep polling
    }
  }
  return "timeout";
}

export const retryDocumentIndexing = (documentId: string) =>
  request<{ status: string; document_id: string }>(`/documents/${documentId}/retry-indexing`, {
    method: "POST",
  });
