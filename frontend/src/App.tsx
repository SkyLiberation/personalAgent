import { FormEvent, type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import {
  buildAskStreamUrl,
  captureNote,
  checkUploadConflict,
  fetchAskHistory,
  fetchDigest,
  fetchNotes,
  getApiKey,
  resetUserData,
  retryGraphSync,
  setApiKey,
  uploadCapture,
  type AskHistoryItem,
  type AskResponse,
  type Citation,
  type DigestResponse,
  type Note,
} from "./api";

function loadUserId(): string {
  try {
    return localStorage.getItem("personal-agent-user-id") || "default";
  } catch {
    return "default";
  }
}

function saveUserId(id: string): void {
  try {
    localStorage.setItem("personal-agent-user-id", id);
  } catch {
    // localStorage unavailable
  }
}

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

type SessionSummary = {
  sessionId: string;
  title: string;
  lastQuestion: string;
  updatedAt: string;
  turnCount: number;
};

const TABS: Array<{ id: TabId; label: string; kicker: string }> = [
  { id: "capture", label: "采集", kicker: "录入" },
  { id: "ask", label: "对话", kicker: "问答" },
  { id: "entity", label: "Entity Graph", kicker: "图谱" },
  { id: "relation", label: "Relation Graph", kicker: "关系" },
  { id: "digest", label: "摘要", kicker: "复习" },
  { id: "timeline", label: "Timeline", kicker: "时间" },
  { id: "memory", label: "记忆", kicker: "归档" },
];

export default function App() {
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId());
  const [activeTab, setActiveTab] = useState<TabId>("ask");
  const [captureText, setCaptureText] = useState("");
  const [captureUrl, setCaptureUrl] = useState("");
  const [captureFile, setCaptureFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [status, setStatus] = useState("Agent 正在准备中。");
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [selectedRelationFact, setSelectedRelationFact] = useState<string | null>(null);
  const [askHistory, setAskHistory] = useState<AskHistoryView[]>([]);
  const [allAskHistory, setAllAskHistory] = useState<AskHistoryView[]>([]);
  const [selectedAskId, setSelectedAskId] = useState<string | null>(null);
  const [isCapturingText, setIsCapturingText] = useState(false);
  const [isCapturingLink, setIsCapturingLink] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isResettingData, setIsResettingData] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isRetryingGraphSync, setIsRetryingGraphSync] = useState(false);
  const [uploadConflict, setUploadConflict] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState(() => getApiKey() || "");
  const [userId, setUserId] = useState(() => loadUserId());
  const [showSettings, setShowSettings] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void refreshAll();

    const intervalId = window.setInterval(() => {
      void refreshAll({ silent: true });
    }, 8000);

    return () => {
      window.clearInterval(intervalId);
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, [sessionId]);

  async function refreshAll(options?: { silent?: boolean }) {
    if (!options?.silent) {
      setStatus("正在刷新记忆视图...");
    }
    try {
      const [noteItems, digestResult, askHistoryResult, allAskHistoryResult] = await Promise.all([
        fetchNotes(userId),
        fetchDigest(userId),
        fetchAskHistory(userId, 20, sessionId),
        fetchAskHistory(userId, 100),
      ]);
      setNotes(noteItems);
      setDigest(digestResult);
      const historyItems = askHistoryResult.items.map((item) => ({
        ...item,
        status: "done" as const,
      }));
      const allHistoryItems = allAskHistoryResult.items.map((item) => ({
        ...item,
        status: "done" as const,
      }));
      setAskHistory(historyItems);
      setAllAskHistory(allHistoryItems);
      setSelectedAskId((current) => current ?? historyItems[0]?.id ?? null);
      if (!options?.silent) {
        setStatus("知识库已就绪。");
      }
    } catch (error) {
      console.error(error);
      if (!options?.silent) {
        setStatus("暂时无法连接后端，请启动 FastAPI 后刷新页面。");
      }
    }
  }

  async function onCapture(event: FormEvent) {
    event.preventDefault();
    if (!captureText.trim()) {
      return;
    }

    setIsCapturingText(true);
    setStatus("正在采集并连接这条笔记...");
    try {
      await captureNote(captureText.trim(), userId, "text");
      setCaptureText("");
      await refreshAll();
      setStatus("新笔记已采集并建立关联。");
    } catch (error) {
      console.error(error);
      setStatus("采集失败，请检查后端日志。");
    } finally {
      setIsCapturingText(false);
    }
  }

  async function onCaptureLink(event: FormEvent) {
    event.preventDefault();
    if (!captureUrl.trim()) {
      return;
    }

    setIsCapturingLink(true);
    setStatus("正在抓取网页并写入记忆...");
    try {
      await captureNote(captureUrl.trim(), userId, "link");
      setCaptureUrl("");
      await refreshAll();
      setStatus("网页已写入记忆。");
    } catch (error) {
      console.error(error);
      setStatus("网站抓取失败，请检查 URL 和后端日志。");
    } finally {
      setIsCapturingLink(false);
    }
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
      user_id: userId,
      session_id: sessionId,
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
    setStatus("正在检索你的个人记忆...");

    const source = new EventSource(buildAskStreamUrl(prompt, userId, sessionId));
    eventSourceRef.current = source;

    source.addEventListener("status", (streamEvent) => {
      const payload = parseSsePayload<{ message?: string }>(streamEvent);
      setStatus(payload.message ?? "正在生成回答...");
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
      const completedItem: AskHistoryView = {
        ...historyItem,
        answer: payload.answer ?? historyItem.answer,
        citations: payload.citations ?? historyItem.citations,
        graph_enabled: payload.graph_enabled ?? historyItem.graph_enabled,
        status: "done",
      };
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? completedItem
            : item
        )
      );
      setSelectedAskId(historyItem.id);
      setStatus("已根据你的笔记生成回答。");
      source.close();
      eventSourceRef.current = null;
      void refreshAskHistorySelection(completedItem);
    });

    source.onerror = () => {
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? {
                ...item,
                status: "error",
                error: "流式返回被中断，请检查后端日志后重试。",
              }
            : item
        )
      );
      setStatus("提问失败，请检查后端日志。");
      source.close();
      eventSourceRef.current = null;
    };
  }

  async function refreshAskHistorySelection(fallbackItem?: AskHistoryView) {
    try {
      const response = await fetchAskHistory(userId, 20, sessionId);
      const serverItems = response.items.map((item) => ({
        ...item,
        status: "done" as const,
      }));
      setAskHistory((currentHistory) => {
        const merged = mergeAskHistory(serverItems, currentHistory, fallbackItem);
        setSelectedAskId((currentSelectedId) => {
          if (currentSelectedId && merged.some((item) => item.id === currentSelectedId)) {
            return currentSelectedId;
          }
          if (fallbackItem && merged.some((item) => item.id === fallbackItem.id)) {
            return fallbackItem.id;
          }
          return merged[0]?.id ?? null;
        });
        return merged;
      });
      const allHistoryResponse = await fetchAskHistory(userId, 100);
      setAllAskHistory(
        allHistoryResponse.items.map((item) => ({
          ...item,
          status: "done" as const,
        }))
      );
    } catch (error) {
      console.error(error);
    }
  }

  function startNewDialog() {
    const nextSessionId = crypto.randomUUID();
    setSessionId(nextSessionId);
    localStorage.setItem("personal-agent-session-id", nextSessionId);
    setAskHistory([]);
    setSelectedAskId(null);
    setQuestion("");
    setStatus("已开始新对话，可以继续追问。");
    setActiveTab("ask");
  }

  async function openSession(targetSessionId: string) {
    if (targetSessionId === sessionId) {
      setActiveTab("ask");
      return;
    }
    setStatus("正在加载对话历史...");
    setSessionId(targetSessionId);
    localStorage.setItem("personal-agent-session-id", targetSessionId);
    setActiveTab("ask");
  }

  async function onUpload(event: FormEvent) {
    event.preventDefault();
    if (!captureFile) {
      return;
    }

    let overwrite = false;
    if (uploadConflict) {
      const confirmed = window.confirm(
        `data/uploads 中已经存在同名文件“${captureFile.name}”。是否覆盖原文件？`
      );
      if (!confirmed) {
        setStatus("已取消上传，保留原文件。");
        return;
      }
      overwrite = true;
    }

    setIsUploading(true);
    setUploadProgress(0);
    setStatus(`正在上传 ${captureFile.name} 并写入记忆...`);
    try {
      await uploadCapture(captureFile, userId, overwrite, (progress) => {
        setUploadProgress(progress);
      });
      setUploadProgress(100);
      setCaptureFile(null);
      setUploadConflict(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await refreshAll();
      setStatus("文件已采集完成，图谱同步将在后台继续。");
    } catch (error) {
      console.error(error);
      const message = error instanceof Error ? error.message : "上传失败，请检查后端日志。";
      setStatus(message);
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadProgress(0), 300);
    }
  }

  async function onSelectUploadFile(file: File | null) {
    setCaptureFile(file);
    setUploadConflict(false);
    if (!file) {
      return;
    }

    try {
      const conflict = await checkUploadConflict(file.name);
      setUploadConflict(conflict.exists);
      if (conflict.exists) {
        setStatus(`已存在同名文件 ${file.name}，上传时需要确认是否覆盖。`);
      }
    } catch (error) {
      console.error(error);
    }
  }

  async function onRetryGraphSync(note: Note) {
    setIsRetryingGraphSync(true);
    setStatus(`正在重试 ${note.title} 的图谱同步...`);
    try {
      const result = await retryGraphSync(note.id);
      await refreshAll();
      setStatus(
        result.queued
          ? "图谱同步重试已加入队列，稍后刷新即可看到最新状态。"
          : "当前还没有配置图谱同步。"
      );
    } catch (error) {
      console.error(error);
      setStatus("重试图谱同步失败，请检查后端日志。");
    } finally {
      setIsRetryingGraphSync(false);
    }
  }

  async function onResetUserData() {
    const confirmed = window.confirm(
      "这会清空当前用户的本地笔记、复习任务、对话历史、上传源文件、服务端问答历史，以及图谱分组数据。确定继续吗？"
    );
    if (!confirmed) {
      return;
    }

    setIsResettingData(true);
    setStatus("正在清空调试数据...");
    try {
      const result = await resetUserData(userId);
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      setCaptureText("");
      setCaptureUrl("");
      setCaptureFile(null);
      setQuestion("");
      setAskHistory([]);
      setAllAskHistory([]);
      setSelectedAskId(null);
      const nextSessionId = crypto.randomUUID();
      setSessionId(nextSessionId);
      localStorage.setItem("personal-agent-session-id", nextSessionId);
      localStorage.removeItem("personal-agent-session-summaries");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await refreshAll();
      setStatus(
        `调试数据已清空：删除 ${result.deleted_notes} 条笔记、${result.deleted_reviews} 条复习、${result.deleted_conversations} 条对话、${result.deleted_upload_files} 个源文件、${result.deleted_ask_history} 条问答历史，以及 ${result.deleted_graph_episodes} 条图谱 episode。`
      );
    } catch (error) {
      console.error(error);
      setStatus("清空调试数据失败，请检查后端日志。");
    } finally {
      setIsResettingData(false);
    }
  }

  const filteredNotes = filterNotes(notes, selectedEntity, selectedRelationFact);
  const entityStats = deriveEntityStats(filterNotes(notes, null, selectedRelationFact));
  const relationViews = deriveRelationViews(filterNotes(notes, selectedEntity, null));
  const timelineEvents = deriveTimelineEvents(filteredNotes);
  const hasGraphFilter = Boolean(selectedEntity || selectedRelationFact);
  const orderedAskHistory = [...askHistory].sort((left, right) => left.created_at.localeCompare(right.created_at));
  const sessionSummaries = deriveSessionSummaries(allAskHistory, askHistory, sessionId);

  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="hero hero-compact">
        <p className="eyebrow">个人知识系统</p>
        <h1>让你的第二大脑真正能和你对话。</h1>
        <p className="hero-copy">
          这里把采集、对话、图谱和复习整理成统一工作台，让你可以围绕个人记忆顺畅切换，而不是在一堆零散页面里来回跳转。
        </p>
      </header>

      <main className="workspace-shell">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <p className="panel-kicker">工作台</p>
            <h2>功能视图</h2>
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
          <div className="sidebar-settings">
            <button
              type="button"
              className={`settings-toggle ${showSettings ? "settings-toggle-active" : ""}`}
              onClick={() => setShowSettings((current) => !current)}
            >
              {showSettings ? "收起设置" : "设置"}
            </button>
            {showSettings ? (
              <div className="settings-panel">
                <label className="settings-field">
                  <span>API Key</span>
                  <input
                    type="password"
                    value={apiKeyInput}
                    onChange={(event) => {
                      setApiKeyInput(event.target.value);
                      setApiKey(event.target.value);
                    }}
                    placeholder="输入 API Key..."
                  />
                </label>
                <label className="settings-field">
                  <span>用户 ID</span>
                  <input
                    type="text"
                    value={userId}
                    onChange={(event) => {
                      setUserId(event.target.value);
                      saveUserId(event.target.value);
                    }}
                    placeholder="default"
                  />
                </label>
              </div>
            ) : null}
          </div>
        </aside>

        <section className="content-stage">
          {activeTab === "capture" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">采集</p>
                <h2>尽可能低成本地写下一条新笔记</h2>
              </div>
              <div className="capture-grid">
                <form onSubmit={onCapture} className="panel sub-panel stack">
                  <p className="sub-panel-title">快速文本采集</p>
                  <p className="sub-panel-copy">
                    适合记录想法、会议纪要、草稿片段，直接写成一条普通记忆。
                  </p>
                  <textarea
                    value={captureText}
                    onChange={(event) => setCaptureText(event.target.value)}
                    placeholder="粘贴一个想法、一段草稿，或者一场会议的总结..."
                    rows={10}
                  />
                  <button type="submit" disabled={isCapturingText}>
                    {isCapturingText ? "保存中..." : "写入记忆"}
                  </button>
                </form>

                <form onSubmit={onCaptureLink} className="panel sub-panel stack">
                  <p className="sub-panel-title">网站抓取采集</p>
                  <p className="sub-panel-copy">
                    粘贴一个网页 URL，系统会优先抓取正文并转成可索引内容。
                  </p>
                  <textarea
                    value={captureUrl}
                    onChange={(event) => setCaptureUrl(event.target.value)}
                    placeholder="https://example.com/article"
                    rows={10}
                  />
                  <button type="submit" disabled={isCapturingLink}>
                    {isCapturingLink ? "抓取中..." : "抓取网页"}
                  </button>
                </form>

                <form onSubmit={onUpload} className="panel sub-panel stack">
                  <p className="sub-panel-title">文件上传采集</p>
                  <p className="sub-panel-copy">
                    支持先把文件保存到本地知识库，文本和 PDF 会尽量抽取正文，其它类型先保存元信息。
                  </p>
                  <div className="upload-zone">
                    <div className="upload-label">
                      {!isUploading ? (
                        <>
                          <strong>{captureFile ? captureFile.name : "选择一个要采集的文件"}</strong>
                          <span>
                            文本类文件会直接采集内容，其他文件类型目前先保存为元信息笔记。
                          </span>
                          {uploadConflict ? (
                            <span className="upload-warning">
                              已存在同名文件，稍后会询问你是否覆盖。
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <div className="upload-progress-block">
                          <div className="upload-progress-copy">
                            <strong>正在上传文件...</strong>
                            <span>已完成 {uploadProgress}%</span>
                          </div>
                          <div className="upload-progress-track" aria-hidden="true">
                            <div
                              className="upload-progress-bar"
                              style={{ width: `${uploadProgress}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="upload-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isUploading}
                      >
                        {captureFile ? "重新选择文件" : "选择文件"}
                      </button>
                    </div>
                    <input
                      id="capture-file"
                      type="file"
                      ref={fileInputRef}
                      className="file-input-hidden"
                      onChange={(event) => void onSelectUploadFile(event.target.files?.[0] ?? null)}
                    />
                  </div>
                  <button type="submit" disabled={isUploading || !captureFile}>
                    {isUploading ? "上传中..." : "上传文件"}
                  </button>
                </form>
              </div>
              <div className="danger-zone">
                <div>
                  <p className="sub-panel-title">调试重置</p>
                  <p className="danger-copy">
                    一键清空当前用户的本地笔记、复习任务、对话历史、上传源文件，以及服务端问答历史，便于快速回到干净状态。
                    如果图谱已启用，也会一并清理当前用户对应的图谱分组数据。
                  </p>
                </div>
                <button
                  type="button"
                  className="danger-button"
                  disabled={isResettingData}
                  onClick={() => void onResetUserData()}
                >
                  {isResettingData ? "清空中..." : "一键清空调试数据"}
                </button>
              </div>
            </section>
          ) : null}

          {activeTab === "ask" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">对话</p>
                <h2>直接和你的知识库展开对话</h2>
              </div>
              <div className="filter-toolbar">
                <span>当前对话：{sessionId.slice(0, 8)}</span>
                <button type="button" className="secondary-button" onClick={startNewDialog}>
                  新建对话
                </button>
              </div>

              <div className="ask-chat-shell">
                <aside className="ask-session-list">
                  <div className="sub-panel-header">
                    <p className="panel-kicker">对话</p>
                    <h3>最近会话</h3>
                  </div>
                  <div className="history-list">
                    {sessionSummaries.length ? (
                      sessionSummaries.map((session) => (
                        <button
                          key={session.sessionId}
                          type="button"
                          className={`history-item ${session.sessionId === sessionId ? "history-item-active" : ""}`}
                          onClick={() => void openSession(session.sessionId)}
                        >
                          <strong>{session.title}</strong>
                          <span>{session.lastQuestion}</span>
                          <em>{formatDateTime(session.updatedAt)} · {session.turnCount} 轮</em>
                        </button>
                      ))
                    ) : (
                      <p className="empty-copy">你的历史会话会显示在这里。</p>
                    )}
                  </div>
                </aside>

                <div className="ask-chat-thread">
                  {orderedAskHistory.length ? (
                    orderedAskHistory.map((item) => (
                      <div key={item.id} className="chat-turn">
                        <article className="chat-bubble chat-bubble-user">
                          <div className="chat-meta">
                            <span>你</span>
                            <time>{formatDateTime(item.created_at)}</time>
                          </div>
                          <p>{item.question}</p>
                        </article>

                        <article className="chat-bubble chat-bubble-agent">
                          <div className="chat-meta">
                            <span>Agent</span>
                            <em className={`history-state history-state-${item.status}`}>{translateAskStatus(item.status)}</em>
                          </div>
                          <p className={item.status === "streaming" ? "streaming-text" : ""}>
                            {item.answer || "正在思考..."}
                          </p>
                          {item.error ? <p className="sync-error">{item.error}</p> : null}
                          {item.citations?.length ? (
                            <div className="citation-list">
                              {item.citations.map((citation, index) => (
                                <article
                                  key={`${item.id}-${citation.note_id}-${citation.relation_fact ?? index}`}
                                  className="citation-item"
                                >
                                  <strong>{citation.title}</strong>
                                  {citation.relation_fact ? <em>{citation.relation_fact}</em> : null}
                                  <span>{citation.snippet}</span>
                                </article>
                              ))}
                            </div>
                          ) : null}
                        </article>
                      </div>
                    ))
                  ) : (
                    <div className="ask-empty-state">
                      <p className="empty-copy">先开始一轮对话吧，后续追问会自动留在同一个会话里。</p>
                    </div>
                  )}
                </div>

                <form onSubmit={onAsk} className="ask-composer">
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="例如：支付系统重构项目第一阶段方案包括什么？"
                    rows={3}
                  />
                  <div className="ask-composer-actions">
                    <span className="composer-hint">Agent 会把当前会话作为上下文来理解你的追问。</span>
                    <button type="submit">发送</button>
                  </div>
                </form>
              </div>
            </section>
          ) : null}

          {activeTab === "entity" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Entity Graph</p>
                <h2>看看哪些概念经常一起出现</h2>
              </div>
              <div className="filter-toolbar">
                <span>{hasGraphFilter ? `已筛出 ${filteredNotes.length} 条笔记` : `共 ${notes.length} 条笔记`}</span>
                {selectedEntity ? <span className="filter-chip">实体：{selectedEntity}</span> : null}
                {selectedRelationFact ? <span className="filter-chip">关系：{selectedRelationFact}</span> : null}
                {hasGraphFilter ? (
                  <button type="button" className="secondary-button" onClick={() => clearFilters(setSelectedEntity, setSelectedRelationFact)}>
                    清空筛选
                  </button>
                ) : null}
              </div>
              <div className="entity-cloud">
                {entityStats.length ? (
                  entityStats.map((entity, index) => (
                    <button
                      key={entity.name}
                      type="button"
                      className={`entity-pill entity-size-${Math.min(4, Math.max(1, 5 - index))}`}
                      data-active={selectedEntity === entity.name}
                      onClick={() => setSelectedEntity((current) => (current === entity.name ? null : entity.name))}
                    >
                      <strong>{entity.name}</strong>
                      <span>{entity.count} notes</span>
                    </button>
                  ))
                ) : (
                  <p className="empty-copy">先采集启用图谱的笔记，这里才会逐渐丰富起来。</p>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "relation" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Relation Graph</p>
                <h2>追踪实体在不同笔记之间如何建立联系</h2>
              </div>
              <div className="filter-toolbar">
                <span>{hasGraphFilter ? `已筛出 ${filteredNotes.length} 条笔记` : `共 ${notes.length} 条笔记`}</span>
                {selectedEntity ? <span className="filter-chip">实体：{selectedEntity}</span> : null}
                {selectedRelationFact ? <span className="filter-chip">关系：{selectedRelationFact}</span> : null}
              </div>
              <div className="relation-list">
                {relationViews.length ? (
                  relationViews.map((relation) => (
                    <button
                      key={relation.fact}
                      type="button"
                      className="relation-card"
                      data-active={selectedRelationFact === relation.fact}
                      onClick={() =>
                        setSelectedRelationFact((current) => (current === relation.fact ? null : relation.fact))
                      }
                    >
                      <div className="relation-line">
                        <span
                          className="entity-node"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedEntity((current) => (current === relation.source ? null : relation.source));
                          }}
                        >
                          {relation.source}
                        </span>
                        <span className="relation-label">{relation.relation}</span>
                        <span
                          className="entity-node"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedEntity((current) => (current === relation.target ? null : relation.target));
                          }}
                        >
                          {relation.target}
                        </span>
                      </div>
                      <p>{relation.fact}</p>
                      <span className="relation-meta">
                        出现 {relation.count} 次 · 最近一次
                        {formatDateTime(relation.latestAt)}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="empty-copy">暂时还没有关系事实，后续图谱采集会把它们展示在这里。</p>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "digest" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">摘要</p>
                <h2>看看今天最值得关注的内容</h2>
              </div>
              <pre className="digest-block">{digest?.message ?? "暂时还没有摘要内容。"}</pre>
              <div className="review-grid">
                {(digest?.due_reviews ?? []).map((review) => (
                  <article key={review.id} className="review-card">
                    <p>{review.prompt}</p>
                    <span>到期时间：{new Date(review.due_at).toLocaleString()}</span>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {activeTab === "timeline" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">Timeline</p>
                <h2>沿着时间线观察知识如何逐步累积</h2>
              </div>
              <div className="filter-toolbar">
                <span>{hasGraphFilter ? `显示 ${timelineEvents.length} 条匹配事件` : `最近 ${timelineEvents.length} 条事件`}</span>
                {selectedEntity ? <span className="filter-chip">实体：{selectedEntity}</span> : null}
                {selectedRelationFact ? <span className="filter-chip">关系：{selectedRelationFact}</span> : null}
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
                            <button
                              key={entityName}
                              type="button"
                              className="mini-chip"
                              onClick={() =>
                                setSelectedEntity((current) => (current === entityName ? null : entityName))
                              }
                            >
                              {entityName}
                            </button>
                          ))}
                        </div>
                      ) : null}
                      {event.relationFacts.length ? (
                        <div className="timeline-facts">
                          {event.relationFacts.map((fact) => (
                            <button
                              key={fact}
                              type="button"
                              onClick={() =>
                                setSelectedRelationFact((current) => (current === fact ? null : fact))
                              }
                            >
                              {fact}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ))
                ) : (
                  <p className="empty-copy">暂时还没有笔记历史。</p>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "memory" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">记忆</p>
                <h2>知识库中的最近笔记</h2>
              </div>
              <div className="filter-toolbar">
                <span>{hasGraphFilter ? `当前图谱筛选命中 ${filteredNotes.length} 条笔记` : `当前共有 ${notes.length} 条记忆`}</span>
                {selectedEntity ? <span className="filter-chip">实体：{selectedEntity}</span> : null}
                {selectedRelationFact ? <span className="filter-chip">关系：{selectedRelationFact}</span> : null}
              </div>
              <div className="notes-grid">
                {filteredNotes.length ? (
                  filteredNotes.map((note) => (
                    <article key={note.id} className="note-card">
                      <h3>{note.title}</h3>
                      <p>{note.summary}</p>
                      {note.source_ref ? (
                        <div className="note-meta-row">
                          <span className={`sync-pill sync-${note.graph_sync_status ?? "idle"}`}>
                            图谱 {translateGraphStatus(note.graph_sync_status ?? "idle")}
                          </span>
                          {note.graph_sync_status === "failed" || note.graph_sync_status === "idle" ? (
                            <button
                              type="button"
                              className="secondary-button"
                              disabled={isRetryingGraphSync}
                              onClick={() => void onRetryGraphSync(note)}
                            >
                              重试同步
                            </button>
                          ) : null}
                          {note.graph_sync_error ? (
                            <span className="sync-error" title={note.graph_sync_error}>
                              {note.graph_sync_error}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                      {note.source_ref ? (
                        <p className={`sync-hint sync-hint-${note.graph_sync_status ?? "idle"}`}>
                          {describeGraphStatus(note)}
                        </p>
                      ) : null}
                      <div className="tag-row">
                        {note.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                      {note.entity_names?.length ? (
                        <div className="mini-row">
                          {note.entity_names.slice(0, 5).map((entityName) => (
                            <button
                              key={entityName}
                              type="button"
                              className="mini-chip"
                              onClick={() =>
                                setSelectedEntity((current) => (current === entityName ? null : entityName))
                              }
                            >
                              {entityName}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ))
                ) : (
                  <p className="empty-copy">
                    {notes.length ? "没有笔记符合当前筛选条件。" : "还没有任何笔记，先记录下你的第一个想法吧。"}
                  </p>
                )}
              </div>
            </section>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function clearFilters(
  setEntity: Dispatch<SetStateAction<string | null>>,
  setRelation: Dispatch<SetStateAction<string | null>>
) {
  setEntity(null);
  setRelation(null);
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

function filterNotes(notes: Note[], selectedEntity: string | null, selectedRelationFact: string | null): Note[] {
  return notes.filter((note) => {
    const entityMatch = !selectedEntity || (note.entity_names ?? []).includes(selectedEntity);
    const relationMatch = !selectedRelationFact || (note.relation_facts ?? []).includes(selectedRelationFact);
    return entityMatch && relationMatch;
  });
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
    source: "笔记",
    relation: "关联到",
    target: fact,
  };
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function parseSsePayload<T>(event: MessageEvent<string>): T {
  return JSON.parse(event.data) as T;
}

function translateAskStatus(status: AskHistoryView["status"]): string {
  if (status === "streaming") {
    return "生成中";
  }
  if (status === "done") {
    return "已完成";
  }
  return "出错";
}

function translateGraphStatus(status: NonNullable<Note["graph_sync_status"]>): string {
  if (status === "pending") {
    return "同步中";
  }
  if (status === "synced") {
    return "已同步";
  }
  if (status === "failed") {
    return "失败";
  }
  return "未开始";
}

function describeGraphStatus(note: Note): string {
  const status = note.graph_sync_status ?? "idle";
  if (status === "pending") {
    return "正在抽取实体和关系，通常需要 1 到 2 分钟；内容较长时会更久。";
  }
  if (status === "synced") {
    const entityCount = note.entity_names?.length ?? 0;
    const relationCount = note.relation_facts?.length ?? 0;
    return `图谱已完成同步，提取到 ${entityCount} 个实体和 ${relationCount} 条关系。`;
  }
  if (status === "failed") {
    return "图谱同步失败，可以查看错误提示后重新发起同步。";
  }
  return "这条笔记还没有进入图谱同步流程。";
}

function getOrCreateSessionId(): string {
  const storageKey = "personal-agent-session-id";
  const existing = localStorage.getItem(storageKey);
  if (existing) {
    return existing;
  }
  const created = crypto.randomUUID();
  localStorage.setItem(storageKey, created);
  return created;
}

function deriveSessionSummaries(
  allHistory: AskHistoryView[],
  currentSessionHistory: AskHistoryView[],
  currentSessionId: string
): SessionSummary[] {
  const allSessions = loadStoredSessionSummaries();
  const currentSummary = summarizeCurrentSession(currentSessionHistory, currentSessionId);
  const merged = new Map<string, SessionSummary>();

  for (const session of summarizeSessionsFromHistory(allHistory)) {
    merged.set(session.sessionId, session);
  }
  for (const session of allSessions) {
    merged.set(session.sessionId, session);
  }
  if (currentSummary) {
    merged.set(currentSummary.sessionId, currentSummary);
    persistSessionSummaries([...merged.values()]);
  }

  return [...merged.values()].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

function summarizeCurrentSession(
  history: AskHistoryView[],
  sessionId: string
): SessionSummary | null {
  if (!history.length) {
    return {
      sessionId,
      title: `对话 ${sessionId.slice(0, 8)}`,
      lastQuestion: "暂无消息",
      updatedAt: new Date().toISOString(),
      turnCount: 0,
    };
  }

  const first = history[0];
  const last = history[history.length - 1];
  return {
    sessionId,
    title: first.question.slice(0, 24) || `对话 ${sessionId.slice(0, 8)}`,
    lastQuestion: last.question,
    updatedAt: last.created_at,
    turnCount: history.length,
  };
}

function loadStoredSessionSummaries(): SessionSummary[] {
  try {
    const raw = localStorage.getItem("personal-agent-session-summaries");
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as SessionSummary[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistSessionSummaries(items: SessionSummary[]) {
  localStorage.setItem(
    "personal-agent-session-summaries",
    JSON.stringify(items.slice(0, 20))
  );
}

function summarizeSessionsFromHistory(history: AskHistoryView[]): SessionSummary[] {
  const grouped = new Map<string, AskHistoryView[]>();
  for (const item of history) {
    const sessionItems = grouped.get(item.session_id) ?? [];
    sessionItems.push(item);
    grouped.set(item.session_id, sessionItems);
  }

  return [...grouped.entries()].map(([sessionId, items]) => {
    const ordered = [...items].sort((left, right) => left.created_at.localeCompare(right.created_at));
    const first = ordered[0];
    const last = ordered[ordered.length - 1];
    return {
      sessionId,
      title: first.question.slice(0, 24) || `对话 ${sessionId.slice(0, 8)}`,
      lastQuestion: last.question,
      updatedAt: last.created_at,
      turnCount: ordered.length,
    };
  });
}

function mergeAskHistory(
  serverItems: AskHistoryView[],
  currentItems: AskHistoryView[],
  fallbackItem?: AskHistoryView
): AskHistoryView[] {
  const merged: AskHistoryView[] = [];
  const seen = new Set<string>();

  for (const item of serverItems) {
    merged.push(item);
    seen.add(item.id);
  }

  const localCandidates = fallbackItem ? [fallbackItem, ...currentItems] : currentItems;
  for (const item of localCandidates) {
    if (seen.has(item.id)) {
      continue;
    }
    const matchedServerItem = serverItems.find(
      (serverItem) =>
        serverItem.question === item.question &&
        serverItem.answer === item.answer
    );
    if (matchedServerItem) {
      continue;
    }
    merged.push(item);
    seen.add(item.id);
  }

  return merged
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, 20);
}
