import { FormEvent, type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import {
  buildEntryStreamUrl,
  confirmPendingAction,
  deleteAskHistoryRecord,
  fetchAskHistory,
  fetchDigest,
  fetchNotes,
  fetchPendingActions,
  getApiKey,
  rejectPendingAction,
  resetUserData,
  retryGraphSync,
  searchAskHistory,
  setApiKey,
  uploadEntryFile,
  type AskHistoryItem,
  type Citation,
  type DigestResponse,
  type Note,
  type PendingActionItem,
  type PlanStep,
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
  plan_steps?: PlanStep[];
};

type SessionSummary = {
  sessionId: string;
  title: string;
  lastQuestion: string;
  updatedAt: string;
  turnCount: number;
};

const TABS: Array<{ id: TabId; label: string; kicker: string }> = [
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
  const [question, setQuestion] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [status, setStatus] = useState("Agent 正在准备中。");
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [selectedRelationFact, setSelectedRelationFact] = useState<string | null>(null);
  const [askHistory, setAskHistory] = useState<AskHistoryView[]>([]);
  const [allAskHistory, setAllAskHistory] = useState<AskHistoryView[]>([]);
  const [selectedAskId, setSelectedAskId] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isResettingData, setIsResettingData] = useState(false);
  const [isRetryingGraphSync, setIsRetryingGraphSync] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState(() => getApiKey() || "");
  const [userId, setUserId] = useState(() => loadUserId());
  const [showSettings, setShowSettings] = useState(false);
  const [expandedPlans, setExpandedPlans] = useState<Set<string>>(new Set());
  const [pendingActions, setPendingActions] = useState<PendingActionItem[]>([]);
  const [isConfirmingAction, setIsConfirmingAction] = useState(false);
  const [historySearchQuery, setHistorySearchQuery] = useState("");
  const [isSearchingHistory, setIsSearchingHistory] = useState(false);
  const [activeCitationKey, setActiveCitationKey] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (activeCitationKey) {
      // Scroll to highlighted citation text after a short delay for render
      const timer = window.setTimeout(() => {
        const el = document.querySelector("[data-cite-highlight]");
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 100);
      return () => window.clearTimeout(timer);
    }
  }, [activeCitationKey]);

  useEffect(() => {
    void refreshAll();
    void refreshPendingActions();

    const intervalId = window.setInterval(() => {
      void refreshAll({ silent: true });
      void refreshPendingActions();
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
      setAskHistory((current) => mergeAskHistory(historyItems, current));
      setAllAskHistory((current) => {
        const merged = new Map<string, AskHistoryView>();
        for (const item of [...allHistoryItems, ...current]) {
          merged.set(item.id, item);
        }
        return [...merged.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
      });
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

  async function refreshPendingActions() {
    try {
      const response = await fetchPendingActions(userId, "pending");
      setPendingActions(response.items);
    } catch {
      // Silently ignore — pending actions are non-critical
    }
  }

  async function handleConfirmPending(action: PendingActionItem) {
    if (!action.token) return;
    setIsConfirmingAction(true);
    try {
      await confirmPendingAction(action.id, action.token, userId);
      setPendingActions((current) => current.filter((a) => a.id !== action.id));
      void refreshAll();
    } catch (error) {
      console.error("Failed to confirm pending action:", error);
    } finally {
      setIsConfirmingAction(false);
    }
  }

  async function handleRejectPending(action: PendingActionItem, reason = "") {
    try {
      await rejectPendingAction(action.id, userId, reason);
      setPendingActions((current) => current.filter((a) => a.id !== action.id));
    } catch (error) {
      console.error("Failed to reject pending action:", error);
    }
  }

  async function handleSearchHistory(query: string) {
    setHistorySearchQuery(query);
    if (!query.trim()) {
      void refreshAll();
      return;
    }
    setIsSearchingHistory(true);
    try {
      const result = await searchAskHistory(query.trim(), userId, 50);
      const items = result.items.map((item) => ({ ...item, status: "done" as const }));
      setAskHistory(items);
    } catch (error) {
      console.error("Failed to search ask history:", error);
    } finally {
      setIsSearchingHistory(false);
    }
  }

  async function handleDeleteHistoryRecord(recordId: string) {
    try {
      await deleteAskHistoryRecord(recordId, userId);
      setAskHistory((current) => current.filter((item) => item.id !== recordId));
      setAllAskHistory((current) => current.filter((item) => item.id !== recordId));
    } catch (error) {
      console.error("Failed to delete ask history record:", error);
    }
  }

  function onEntry(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();

    if (pendingFile) {
      void submitFileWithText(pendingFile, text || undefined);
      return;
    }

    if (!text) {
      return;
    }

    eventSourceRef.current?.close();
    const prompt = text;
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
    setStatus("正在理解你的意图...");

    const source = new EventSource(buildEntryStreamUrl(prompt, userId, sessionId));
    eventSourceRef.current = source;

    let entryIntent = "";

    source.addEventListener("intent", (streamEvent) => {
      const payload = parseSsePayload<{ intent?: string; reason?: string }>(streamEvent);
      entryIntent = payload.intent ?? "";
      setStatus(payload.reason ?? "正在处理...");
    });

    source.addEventListener("plan_created", (streamEvent) => {
      const payload = parseSsePayload<{ plan_steps?: PlanStep[] }>(streamEvent);
      if (payload.plan_steps?.length) {
        setAskHistory((current) =>
          current.map((item) =>
            item.id === historyItem.id
              ? { ...item, plan_steps: payload.plan_steps }
              : item
          )
        );
      }
    });

    // Plan execution progress events
    const updatePlanStepStatus = (stepId: string, newStatus: string) => {
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id && item.plan_steps
            ? {
                ...item,
                plan_steps: item.plan_steps.map((ps) =>
                  ps.step_id === stepId ? { ...ps, status: newStatus } : ps
                ),
              }
            : item
        )
      );
    };

    source.addEventListener("plan_step_started", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string }>(streamEvent);
      if (payload.step_id) updatePlanStepStatus(payload.step_id, "running");
    });

    source.addEventListener("plan_step_completed", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string }>(streamEvent);
      if (payload.step_id) updatePlanStepStatus(payload.step_id, "completed");
    });

    source.addEventListener("plan_step_failed", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string }>(streamEvent);
      if (payload.step_id) updatePlanStepStatus(payload.step_id, "failed");
    });

    source.addEventListener("plan_step_skipped", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string }>(streamEvent);
      if (payload.step_id) updatePlanStepStatus(payload.step_id, "skipped");
    });

    source.addEventListener("pending_action_created", (streamEvent) => {
      const payload = parseSsePayload<{
        action_id?: string;
        token?: string;
        action_type?: string;
        note_id?: string;
        title?: string;
        summary?: string;
        expires_at?: string;
        message?: string;
      }>(streamEvent);
      if (payload.action_id && payload.token) {
        const newAction: PendingActionItem = {
          id: payload.action_id,
          user_id: userId,
          action_type: payload.action_type ?? "delete_note",
          target_id: payload.note_id ?? "",
          title: payload.title ?? "待确认操作",
          description: payload.message ?? payload.summary ?? "",
          status: "pending",
          token: payload.token,
          created_at: new Date().toISOString(),
          expires_at: payload.expires_at ?? new Date(Date.now() + 3600000).toISOString(),
          resolved_at: null,
        };
        setPendingActions((current) => {
          if (current.some((a) => a.id === newAction.id)) return current;
          return [newAction, ...current];
        });
        setStatus(payload.message ?? "有操作需要你的确认。");
      }
      void refreshPendingActions();
    });

    source.addEventListener("draft_ready", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string; draft_text?: string }>(streamEvent);
      if (payload.draft_text) {
        setStatus("知识草稿已生成，正在写入知识库...");
      }
    });

    source.addEventListener("plan_replan_attempt", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string; reason?: string }>(streamEvent);
      if (payload.step_id) {
        setStatus(`步骤 ${payload.step_id} 失败，正在尝试重新规划...`);
      }
    });

    source.addEventListener("plan_replanned", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string; revised_step_count?: number }>(streamEvent);
      if (payload.step_id) {
        setStatus(`已重新规划，生成 ${payload.revised_step_count ?? 0} 个新步骤。`);
      }
    });

    source.addEventListener("plan_replan_failed", (streamEvent) => {
      const payload = parseSsePayload<{ step_id?: string; reason?: string }>(streamEvent);
      if (payload.step_id) {
        setStatus(`重新规划失败：${payload.reason ?? "无法恢复"}`);
      }
    });

    source.addEventListener("capture_result", (streamEvent) => {
      const payload = parseSsePayload<{ note?: Note; reply?: string }>(streamEvent);
      const reply = payload.reply ?? "已采集完成。";
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? { ...item, answer: reply, status: "done" as const }
            : item
        )
      );
      setStatus(reply);
    });

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
      const payload = parseSsePayload<{ answer?: string; reply?: string; citations?: Citation[]; graph_enabled?: boolean }>(streamEvent);
      const finalAnswer = payload.answer ?? payload.reply ?? historyItem.answer;
      const completedItem: AskHistoryView = {
        ...historyItem,
        answer: finalAnswer,
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
      if (entryIntent.startsWith("capture_") || entryIntent === "summarize_thread") {
        setStatus(finalAnswer);
        void refreshAll();
      } else {
        setStatus("已根据你的笔记生成回答。");
        void refreshAskHistorySelection(completedItem);
      }
      source.close();
      eventSourceRef.current = null;
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
      setStatus("处理失败，请检查后端日志。");
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

  function onFileSelect() {
    const fileInput = fileInputRef.current;
    if (!fileInput?.files?.length) {
      return;
    }
    const file = fileInput.files[0];
    setPendingFile(file);
    if (fileInput) {
      fileInput.value = "";
    }
    setActiveTab("ask");
  }

  function dismissPendingFile() {
    setPendingFile(null);
  }

  async function submitFileWithText(file: File, text?: string) {
    setIsUploading(true);
    setPendingFile(null);
    setQuestion("");
    const historyItem: AskHistoryView = {
      id: crypto.randomUUID(),
      user_id: userId,
      session_id: sessionId,
      question: text || `采集文件：${file.name}`,
      answer: "",
      citations: [],
      graph_enabled: false,
      created_at: new Date().toISOString(),
      status: "streaming",
    };
    setAskHistory((current) => [historyItem, ...current].slice(0, 20));
    setSelectedAskId(historyItem.id);
    setStatus(`正在上传 ${file.name} 并写入记忆...`);
    try {
      const entryResult = await uploadEntryFile(file, userId, sessionId, text);
      const reply = entryResult.reply_text || "文件已采集完成。";
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? { ...item, answer: reply, status: "done" as const }
            : item
        )
      );
      setStatus(reply);
      await refreshAll();
    } catch (error) {
      console.error(error);
      const message = error instanceof Error ? error.message : "上传失败，请检查后端日志。";
      setAskHistory((current) =>
        current.map((item) =>
          item.id === historyItem.id
            ? { ...item, status: "error" as const, error: message }
            : item
        )
      );
      setStatus(message);
    } finally {
      setIsUploading(false);
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
          {activeTab === "ask" ? (
            <section className="panel stage-panel">
              <div className="panel-header">
                <p className="panel-kicker">对话</p>
                <h2>直接和你的知识库展开对话</h2>
              </div>
              <div className="filter-toolbar">
                <span>当前对话：{sessionId.slice(0, 8)}</span>
                <input
                  type="text"
                  className="history-search-input"
                  placeholder="搜索问答历史..."
                  value={historySearchQuery}
                  onChange={(e) => {
                    const query = e.target.value;
                    setHistorySearchQuery(query);
                    if (!query.trim()) {
                      void refreshAll();
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void handleSearchHistory(historySearchQuery);
                    }
                  }}
                />
                <button
                  type="button"
                  className="secondary-button"
                  disabled={isSearchingHistory}
                  onClick={() => void handleSearchHistory(historySearchQuery)}
                >
                  {isSearchingHistory ? "搜索中..." : "搜索"}
                </button>
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

                <div className="ask-chat-main">
                  <div className="ask-chat-thread">
                  {orderedAskHistory.length ? (
                    orderedAskHistory.map((item) => (
                      <div key={item.id} className="chat-turn">
                        <article className="chat-bubble chat-bubble-user">
                          <div className="chat-meta">
                            <span>你</span>
                            <time>{formatDateTime(item.created_at)}</time>
                            <button
                              type="button"
                              className="history-delete-button"
                              title="删除此轮对话"
                              onClick={() => void handleDeleteHistoryRecord(item.id)}
                            >
                              ✕
                            </button>
                          </div>
                          <p>{item.question}</p>
                        </article>

                        <article className="chat-bubble chat-bubble-agent">
                          <div className="chat-meta">
                            <span>Agent</span>
                            <em className={`history-state history-state-${item.status}`}>{translateAskStatus(item.status)}</em>
                          </div>
                          <div className={item.status === "streaming" ? "streaming-text" : ""}>
                            {renderHighlightedAnswer(
                              item.answer || "正在思考...",
                              activeCitationKey,
                              item.citations,
                            )}
                          </div>
                          {item.error ? <p className="sync-error">{item.error}</p> : null}
                          {item.plan_steps?.length ? (
                            <div className="plan-panel">
                              <button
                                type="button"
                                className="plan-toggle"
                                onClick={() =>
                                  setExpandedPlans((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(item.id)) next.delete(item.id);
                                    else next.add(item.id);
                                    return next;
                                  })
                                }
                              >
                                Agent 计划执行 {item.plan_steps.length} 步
                                <span className="plan-toggle-icon">
                                  {expandedPlans.has(item.id) ? " ▾" : " ▸"}
                                </span>
                              </button>
                              {expandedPlans.has(item.id) ? (
                                <ol className="plan-steps-list">
                                  {item.plan_steps.map((ps, idx) => {
                                    const actionType = ps.action_type || (ps as Record<string, unknown>).step as string || "?";
                                    const toolName = ps.tool_name ?? (ps as Record<string, unknown>).tool as string;
                                    const riskLabel = translateRiskLevel(ps.risk_level ?? "low");
                                    return (
                                      <li key={ps.step_id || idx} className="plan-step-item">
                                        <span className="plan-step-type">[{translatePlanStep(actionType)}]</span>
                                        <span className="plan-step-desc">{ps.description || actionType}</span>
                                        {toolName ? <span className="plan-step-tool">{toolName}</span> : null}
                                        {riskLabel ? <span className="plan-step-risk">{riskLabel}</span> : null}
                                        {ps.requires_confirmation ? <span className="plan-step-confirm">待确认</span> : null}
                                        {ps.validation_warnings?.map((w, wi) => (
                                          <span key={wi} className="plan-step-warning" title={w}>警告</span>
                                        ))}
                                        <span className={`plan-step-status status-${ps.status}`}>{ps.status}</span>
                                        {ps.retry_count && ps.retry_count > 0 ? <span className="plan-step-retry" title={`重试了 ${ps.retry_count} 次`}>重试{ps.retry_count}</span> : null}
                                      </li>
                                    );
                                  })}
                                </ol>
                              ) : null}
                            </div>
                          ) : null}
                          {item.citations?.length ? (
                            <div className="citation-list">
                              {item.citations.map((citation, index) => {
                                const citeKey = `${item.id}-${citation.note_id}-${citation.relation_fact ?? index}`;
                                const isActive = activeCitationKey === citeKey;
                                return (
                                  <article
                                    key={citeKey}
                                    className={`citation-item ${isActive ? "citation-item-active" : ""}`}
                                    onClick={() =>
                                      setActiveCitationKey((current) =>
                                        current === citeKey ? null : citeKey
                                      )
                                    }
                                  >
                                    <strong>{citation.title}</strong>
                                    {citation.relation_fact ? <em>{citation.relation_fact}</em> : null}
                                    <span>{citation.snippet}</span>
                                  </article>
                                );
                              })}
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

                {pendingFile ? (
                  <div className="pending-file-bar">
                    <span className="pending-file-icon">📄</span>
                    <span className="pending-file-name">{pendingFile.name}</span>
                    <button
                      type="button"
                      className="pending-file-dismiss"
                      onClick={dismissPendingFile}
                      disabled={isUploading}
                    >
                      ✕
                    </button>
                  </div>
                ) : null}
                <div className="ask-composer-file-row">
                  <input
                    type="file"
                    ref={fileInputRef}
                    className="file-input-hidden"
                    onChange={onFileSelect}
                  />
                </div>
                <form onSubmit={onEntry} className="ask-composer">
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="提问、记录想法、粘贴链接，或直接上传文件..."
                    rows={3}
                  />
                  <div className="ask-composer-actions">
                    <span className="composer-hint">输入问题会检索知识库回答，记录/链接/文件会自动采集。</span>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={isUploading}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      {isUploading ? "上传中..." : "上传文件"}
                    </button>
                    <button type="submit">发送</button>
                  </div>
                </form>
                </div>
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

          {pendingActions.length > 0 ? (
            <section className="panel stage-panel pending-actions-panel">
              <div className="panel-header">
                <p className="panel-kicker">待处理</p>
                <h2>需要你确认的操作 ({pendingActions.length})</h2>
              </div>
              <div className="pending-actions-list">
                {pendingActions.map((action) => (
                  <article key={action.id} className="pending-action-card">
                    <div className="pending-action-info">
                      <h3>{action.title}</h3>
                      <p>{action.description}</p>
                      <div className="pending-action-meta">
                        <span className="pending-action-type">{action.action_type}</span>
                        <span className="pending-action-expires">
                          过期时间: {new Date(action.expires_at).toLocaleString()}
                        </span>
                      </div>
                    </div>
                    <div className="pending-action-actions">
                      <button
                        type="button"
                        className="confirm-button"
                        disabled={isConfirmingAction}
                        onClick={() => void handleConfirmPending(action)}
                      >
                        确认
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={isConfirmingAction}
                        onClick={() => void handleRejectPending(action, "用户拒绝")}
                      >
                        拒绝
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

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

function translatePlanStep(actionType: string): string {
  switch (actionType) {
    case "retrieve": return "检索";
    case "tool_call": return "调用工具";
    case "compose": return "生成回答";
    case "verify": return "校验";
    default: return actionType;
  }
}

function translateRiskLevel(risk: string): string {
  switch (risk) {
    case "high": return "高风险";
    case "medium": return "中风险";
    default: return "";
  }
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

function renderHighlightedAnswer(
  answer: string,
  activeCiteKey: string | null,
  citations?: Citation[],
) {
  if (!activeCiteKey || !citations?.length) {
    return <p>{answer}</p>;
  }

  // Find the active citation
  const activeCitation = citations.find((c, i) => {
    const key = `${c.note_id}-${c.relation_fact ?? i}`;
    return activeCiteKey.includes(key);
  });

  if (!activeCitation) {
    return <p>{answer}</p>;
  }

  // Find text to highlight: prefer snippet, fall back to relation_fact
  const highlightText = activeCitation.snippet || activeCitation.relation_fact;
  if (!highlightText || highlightText.length < 3) {
    return <p>{answer}</p>;
  }

  // Find the best matching substring in the answer
  const matchIndex = answer.indexOf(highlightText.slice(0, 30));
  if (matchIndex < 0) {
    // Try matching relation_fact keywords
    const factWords = (activeCitation.relation_fact || "")
      .split(/\s+/)
      .filter((w) => w.length >= 3);
    if (!factWords.length) {
      return <p>{answer}</p>;
    }

    const parts: React.ReactNode[] = [];
    let remaining = answer;
    let keyIndex = 0;

    for (const word of factWords) {
      const idx = remaining.indexOf(word);
      if (idx >= 0) {
        if (idx > 0) {
          parts.push(<span key={`t-${keyIndex++}`}>{remaining.slice(0, idx)}</span>);
        }
        parts.push(
          <mark key={`m-${keyIndex++}`} className="citation-highlight" data-cite-highlight="true">
            {remaining.slice(idx, idx + word.length)}
          </mark>
        );
        remaining = remaining.slice(idx + word.length);
      }
    }

    if (remaining) {
      parts.push(<span key={`t-${keyIndex++}`}>{remaining}</span>);
    }

    return (
      <p>
        {parts.length ? parts : answer}
      </p>
    );
  }

  // Exact match of first 30 chars of snippet
  const before = answer.slice(0, matchIndex);
  const highlightLen = Math.min(highlightText.length, 160);
  const match = answer.slice(matchIndex, matchIndex + highlightLen);
  const after = answer.slice(matchIndex + highlightLen);

  return (
    <p>
      {before}
      <mark className="citation-highlight" data-cite-highlight="true">
        {match}
      </mark>
      {after}
    </p>
  );
}
