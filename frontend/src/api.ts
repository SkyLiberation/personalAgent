export type Note = {
  id: string;
  user_id: string;
  source_type?: string;
  source_ref?: string | null;
  graph_sync_status?: "idle" | "pending" | "synced" | "failed";
  graph_sync_error?: string | null;
  title: string;
  content: string;
  summary: string;
  tags: string[];
  related_note_ids: string[];
  graph_episode_uuid?: string | null;
  entity_names?: string[];
  relation_facts?: string[];
  created_at: string;
  updated_at: string;
};

export type ReviewCard = {
  id: string;
  note_id: string;
  prompt: string;
  answer_hint: string;
  interval_days: number;
  due_at: string;
};

export type Citation = {
  note_id: string;
  title: string;
  snippet: string;
  relation_fact?: string | null;
};

export type DigestResponse = {
  message: string;
  recent_notes: Note[];
  due_reviews: ReviewCard[];
};

export type CaptureResponse = {
  note: Note;
  related_notes: Note[];
  review_card: ReviewCard | null;
};

export type AskResponse = {
  answer: string;
  citations: Citation[];
  matches: Note[];
  graph_enabled?: boolean;
  session_id?: string;
};

export type GraphSyncResponse = {
  note: Note;
  queued: boolean;
};

export type AskHistoryItem = {
  id: string;
  user_id: string;
  session_id: string;
  question: string;
  answer: string;
  citations: Citation[];
  graph_enabled: boolean;
  created_at: string;
};

export type AskHistoryResponse = {
  items: AskHistoryItem[];
};

export type UploadConflictResponse = {
  filename: string;
  exists: boolean;
  path: string;
};

export type ResetUserDataResponse = {
  user_id: string;
  deleted_notes: number;
  deleted_reviews: number;
  deleted_conversations: number;
  deleted_upload_files: number;
  deleted_ask_history: number;
  deleted_graph_episodes: number;
};

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

async function requestFormData<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

function requestFormDataWithProgress<T>(
  url: string,
  body: FormData,
  onProgress?: (progress: number) => void
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (!onProgress || !event.lengthComputable) {
        return;
      }
      const progress = Math.min(100, Math.round((event.loaded / event.total) * 100));
      onProgress(progress);
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as T);
        return;
      }
      const detail =
        xhr.response && typeof xhr.response === "object" && "detail" in xhr.response
          ? String((xhr.response as { detail?: unknown }).detail ?? "")
          : "";
      reject(new Error(detail || `Request failed: ${xhr.status}`));
    };

    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.send(body);
  });
}

export function fetchNotes(userId = "default"): Promise<Note[]> {
  return requestJson<Note[]>(`/api/notes?user_id=${encodeURIComponent(userId)}`);
}

export function fetchDigest(userId = "default"): Promise<DigestResponse> {
  return requestJson<DigestResponse>(`/api/digest?user_id=${encodeURIComponent(userId)}`);
}

export function fetchAskHistory(userId = "default", limit = 20, sessionId?: string): Promise<AskHistoryResponse> {
  const sessionQuery = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  return requestJson<AskHistoryResponse>(
    `/api/ask-history?user_id=${encodeURIComponent(userId)}&limit=${encodeURIComponent(String(limit))}${sessionQuery}`
  );
}

export function checkUploadConflict(filename: string): Promise<UploadConflictResponse> {
  return requestJson<UploadConflictResponse>(
    `/api/uploads/conflict?filename=${encodeURIComponent(filename)}`
  );
}

export function captureNote(
  text: string,
  userId = "default",
  sourceType: "text" | "link" = "text"
): Promise<CaptureResponse> {
  return requestJson<CaptureResponse>("/api/capture", {
    method: "POST",
    body: JSON.stringify({
      text,
      source_type: sourceType,
      user_id: userId,
    }),
  });
}

export function uploadCapture(
  file: File,
  userId = "default",
  overwrite = false,
  onProgress?: (progress: number) => void
): Promise<CaptureResponse> {
  const body = new FormData();
  body.append("file", file);
  body.append("user_id", userId);
  body.append("overwrite", overwrite ? "true" : "false");
  return requestFormDataWithProgress<CaptureResponse>("/api/capture/upload", body, onProgress);
}

export function askQuestion(question: string, userId = "default", sessionId = "default"): Promise<AskResponse> {
  return requestJson<AskResponse>("/api/ask", {
    method: "POST",
    body: JSON.stringify({
      question,
      user_id: userId,
      session_id: sessionId,
    }),
  });
}

export function buildAskStreamUrl(question: string, userId = "default", sessionId = "default"): string {
  const params = new URLSearchParams({
    question,
    user_id: userId,
    session_id: sessionId,
  });
  return `/api/ask/stream?${params.toString()}`;
}

export function retryGraphSync(noteId: string): Promise<GraphSyncResponse> {
  return requestJson<GraphSyncResponse>(`/api/notes/${encodeURIComponent(noteId)}/graph-sync`, {
    method: "POST",
  });
}

export function resetUserData(userId = "default"): Promise<ResetUserDataResponse> {
  return requestJson<ResetUserDataResponse>("/api/debug/reset-user-data", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
    }),
  });
}
