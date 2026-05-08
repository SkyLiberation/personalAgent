export type Note = {
  id: string;
  user_id: string;
  source_type?: string;
  source_ref?: string | null;
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

export function fetchNotes(userId = "default"): Promise<Note[]> {
  return requestJson<Note[]>(`/api/notes?user_id=${encodeURIComponent(userId)}`);
}

export function fetchDigest(userId = "default"): Promise<DigestResponse> {
  return requestJson<DigestResponse>(`/api/digest?user_id=${encodeURIComponent(userId)}`);
}

export function captureNote(text: string, userId = "default"): Promise<CaptureResponse> {
  return requestJson<CaptureResponse>("/api/capture", {
    method: "POST",
    body: JSON.stringify({
      text,
      source_type: "text",
      user_id: userId,
    }),
  });
}

export function uploadCapture(file: File, userId = "default"): Promise<CaptureResponse> {
  const body = new FormData();
  body.append("file", file);
  body.append("user_id", userId);
  return requestFormData<CaptureResponse>("/api/capture/upload", {
    method: "POST",
    body,
  });
}

export function askQuestion(question: string, userId = "default"): Promise<AskResponse> {
  return requestJson<AskResponse>("/api/ask", {
    method: "POST",
    body: JSON.stringify({
      question,
      user_id: userId,
    }),
  });
}
