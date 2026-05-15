const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

type RequestOptions = RequestInit & {
  json?: unknown;
};

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
    body: options.json === undefined ? options.body : JSON.stringify(options.json)
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "API error");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export type User = {
  id: string;
  email: string;
  display_name?: string | null;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatSource = {
  document_id: string;
  title: string;
  filename?: string | null;
  distance?: number | null;
};

export type Message = {
  id: string;
  role: "system" | "user" | "assistant";
  content: string;
  model?: string | null;
  created_at: string;
  sources?: ChatSource[];
};

export type ConversationDetail = Conversation & {
  messages: Message[];
};

export type OllamaModel = {
  name: string;
  selected: boolean;
};

export type UserSettings = {
  id: string;
  user_id: string;
  ocr_processing_model: string | null;
  rag_source_strategy: "best_band" | "top_n";
  rag_best_band: number;
  rag_top_n: number;
  created_at: string;
  updated_at: string;
};

export type DocumentItem = {
  id: string;
  filename: string;
  mime_type: string;
  status: "uploaded" | "processing" | "processed" | "failed";
  created_at: string;
  updated_at: string;
};

export type DocumentFile = {
  id: string;
  document_id: string;
  filename: string;
  mime_type: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type OcrResult = {
  id: string;
  document_id: string;
  raw_text: string;
  normalized_text: string;
  rag_text: string;
  metadata_json: Record<string, unknown>;
  language: string;
  page_count: number;
  engine: string;
  created_at: string;
  updated_at: string;
};

export type DocumentExtraction = {
  id: string;
  document_id: string;
  structured_json: Record<string, unknown>;
  summary: string;
  review_status: string;
  model: string;
  raw_response: string;
  created_at: string;
  updated_at: string;
};

export async function getMe() {
  return api<User>("/users/me");
}

export async function register(email: string, password: string) {
  return api<User>("/auth/register", {
    method: "POST",
    json: { email, password }
  });
}

export async function login(username: string, password: string) {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);
  return api<void>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form
  });
}

export async function logout() {
  return api<void>("/auth/logout", { method: "POST" });
}

export async function listDocuments() {
  return api<DocumentItem[]>("/documents");
}

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<DocumentItem>("/documents", {
    method: "POST",
    body: form
  });
}

export async function listDocumentFiles(documentId: string) {
  return api<DocumentFile[]>(`/documents/${documentId}/files`);
}

export async function addDocumentFile(documentId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<DocumentFile>(`/documents/${documentId}/files`, {
    method: "POST",
    body: form
  });
}

export async function deleteDocumentFile(documentId: string, fileId: string) {
  return api<void>(`/documents/${documentId}/files/${fileId}`, { method: "DELETE" });
}

export async function deleteDocument(documentId: string) {
  return api<void>(`/documents/${documentId}`, { method: "DELETE" });
}

export async function getDocumentOcr(documentId: string) {
  return api<OcrResult>(`/documents/${documentId}/ocr`);
}

export async function runDocumentOcr(documentId: string) {
  return api<{ id: string; status: string; error_message?: string | null }>(`/documents/${documentId}/ocr/run`, {
    method: "POST"
  });
}

export async function getDocumentExtraction(documentId: string) {
  return api<DocumentExtraction>(`/documents/${documentId}/extraction`);
}

export async function runDocumentExtraction(documentId: string) {
  return api<{ id: string; status: string; error_message?: string | null }>(
    `/documents/${documentId}/extraction/run`,
    {
      method: "POST"
    }
  );
}

export async function updateDocumentExtraction(documentId: string, structuredJson: Record<string, unknown>) {
  return api<DocumentExtraction>(`/documents/${documentId}/extraction`, {
    method: "PUT",
    json: { structured_json: structuredJson }
  });
}

export async function createConversation(title = "Nova konverzace") {
  return api<ConversationDetail>("/chat/conversations", {
    method: "POST",
    json: { title }
  });
}

export async function listConversations() {
  return api<Conversation[]>("/chat/conversations");
}

export async function getConversation(id: string) {
  return api<ConversationDetail>(`/chat/conversations/${id}`);
}

export async function deleteConversation(id: string) {
  return api<void>(`/chat/conversations/${id}`, { method: "DELETE" });
}

export async function listModels() {
  return api<OllamaModel[]>("/chat/models");
}

export async function getUserSettings() {
  return api<UserSettings>("/settings");
}

export async function updateUserSettings(payload: {
  ocr_processing_model: string | null;
  rag_source_strategy: "best_band" | "top_n";
  rag_best_band: number;
  rag_top_n: number;
}) {
  return api<UserSettings>("/settings", {
    method: "PUT",
    json: payload
  });
}

export async function sendMessage(conversationId: string, content: string, model?: string) {
  return api<{ conversation: ConversationDetail; assistant_message: Message }>(
    `/chat/conversations/${conversationId}/messages`,
    {
      method: "POST",
      json: { content, model }
    }
  );
}
