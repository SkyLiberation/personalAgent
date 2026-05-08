import { FormEvent, useEffect, useRef, useState, useTransition } from "react";
import {
  buildAskStreamUrl,
  captureNote,
  fetchAskHistory,
  fetchDigest,
  fetchNotes,
  retryGraphSync,
  uploadCapture,
  type AskHistoryItem,
  type AskResponse,
  type Citation,
  type DigestResponse,
  type Note,
} from "./api";

const USER_ID = "default";

type TabId =
  | "capture"
  | "ask"
  | "entity"
  | "relation"
  | "digest"
  | "timeline"
  | "memory";

type EntityStat = {
  name: string;
  count: number;
  latestAt: string;
};

type RelationView = {
  fact: string;
  source: string;
  relation: string;
  target: string;
  count: number;
  latestAt: string;
};

type TimelineEvent = {
  id: string;
  title: string;
  createdAt: string;
  summary: string;
  entityNames: string[];
  relationFacts: string[];
};

type AskHistoryView = AskHistoryItem & {
  status: "streaming" | "done" | "error";
  error?: string;
};

const TABS: Array<{ id: TabId; label: string; kicker: string }> = [
  { id: "capture", label: "Capture", kicker: "Ingest" },
  { id: "ask", label: "Ask", kicker: "Dialog" },
  { id: "entity", label: "Entity Graph", kicker: "Map" },
  { id: "relation", label: "Relation Graph", kicker: "Links" },
  { id: "digest", label: "Digest", kicker: "Review" },
  { id: "timeline", label: "Timeline", kicker: "Flow" },
  { id: "memory", label: "Memory", kicker: "Archive" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("ask");
  const [captureText, setCaptureText] = useState("");
  const [captureFile, setCaptureFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [status, setStatus] = useState("Agent is warming up.");
  const [askHistory, setAskHistory] = useState<AskHistoryView[]>([]);
  const [selectedAskId, setSelectedAskId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    void refreshAll();

    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

  async function refreshAll() {
    setStatus("Refreshing memory timeline...");
    try {
      const [noteItems, digestResult, askHistoryResult] = await Promise.all([
        fetchNotes(USER_ID),
        fetchDigest(USER_ID),
        fetchAskHistory(USER_ID),
      ]);
      setNotes(noteItems);
      setDigest(digestResult);
      const historyItems = askHistoryResult.items.map((item) => ({
        ...item,
        status: "done" as const,
      }));
      setAskHistory(historyItems);
      setSelectedAskId((current) => current ?? historyItems[0]?.id ?? null);
      setStatus("Knowledge base is ready.");
    } catch (error) {
      console.error(error);
      setStatus("Backend not reachable yet. Start FastAPI and reload.");
    }
  }

  async function onCapture(event: FormEvent) {
    event.preventDefault();
    if (!captureText.trim()) {
      return;
    }

    startTransition(async () => {
      setStatus("Capturing and connecting your note...");
      try {
        await captureNote(captureText.trim(), USER_ID);
        setCaptureText("");
        await refreshAll();
        setStatus("New note captured and linked.");
      } catch (error) {
        console.error(error);
        setStatus("Capture failed. Please check the backend logs.");
      }
    });
  }

  function onAsk(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }

    eventSourceRef.current?.close();
    const prompt = question.trim();
    const historyItem: AskHistoryView = {
      id: crypto.randomUUID(),
      user_id: USER_ID,
      question: prompt,
      answer: "",
      citations: [],
      graph_enabled: false,
      created_at: new Date().toISOString(),
      status: "streaming",
    };

    setActiveTab("ask");
    setQuestion("");
    setSelectedAskId(historyItem.id);
    setAskHistory((current) => [historyItem, ...current].slice(0, 20));
    setStatus("Searching your personal memory...");

    const source = new EventSource(buildAskStreamUrl(prompt, USER_ID));
    eventSourceRef.current = source;

    source.addEventListener("status", (streamEvent) => {
      const payload = parseSsePayload<{ message?: string }>(streamEvent);
      setStatus(payload.message ?? "Streaming answer...");
    });

    source.addEventListener("metadata", (streamEvent) => {
      const payload = parseSsePayload<{
        citations?: Citation[];
        graph_enabled?: boolean;
      }>(streamEvent);
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? {
                ...item,
                citations: payload.citations ?? item.citations,
                graph_enabled: payload.graph_enabled ?? item.graph_enabled,
              }
            : item
        )
      );
    });

    source.addEventListener("answer_delta", (streamEvent) => {
      const payload = parseSsePayload<{ answer?: string }>(streamEvent);
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? {
                ...item,
                answer: payload.answer ?? item.answer,
              }
            : item
        )
      );
    });

    source.addEventListener("done", (streamEvent) => {
      const payload = parseSsePayload<AskResponse>(streamEvent);
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? {
                ...item,
                answer: payload.answer ?? item.answer,
                citations: payload.citations ?? item.citations,
                graph_enabled: payload.graph_enabled ?? item.graph_enabled,
                status: "done",
              }
            : item
        )
      );
      setStatus("Answer generated from your notes.");
      source.close();
      eventSourceRef.current = null;
      void refreshAskHistorySelection();
    });

    source.onerror = () => {
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? {
                ...item,
                status: "error",
                error: "Stream interrupted. Please check the backend logs and retry.",
              }
            : item
        )
      );
      setStatus("Question failed. Please check the backend logs.");
      source.close();
      eventSourceRef.current = null;
    };
  }

  async function refreshAskHistorySelection() {
    try {
      const response = await fetchAskHistory(USER_ID);
      const items = response.items.map((item) => ({
        ...item,
        status: "done" as const,
      }));
      setAskHistory(items);
      setSelectedAskId((current) => (current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null));
    } catch (error) {
      console.error(error);
    }
  }

  async function onUpload(event: FormEvent) {
    event.preventDefault();
    if (!captureFile) {
      return;
    }

    startTransition(async () => {
      setStatus(`Uploading ${captureFile.name} into memory...`);
      try {
        await uploadCapture(captureFile, USER_ID);
        setCaptureFile(null);
        await refreshAll();
        setStatus("Uploaded file captured. Graph sync will continue in the background.");
      } catch (error) {
        console.error(error);
        setStatus("Upload failed. Please check the backend logs.");
      }
    });
  }

  async function onRetryGraphSync(note: Note) {
    startTransition(async () => {
      setStatus(`Retrying graph sync for ${note.title}...`);
      try {
        const result = await retryGraphSync(note.id);
        await refreshAll();
        setStatus(
          result.queued
            ? "Graph sync retry queued. Refresh in a moment to see updated status."
            : "Graph sync is not configured yet."
        );
      } catch (error) {
        console.error(error);
        setStatus("Retrying graph sync failed. Please check the backend logs.");
      }
    });
  }

  const entityStats = deriveEntityStats(notes);
  const relationViews = deriveRelationViews(notes);
  const timelineEvents = deriveTimelineEvents(notes);
  const selectedAsk = askHistory.find((item) => item.id === selectedAskId) ?? askHistory[0] ?? null;

  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="hero hero-compact">
        <p className="eyebrow">Personal Knowledge OS</p>
        <h1>Build a second brain that actually talks back.</h1>
        <p className="hero-copy">
          FastAPI handles the agent backend. The workspace now splits capture, ask, entity graph, and relation graph
          into focused left-nav views so you can move between memory tasks without visual noise.
        </p>
      </header>

      <main className="workspace-shell">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <p className="panel-kicker">Workspace</p>
            <h2>Agent Views</h2>
          </div>
          <nav className="tab-nav" aria-label="Primary">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`tab-button ${activeTab === tab.id ? "tab-button-active" : ""}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="tab-kicker">{tab.kicker}</span>
                <strong>{tab.label}</strong>
              </button>
            ))}
          </nav>
          <div className="sidebar-status">
            <span className="status-dot" />
            <span>{status}</span>
          </div>
        </aside>

        <section className="content-stage">
          {activeTab === "capture" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Capture</p>
                <h2>Drop a note with almost zero friction</h2>
              </div>
              <div className="capture-grid">
                <form onSubmit={onCapture} className="panel sub-panel stack">
                  <p className="sub-panel-title">Quick text capture</p>
                  <textarea
                    value={captureText}
                    onChange={(event) => setCaptureText(event.target.value)}
                    placeholder="Paste an insight, a rough note, or a summary from a meeting..."
                    rows={10}
                  />
                  <button type="submit" disabled={isPending}>
                    Save to memory
                  </button>
                </form>

                <form onSubmit={onUpload} className="panel sub-panel stack">
                  <p className="sub-panel-title">File upload capture</p>
                  <div className="upload-zone">
                    <label htmlFor="capture-file" className="upload-label">
                      <strong>{captureFile ? captureFile.name : "Select a file to capture"}</strong>
                      <span>
                        Text files will be ingested directly. Other file types are stored as metadata notes for now.
                      </span>
                    </label>
                    <input
                      id="capture-file"
                      type="file"
                      onChange={(event) => setCaptureFile(event.target.files?.[0] ?? null)}
                    />
                  </div>
                  <button type="submit" disabled={isPending || !captureFile}>
                    Upload file
                  </button>
                </form>
              </div>
            </section>
          ) : null}

          {activeTab === "ask" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Ask</p>
                <h2>Query your own knowledge before the internet</h2>
              </div>

              <form onSubmit={onAsk} className="stack ask-form">
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask something like: 支付系统重构项目第一阶段方案包括什么？"
                  rows={4}
                />
                <button type="submit" disabled={isPending}>
                  Ask the agent
                </button>
              </form>

              <div className="ask-layout">
                <aside className="panel sub-panel ask-history">
                  <div className="sub-panel-header">
                    <p className="panel-kicker">History</p>
                    <h3>Recent questions</h3>
                  </div>
                  <div className="history-list">
                    {askHistory.length ? (
                      askHistory.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className={`history-item ${selectedAsk?.id === item.id ? "history-item-active" : ""}`}
                          onClick={() => setSelectedAskId(item.id)}
                        >
                          <strong>{item.question}</strong>
                          <span>{formatDateTime(item.created_at)}</span>
                          <em className={`history-state history-state-${item.status}`}>{item.status}</em>
                        </button>
                      ))
                    ) : (
                      <p className="empty-copy">Your question history will appear here.</p>
                    )}
                  </div>
                </aside>

                <div className="panel sub-panel ask-result">
                  <div className="sub-panel-header">
                    <p className="panel-kicker">Answer</p>
                    <h3>{selectedAsk?.question ?? "Your answer will appear here once the agent starts streaming."}</h3>
                  </div>
                  <div className="stream-card">
                    <p className={selectedAsk?.status === "streaming" ? "streaming-text" : ""}>
                      {selectedAsk?.answer || "Ask a question to start a live SSE response."}
                    </p>
                    {selectedAsk?.error ? <p className="sync-error">{selectedAsk.error}</p> : null}
                    {selectedAsk?.citations?.length ? (
                      <div className="citation-list">
                        {selectedAsk.citations.map((citation, index) => (
                          <article
                            key={`${citation.note_id}-${citation.relation_fact ?? index}`}
                            className="citation-item"
                          >
                            <strong>{citation.title}</strong>
                            {citation.relation_fact ? <em>{citation.relation_fact}</em> : null}
                            <span>{citation.snippet}</span>
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>
          ) : null}

          {activeTab === "entity" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Entity Graph</p>
                <h2>See which concepts keep showing up together</h2>
              </div>
              <div className="entity-cloud">
                {entityStats.length ? (
                  entityStats.map((entity, index) => (
                    <article
                      key={entity.name}
                      className={`entity-pill entity-size-${Math.min(4, Math.max(1, 5 - index))}`}
                    >
                      <strong>{entity.name}</strong>
                      <span>{entity.count} notes</span>
                    </article>
                  ))
                ) : (
                  <p className="empty-copy">Capture graph-enabled notes to populate the entity view.</p>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "relation" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Relation Graph</p>
                <h2>Trace how entities connect across notes</h2>
              </div>
              <div className="relation-list">
                {relationViews.length ? (
                  relationViews.map((relation) => (
                    <article key={relation.fact} className="relation-card">
                      <div className="relation-line">
                        <span className="entity-node">{relation.source}</span>
                        <span className="relation-label">{relation.relation}</span>
                        <span className="entity-node">{relation.target}</span>
                      </div>
                      <p>{relation.fact}</p>
                      <span className="relation-meta">
                        Seen {relation.count} time{relation.count > 1 ? "s" : ""} · latest{" "}
                        {formatDateTime(relation.latestAt)}
                      </span>
                    </article>
                  ))
                ) : (
                  <p className="empty-copy">No relationship facts yet. Graph-enabled capture will surface them here.</p>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "digest" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Digest</p>
                <h2>See what deserves attention today</h2>
              </div>
              <pre className="digest-block">{digest?.message ?? "No digest yet."}</pre>
              <div className="review-grid">
                {(digest?.due_reviews ?? []).map((review) => (
                  <article key={review.id} className="review-card">
                    <p>{review.prompt}</p>
                    <span>Due: {new Date(review.due_at).toLocaleString()}</span>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {activeTab === "timeline" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Timeline</p>
                <h2>Follow how knowledge compounds over time</h2>
              </div>
              <div className="timeline-list">
                {timelineEvents.length ? (
                  timelineEvents.map((event) => (
                    <article key={event.id} className="timeline-card">
                      <span className="timeline-date">{formatDateTime(event.createdAt)}</span>
                      <h3>{event.title}</h3>
                      <p>{event.summary}</p>
                      {event.entityNames.length ? (
                        <div className="mini-row">
                          {event.entityNames.map((entityName) => (
                            <span key={entityName} className="mini-chip">
                              {entityName}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {event.relationFacts.length ? (
                        <div className="timeline-facts">
                          {event.relationFacts.map((fact) => (
                            <span key={fact}>{fact}</span>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ))
                ) : (
                  <p className="empty-copy">No note history yet.</p>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "memory" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Memory</p>
                <h2>Recent notes in the knowledge base</h2>
              </div>
              <div className="notes-grid">
                {notes.length ? (
                  notes.map((note) => (
                    <article key={note.id} className="note-card">
                      <h3>{note.title}</h3>
                      <p>{note.summary}</p>
                      {note.source_ref ? (
                        <div className="note-meta-row">
                          <span className={`sync-pill sync-${note.graph_sync_status ?? "idle"}`}>
                            graph {note.graph_sync_status ?? "idle"}
                          </span>
                          {note.graph_sync_status === "failed" || note.graph_sync_status === "idle" ? (
                            <button
                              type="button"
                              className="secondary-button"
                              disabled={isPending}
                              onClick={() => void onRetryGraphSync(note)}
                            >
                              Retry sync
                            </button>
                          ) : null}
                          {note.graph_sync_error ? (
                            <span className="sync-error" title={note.graph_sync_error}>
                              {note.graph_sync_error}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="tag-row">
                        {note.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    </article>
                  ))
                ) : (
                  <p className="empty-copy">No notes yet. Capture your first thought to start the graph.</p>
                )}
              </div>
            </section>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function deriveEntityStats(notes: Note[]): EntityStat[] {
  const stats = new Map<string, EntityStat>();
  for (const note of notes) {
    for (const entityName of note.entity_names ?? []) {
      const current = stats.get(entityName);
      if (current) {
        current.count += 1;
        if (note.created_at > current.latestAt) {
          current.latestAt = note.created_at;
        }
      } else {
        stats.set(entityName, {
          name: entityName,
          count: 1,
          latestAt: note.created_at,
        });
      }
    }
  }

  return [...stats.values()]
    .sort((left, right) => right.count - left.count || right.latestAt.localeCompare(left.latestAt))
    .slice(0, 16);
}

function deriveRelationViews(notes: Note[]): RelationView[] {
  const stats = new Map<string, RelationView>();
  for (const note of notes) {
    for (const fact of note.relation_facts ?? []) {
      const parsed = parseRelationFact(fact);
      const current = stats.get(fact);
      if (current) {
        current.count += 1;
        if (note.created_at > current.latestAt) {
          current.latestAt = note.created_at;
        }
      } else {
        stats.set(fact, {
          fact,
          source: parsed.source,
          relation: parsed.relation,
          target: parsed.target,
          count: 1,
          latestAt: note.created_at,
        });
      }
    }
  }

  return [...stats.values()]
    .sort((left, right) => right.count - left.count || right.latestAt.localeCompare(left.latestAt))
    .slice(0, 12);
}

function deriveTimelineEvents(notes: Note[]): TimelineEvent[] {
  return [...notes]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, 10)
    .map((note) => ({
      id: note.id,
      title: note.title,
      createdAt: note.created_at,
      summary: note.summary,
      entityNames: (note.entity_names ?? []).slice(0, 5),
      relationFacts: (note.relation_facts ?? []).slice(0, 3),
    }));
}

function parseRelationFact(fact: string): { source: string; relation: string; target: string } {
  const spaced = fact.match(/^(.*?)\s+([A-Z_]+)\s+(.*?)$/);
  if (spaced) {
    return {
      source: spaced[1].trim(),
      relation: spaced[2].replaceAll("_", " "),
      target: spaced[3].trim(),
    };
  }

  const includePattern = fact.match(/^(.*?)(包括|有)(.*)$/);
  if (includePattern) {
    return {
      source: includePattern[1].trim(),
      relation: includePattern[2].trim(),
      target: includePattern[3].trim(),
    };
  }

  return {
    source: "Note",
    relation: "relates to",
    target: fact,
  };
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function parseSsePayload<T>(event: MessageEvent<string>): T {
  return JSON.parse(event.data) as T;
}
