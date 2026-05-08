import { FormEvent, useEffect, useState, useTransition } from "react";
import {
  askQuestion,
  captureNote,
  fetchDigest,
  fetchNotes,
  uploadCapture,
  type AskResponse,
  type DigestResponse,
  type Note,
} from "./api";

const USER_ID = "default";

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

export default function App() {
  const [captureText, setCaptureText] = useState("");
  const [captureFile, setCaptureFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [status, setStatus] = useState("Agent is warming up.");
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    void refreshAll();
  }, []);

  async function refreshAll() {
    setStatus("Refreshing memory timeline...");
    try {
      const [noteItems, digestResult] = await Promise.all([
        fetchNotes(USER_ID),
        fetchDigest(USER_ID),
      ]);
      setNotes(noteItems);
      setDigest(digestResult);
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

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }

    startTransition(async () => {
      setStatus("Searching your personal memory...");
      try {
        const result = await askQuestion(question.trim(), USER_ID);
        setAnswer(result);
        setStatus("Answer generated from your notes.");
      } catch (error) {
        console.error(error);
        setStatus("Question failed. Please check the backend logs.");
      }
    });
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
        setStatus("Uploaded file captured into memory.");
      } catch (error) {
        console.error(error);
        setStatus("Upload failed. Please check the backend logs.");
      }
    });
  }

  const entityStats = deriveEntityStats(notes);
  const relationViews = deriveRelationViews(notes);
  const timelineEvents = deriveTimelineEvents(notes);

  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="hero">
        <p className="eyebrow">Personal Knowledge OS</p>
        <h1>Build a second brain that actually talks back.</h1>
        <p className="hero-copy">
          FastAPI handles the agent backend. This front end gives you one place to capture
          fragments, ask questions, inspect your entity graph, and follow how memory evolves over time.
        </p>
        <div className="hero-bar">
          <span className="status-dot" />
          <span>{status}</span>
        </div>
      </header>

      <main className="layout">
        <section className="panel panel-capture">
          <div className="panel-header">
            <p className="panel-kicker">Capture</p>
            <h2>Drop a note with almost zero friction</h2>
          </div>
          <form onSubmit={onCapture} className="stack">
            <textarea
              value={captureText}
              onChange={(event) => setCaptureText(event.target.value)}
              placeholder="Paste an insight, a rough note, or a summary from a meeting..."
              rows={7}
            />
            <button type="submit" disabled={isPending}>
              Save to memory
            </button>
          </form>
          <form onSubmit={onUpload} className="stack upload-stack">
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
        </section>

        <section className="panel panel-ask">
          <div className="panel-header">
            <p className="panel-kicker">Ask</p>
            <h2>Query your own knowledge before the internet</h2>
          </div>
          <form onSubmit={onAsk} className="stack">
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

          <div className="answer-card">
            <p className="panel-kicker">Answer</p>
            <p>{answer?.answer ?? "Your answer will appear here once the agent finds supporting notes."}</p>
            {answer?.citations?.length ? (
              <div className="citation-list">
                {answer.citations.map((citation, index) => (
                  <article key={`${citation.note_id}-${citation.relation_fact ?? index}`} className="citation-item">
                    <strong>{citation.title}</strong>
                    {citation.relation_fact ? <em>{citation.relation_fact}</em> : null}
                    <span>{citation.snippet}</span>
                  </article>
                ))}
              </div>
            ) : null}
          </div>
        </section>

        <section className="panel panel-map">
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

        <section className="panel panel-relations">
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

        <section className="panel panel-digest">
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

        <section className="panel panel-timeline">
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

        <section className="panel panel-notes">
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
    .slice(0, 14);
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
    .slice(0, 10);
}

function deriveTimelineEvents(notes: Note[]): TimelineEvent[] {
  return [...notes]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, 8)
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
