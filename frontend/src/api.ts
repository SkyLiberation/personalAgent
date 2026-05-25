export type GraphNodeRef = {
  uuid: string;
  name: string;
  labels?: string[];
  summary?: string;
};

export type GraphEdgeRef = {
  uuid: string;
  fact: string;
  source_node_uuid?: string;
  target_node_uuid?: string;
  source_node_name?: string;
  target_node_name?: string;
  episodes?: string[];
};

export type GraphFactRef = {
  fact: string;
  edge_uuid?: string;
  source_node_name?: string;
  target_node_name?: string;
  episode_uuids?: string[];
};

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
  graph_node_refs?: GraphNodeRef[];
  graph_edge_refs?: GraphEdgeRef[];
  graph_fact_refs?: GraphFactRef[];
  parent_note_id?: string | null;
  chunk_index?: number | null;
  source_span?: string | null;
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

export type ResetUserDataResponse = {
  user_id: string;
  deleted_notes: number;
  deleted_reviews: number;
  deleted_conversations: number;
  deleted_upload_files: number;
  deleted_ask_history: number;
  deleted_graph_episodes: number;
};

const API_KEY_STORAGE_KEY = "personal-agent-api-key";

let _cachedApiKey: string | null = null;

export function getApiKey(): string | null {
  if (_cachedApiKey !== null) {
    return _cachedApiKey || null;
  }
  try {
    _cachedApiKey = localStorage.getItem(API_KEY_STORAGE_KEY) || "";
  } catch {
    _cachedApiKey = "";
  }
  return _cachedApiKey || null;
}

export function setApiKey(key: string): void {
  _cachedApiKey = key;
  try {
    if (key) {
      localStorage.setItem(API_KEY_STORAGE_KEY, key);
    } else {
      localStorage.removeItem(API_KEY_STORAGE_KEY);
    }
  } catch {
    // localStorage unavailable
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  if (!key) return {};
  return { "X-API-Key": key };
}

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
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
  const response = await fetch(input, {
    headers: {
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
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

export type PlanStep = {
  step_id: string;
  action_type: string;
  description: string;
  tool_name?: string | null;
  tool_input?: Record<string, unknown>;
  depends_on?: string[];
  expected_output?: string;
  success_criteria?: string;
  risk_level?: string;
  requires_confirmation?: boolean;
  on_failure?: string;
  status: string;
  retry_count?: number;
  validation_warnings?: string[];
};

export type EntryPendingConfirmation = {
  kind?: string;
  step_id?: string;
  action_type?: string;
  action_id?: string | null;
  token?: string | null;
  note_id?: string | null;
  title?: string;
  summary?: string;
  message?: string;
  original_text?: string;
  options?: Array<{ id: string; label: string; prompt?: string }>;
  [key: string]: unknown;
};

export type EntryResponse = {
  intent: string;
  reason: string;
  reply_text: string;
  plan_steps?: PlanStep[];
  execution_trace?: string[];
  run_id?: string | null;
  pending_confirmation?: EntryPendingConfirmation | null;
  run_status?: "completed" | "waiting_confirmation" | string | null;
  capture_result: {
    note: Note;
    related_notes: Note[];
    review_card: ReviewCard | null;
    graph_enabled: boolean;
  } | null;
  ask_result: {
    answer: string;
    citations: Citation[];
    matches: Note[];
    graph_enabled: boolean;
    session_id: string;
  } | null;
};

export type EntryRunSnapshot = {
  run_id: string;
  thread_id: string;
  user_id: string;
  session_id: string;
  status: string;
  intent: string;
  entry_text: string;
  plan_steps: PlanStep[];
  execution_trace: string[];
  answer?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type EntryRunSnapshotResponse = {
  items: EntryRunSnapshot[];
};

export function fetchEntryRuns(
  userId = "default",
  limit = 100,
): Promise<EntryRunSnapshotResponse> {
  return requestJson<EntryRunSnapshotResponse>(
    `/api/entry/runs?user_id=${encodeURIComponent(userId)}&limit=${encodeURIComponent(String(limit))}`
  );
}

export function resumeEntryRun(
  runId: string,
  decision: "confirm" | "reject" | "clarify",
  userId = "default",
  text = "",
  optionId = ""
): Promise<EntryResponse> {
  return requestJson<EntryResponse>(`/api/entry/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    body: JSON.stringify({ decision, user_id: userId, text, option_id: optionId }),
  });
}

export function buildEntryStreamUrl(text: string, userId = "default", sessionId = "default"): string {
  const params = new URLSearchParams({
    text,
    user_id: userId,
    session_id: sessionId,
  });
  const key = getApiKey();
  if (key) {
    params.set("api_key", key);
  }
  return `/api/entry/stream?${params.toString()}`;
}

export function uploadEntryFile(
  file: File,
  userId = "default",
  sessionId = "default",
  text?: string
): Promise<EntryResponse> {
  const body = new FormData();
  body.append("file", file);
  body.append("user_id", userId);
  body.append("session_id", sessionId);
  if (text) {
    body.append("text", text);
  }
  return requestFormData<EntryResponse>("/api/entry/upload", {
    method: "POST",
    body,
  });
}

export function searchAskHistory(
  query: string,
  userId = "default",
  limit = 20,
  sessionId?: string
): Promise<AskHistoryResponse> {
  const sessionQuery = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  return requestJson<AskHistoryResponse>(
    `/api/ask-history/search?q=${encodeURIComponent(query)}&user_id=${encodeURIComponent(userId)}&limit=${encodeURIComponent(String(limit))}${sessionQuery}`
  );
}

export function deleteAskHistoryRecord(
  recordId: string,
  userId = "default"
): Promise<{ ok: boolean; deleted_id: string }> {
  return requestJson<{ ok: boolean; deleted_id: string }>(
    `/api/ask-history/${encodeURIComponent(recordId)}?user_id=${encodeURIComponent(userId)}`,
    { method: "DELETE" }
  );
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

// ---- Pending Actions (HITL) ----

export type PendingActionItem = {
  id: string;
  user_id: string;
  action_type: string;
  target_id: string;
  title: string;
  description: string;
  status: "pending" | "confirmed" | "rejected" | "expired" | "executed";
  payload?: Record<string, unknown>;
  token?: string;
  source?: "pending_action" | "langgraph_run";
  run_id?: string;
  local_history_id?: string;
  pending_confirmation?: EntryPendingConfirmation;
  created_at: string;
  expires_at: string;
  resolved_at: string | null;
  audit_log?: Array<{ timestamp: string; event: string; actor: string; detail: string }>;
};

export type PendingActionsResponse = {
  items: PendingActionItem[];
};

export function fetchPendingActions(
  userId = "default",
  status?: string
): Promise<PendingActionsResponse> {
  const statusQuery = status ? `&status=${encodeURIComponent(status)}` : "";
  return requestJson<PendingActionsResponse>(
    `/api/pending-actions?user_id=${encodeURIComponent(userId)}${statusQuery}`
  );
}

export function confirmPendingAction(
  actionId: string,
  token: string,
  userId = "default"
): Promise<{ ok: boolean; detail?: string }> {
  return requestJson<{ ok: boolean; detail?: string }>(
    `/api/pending-actions/${encodeURIComponent(actionId)}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ token, user_id: userId }),
    }
  );
}

export function rejectPendingAction(
  actionId: string,
  userId = "default",
  reason = ""
): Promise<{ ok: boolean; detail?: string }> {
  return requestJson<{ ok: boolean; detail?: string }>(
    `/api/pending-actions/${encodeURIComponent(actionId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ user_id: userId, reason }),
    }
  );
}
