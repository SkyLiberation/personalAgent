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
  last_reviewed_at?: string | null;
};

export type ReviewFeedbackOutcome = "remembered" | "forgotten" | "later";

export type ReviewFeedbackResponse = {
  ok: boolean;
  short_id: string;
  outcome: ReviewFeedbackOutcome;
  review_card_id?: string | null;
  delivery_id?: string | null;
  message: string;
  error?: string | null;
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

export type ResetDebugDataResponse = {
  deleted_notes: number;
  deleted_reviews: number;
  deleted_upload_files: number;
  deleted_graph_nodes: number;
  deleted_pending_actions: number;
  deleted_cross_session_artifacts: number;
  deleted_checkpoints: number;
  deleted_checkpoint_blobs: number;
  deleted_checkpoint_writes: number;
  deleted_checkpoint_migrations: number;
  truncated_postgres_tables: number;
  deleted_postgres_rows: number;
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

export function submitReviewFeedback(
  reviewCardId: string,
  outcome: ReviewFeedbackOutcome,
  userId = "default",
): Promise<ReviewFeedbackResponse> {
  return requestJson<ReviewFeedbackResponse>(
    `/api/review/cards/${encodeURIComponent(reviewCardId)}/feedback`,
    {
      method: "POST",
      body: JSON.stringify({ outcome, user_id: userId }),
    },
  );
}

export type GraphTopologyNode = {
  id: string;
  name: string;
  labels?: string[];
  summary?: string;
};

export type GraphTopologyLink = {
  source: string;
  target: string;
  fact: string;
  uuid?: string;
};

export type GraphTopology = {
  nodes: GraphTopologyNode[];
  links: GraphTopologyLink[];
  error?: string;
};

export function fetchGraphTopology(userId = "default"): Promise<GraphTopology> {
  return requestJson<GraphTopology>(`/api/graph/topology?user_id=${encodeURIComponent(userId)}`);
}

export type ExecutionStep = {
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
  output_label?: string;
  output_title?: string;
  output_preview?: string;
};

export type ConversationTurnRequest = {
  session_id: string;
  client_request_id: string;
  text: string;
  create_session: boolean;
  user_id: string;
};

type ConversationTurnIdentity = { turn_id: string; session_id: string };

export type ConversationTurnEvent =
  | ({ type: "status" | "pending" } & ConversationTurnIdentity)
  | ({ type: "done"; answer: string } & ConversationTurnIdentity)
  | { type: "answer_delta"; answer: string };

export class ConversationTurnError extends Error {
  constructor(readonly status: number, detail: unknown) {
    super(conversationErrorMessage(detail) ?? `对话请求失败（${status}）。`);
  }
}

function conversationErrorMessage(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
}

function decodeConversationEvent(frame: string): ConversationTurnEvent | undefined {
  const lines = frame.split(/\r?\n/);
  const type = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
  if (type !== "status" && type !== "answer_delta" && type !== "done" && type !== "pending" && type !== "error") {
    return;
  }
  const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
  const value: unknown = JSON.parse(data);
  if (value && typeof value === "object") {
    if (type === "error" && "status_code" in value && typeof value.status_code === "number") {
      throw new ConversationTurnError(value.status_code, "detail" in value ? value.detail : undefined);
    }
    const answer = "answer" in value && typeof value.answer === "string" ? value.answer : undefined;
    if (type === "answer_delta" && answer !== undefined) return { type, answer };
    if ("turn_id" in value && typeof value.turn_id === "string"
        && "session_id" in value && typeof value.session_id === "string") {
      const identity = { turn_id: value.turn_id, session_id: value.session_id };
      if (type === "status" || type === "pending") return { type, ...identity };
      if (type === "done" && answer !== undefined) return { type, ...identity, answer };
    }
  }
  throw new Error("对话服务返回了无效的流事件。");
}

export async function streamConversationTurn(
  request: ConversationTurnRequest,
  signal: AbortSignal,
  onEvent: (event: ConversationTurnEvent) => void,
): Promise<void> {
  const response = await fetch("/api/conversation/turns", {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new ConversationTurnError(response.status, error?.detail);
  }
  if (!response.headers.get("content-type")?.startsWith("text/event-stream") || !response.body) {
    throw new Error("对话服务未返回事件流。");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const event = decodeConversationEvent(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary[0].length);
        if (event) {
          onEvent(event);
          if (event.type === "done" || event.type === "pending") return;
        }
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
    }
    throw new Error("对话连接已中断，可以重试本轮。");
  } finally {
    await reader.cancel().catch(() => {});
  }
}

export async function steerConversationTurn(
  turnId: string,
  sessionId: string,
  request: { text: string; user_id: string; client_request_id: string },
): Promise<void> {
  const response = await fetch(`/api/conversation/turns/${encodeURIComponent(turnId)}/steer`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(request),
  });
  const value = await response.json().catch(() => null) as {
    detail?: unknown; turn_id?: unknown; session_id?: unknown; client_request_id?: unknown;
  } | null;
  if (!response.ok) throw new ConversationTurnError(response.status, value?.detail);
  if (response.status !== 202 || value?.turn_id !== turnId || value.session_id !== sessionId
      || value.client_request_id !== request.client_request_id) {
    throw new Error("对话服务返回了无效的补充指令回执。");
  }
}

export async function resumeConversationTurn(
  turnId: string,
  userId: string,
  signal: AbortSignal,
): Promise<Extract<ConversationTurnEvent, { type: "done" }>> {
  const response = await fetch(`/api/conversation/turns/${encodeURIComponent(turnId)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ user_id: userId }),
    signal,
  });
  const value = await response.json().catch(() => null) as {
    detail?: unknown;
    turn_id?: unknown;
    session_id?: unknown;
    message?: { content?: unknown };
  } | null;
  if (!response.ok) throw new ConversationTurnError(response.status, value?.detail);
  if (typeof value?.turn_id !== "string" || typeof value.session_id !== "string"
      || typeof value.message?.content !== "string") {
    throw new Error("对话服务返回了无效的恢复结果。");
  }
  return {
    type: "done",
    turn_id: value.turn_id,
    session_id: value.session_id,
    answer: value.message.content,
  };
}

export function uploadEntryFile(
  file: File,
  userId = "default",
): Promise<KnowledgeCapturedResource> {
  const body = new FormData();
  body.append("file", file);
  body.append("user_id", userId);
  return requestFormData<KnowledgeCapturedResource>("/api/knowledge/ingest-upload", {
    method: "POST",
    body,
  });
}

export type KnowledgeCapturedResource = {
  resource_ref: { resource_id: string } | null;
  ingest_result: {
    artifact: { artifact_id: string; text: string };
  };
};

export type ProjectReference = {
  project_id: string;
  tenant_id: string;
  user_id: string;
  state: string;
  title: string;
  goal: string;
};

export type InvestigationProjectView = {
  project_id: string;
  state: string;
  last_state_reason: string;
  waiting_reasons: Array<{ code?: string; message?: string }>;
  completion_report?: unknown;
};

export function fetchInvestigationProject(
  reference: ProjectReference,
): Promise<InvestigationProjectView> {
  const params = new URLSearchParams({
    tenant_id: reference.tenant_id,
    user_id: reference.user_id,
  });
  return requestJson<InvestigationProjectView>(
    `/api/investigation-projects/${encodeURIComponent(reference.project_id)}?${params.toString()}`,
  );
}

export function setInvestigationProjectPaused(
  reference: ProjectReference,
  paused: boolean,
): Promise<InvestigationProjectView> {
  return requestJson<InvestigationProjectView>(
    `/api/investigation-projects/${encodeURIComponent(reference.project_id)}/${paused ? "pause" : "resume"}`,
    {
      method: "POST",
      body: JSON.stringify({
        tenant_id: reference.tenant_id,
        user_id: reference.user_id,
      }),
    },
  );
}

export type KnowledgeGroundedAnswer = {
  answer: string;
  grounding_status: "supported" | "weak_evidence" | "unsupported";
};

export function askKnowledge(
  question: string,
  userId = "default",
): Promise<KnowledgeGroundedAnswer> {
  return requestJson<KnowledgeGroundedAnswer>("/api/knowledge/ask", {
    method: "POST",
    body: JSON.stringify({ question, user_id: userId }),
  });
}

export function retryGraphSync(noteId: string): Promise<GraphSyncResponse> {
  return requestJson<GraphSyncResponse>(`/api/notes/${encodeURIComponent(noteId)}/graph-sync`, {
    method: "POST",
  });
}

export function resetDebugData(): Promise<ResetDebugDataResponse> {
  return requestJson<ResetDebugDataResponse>("/api/debug/reset-database", {
    method: "POST",
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
  source?: "pending_action";
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
