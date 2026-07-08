import { useState, useEffect, useRef, useCallback } from "react";
import MessageBubble from "./MessageBubble";
import { useSSE } from "../hooks/useSSE";
import {
  listSessions,
  createSession,
  getHistory,
  deleteSession,
} from "../api/chat";
import type { ChatSession, ChatMessage } from "../types/chat";

// ── 状态映射 ──────────────────────────────────────
type PageState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "ready"; sessions: ChatSession[]; activeId: string | null }
  | { kind: "error"; message: string };

/* ── 组件属性 ────────────────────────────────────── */
export interface ChatPanelProps {
  /** 外部引用文本 — 变化时自动填充到输入框 */
  quoteText?: string;
  /** 引用计数器 — 确保相同文本多次引用也能触发填充 */
  quoteKey?: number;
  /** 当前关联的课件 ID — 创建新会话时自动绑定 */
  coursewareId?: string | null;
  /** 当前关联的课件标题 — 用于 UI 展示 */
  coursewareTitle?: string | null;
}

export default function ChatPanel({
  quoteText,
  quoteKey,
  coursewareId,
  coursewareTitle,
}: ChatPanelProps = {}) {
  // ── 页面 & 消息状态 ──────────────────────────────
  const [pageState, setPageState] = useState<PageState>({ kind: "loading" });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [streamError, setStreamError] = useState<string | null>(null);

  // ── 流式 token 追踪 ──────────────────────────────
  const [streamingTokens, setStreamingTokens] = useState<string[]>([]);
  const streamingMsgIdRef = useRef<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ── SSE Hook ────────────────────────────────────
  const { start, stop, isStreaming, isReconnecting, error: sseError } =
    useSSE({
      onToken: (content: string) => {
        setStreamingTokens((prev) => [...prev, content]);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingMsgIdRef.current
              ? { ...m, content: m.content + content }
              : m,
          ),
        );
      },
      onDone: (data: { message_id: string; token_count: number }) => {
        const assistantId = streamingMsgIdRef.current;
        if (!assistantId) return;

        setMessages((prev) =>
          prev.map((m) => {
            // 替换用户临时消息的 ID
            if (
              m.role === "user" &&
              m.id.startsWith("temp-") &&
              m.id !== assistantId
            ) {
              return { ...m, id: `user-${data.message_id}` };
            }
            // 替换助手临时消息的 ID 并写入 token_count
            if (m.id === assistantId) {
              return {
                ...m,
                id: data.message_id,
                token_count: data.token_count,
              };
            }
            return m;
          }),
        );

        // 清理流式状态
        streamingMsgIdRef.current = null;
        setStreamingTokens([]);
      },
      onError: (message: string) => {
        setStreamError(message);
        // 移除占位助手消息
        setMessages((prev) =>
          prev.filter((m) => m.id !== streamingMsgIdRef.current),
        );
        streamingMsgIdRef.current = null;
        setStreamingTokens([]);
      },
    });

  // 将 hook 的 error 同步到 streamError（重连提示在 UI 中展示）
  useEffect(() => {
    if (sseError) {
      setStreamError(sseError);
    } else if (!isReconnecting) {
      // 重连成功后清除错误
      setStreamError(null);
    }
  }, [sseError, isReconnecting]);

  // ── 加载会话列表 ────────────────────────────────
  const loadSessions = useCallback(async () => {
    setPageState({ kind: "loading" });
    try {
      const data = await listSessions(1, 50);
      if (data.items.length === 0) {
        setPageState({ kind: "empty" });
      } else {
        setPageState({
          kind: "ready",
          sessions: data.items,
          activeId: data.items[0].id,
        });
      }
    } catch (err: any) {
      setPageState({
        kind: "error",
        message: err?.message || "加载会话列表失败",
      });
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // ── 加载历史消息 ────────────────────────────────
  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const data = await getHistory(sessionId);
      setMessages(data.messages);
      setStreamError(null);
      setStreamingTokens([]);
      streamingMsgIdRef.current = null;
    } catch (err: any) {
      console.error("加载历史消息失败:", err);
      setMessages([]);
    }
  }, []);

  // 当 activeId 变化时加载消息
  useEffect(() => {
    if (pageState.kind === "ready" && pageState.activeId) {
      loadMessages(pageState.activeId);
    }
  }, [pageState.kind === "ready" ? (pageState as any).activeId : null, loadMessages]);

  // ── 自动滚动到底部 ──────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingTokens]);

  // ── 外部引用文本写入输入框 ────────────────────────
  useEffect(() => {
    if (quoteText) {
      setInputValue((prev) => {
        const trimmed = prev.trim();
        return trimmed ? `${trimmed}\n\n${quoteText}` : quoteText;
      });
    }
    // quoteKey 变化时触发（即使 quoteText 内容相同）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteKey]);

  // ── 创建新会话 ──────────────────────────────────
  const handleNewSession = async () => {
    try {
      const title = coursewareTitle
        ? `${coursewareTitle} - 对话`
        : "新对话";
      const session = await createSession({
        title,
        courseware_id: coursewareId ?? undefined,
      });
      await loadSessions();
      // 切换到新会话
      setPageState((prev) => {
        if (prev.kind === "ready") {
          return {
            ...prev,
            sessions: [session, ...prev.sessions],
            activeId: session.id,
          };
        }
        return prev;
      });
      setMessages([]);
      setStreamError(null);
      setStreamingTokens([]);
      streamingMsgIdRef.current = null;
    } catch (err: any) {
      alert(err?.message || "创建会话失败");
    }
  };

  // ── 切换会话 ────────────────────────────────────
  const handleSwitchSession = (sessionId: string) => {
    // 切换前先中止当前流
    stop();
    setPageState((prev) => {
      if (prev.kind === "ready") {
        return { ...prev, activeId: sessionId };
      }
      return prev;
    });
    setStreamError(null);
    setStreamingTokens([]);
    streamingMsgIdRef.current = null;
  };

  // ── 删除会话 ────────────────────────────────────
  const handleDeleteSession = async (sessionId: string) => {
    if (!confirm("确定要删除这个会话吗？")) return;
    try {
      await deleteSession(sessionId);
      await loadSessions();
      // 如果删除的是当前活跃会话，清空消息
      setPageState((prev) => {
        if (prev.kind === "ready" && prev.activeId === sessionId) {
          const remaining = prev.sessions.filter((s) => s.id !== sessionId);
          if (remaining.length === 0) {
            return { kind: "empty" };
          }
          return {
            ...prev,
            sessions: remaining,
            activeId: remaining[0].id,
          };
        }
        return prev;
      });
      setMessages([]);
      setStreamingTokens([]);
      streamingMsgIdRef.current = null;
    } catch (err: any) {
      alert(err?.message || "删除会话失败");
    }
  };

  // ── 发送消息 ────────────────────────────────────
  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isStreaming) return;

    const activeId =
      pageState.kind === "ready" ? pageState.activeId : null;
    if (!activeId) return;

    setInputValue("");
    setStreamError(null);
    setStreamingTokens([]);

    // 添加用户消息到本地（乐观更新）
    const tempUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      session_id: activeId,
      role: "user",
      content: text,
      token_count: 0,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    // 添加占位的 assistant 消息
    const tempAssistantMsg: ChatMessage = {
      id: `temp-assistant-${Date.now()}`,
      session_id: activeId,
      role: "assistant",
      content: "",
      token_count: 0,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempAssistantMsg]);

    // 记录流式消息 ID
    streamingMsgIdRef.current = tempAssistantMsg.id;

    // 发起 SSE 流式请求
    start(`/api/chat/sessions/${activeId}/messages`, {
      content: text,
    });
  };

  // ── 键盘事件 ────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── 取消生成 ────────────────────────────────────
  const handleCancel = () => {
    stop();
    streamingMsgIdRef.current = null;
    setStreamingTokens([]);
  };

  // ── 渲染: 加载态 ────────────────────────────────
  if (pageState.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-gray-400">加载中...</p>
      </div>
    );
  }

  // ── 渲染: 错误态 ────────────────────────────────
  if (pageState.kind === "error") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
        <p className="text-sm text-red-500">{pageState.message}</p>
        <button
          onClick={loadSessions}
          className="rounded bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600"
        >
          重试
        </button>
      </div>
    );
  }

  // ── 渲染: 空态（无会话） ────────────────────────
  if (pageState.kind === "empty") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6">
        <div className="text-center">
          <p className="mb-1 text-lg font-medium text-gray-600">还没有聊天</p>
          <p className="text-sm text-gray-400">
            点击下方按钮开始与 AI 助教对话
          </p>
        </div>
        <button
          onClick={handleNewSession}
          className="rounded-lg bg-blue-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600"
        >
          开始新对话
        </button>
      </div>
    );
  }

  // ── 渲染: 正常态 ────────────────────────────────
  const { sessions, activeId } = pageState;
  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* 课件关联提示 */}
      {coursewareTitle && (
        <div className="flex items-center gap-1.5 border-b border-blue-100 bg-blue-50 px-4 py-1.5 text-xs text-blue-700">
          <svg className="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-3-3v6m-8 4h16a1 1 0 001-1V7a1 1 0 00-1-1H5a1 1 0 00-1 1v11a1 1 0 001 1z" />
          </svg>
          <span className="truncate">
            当前课件：{coursewareTitle}
          </span>
          <span className="text-blue-400">— 新对话将自动关联此课件</span>
        </div>
      )}

      {/* 顶部栏: 会话选择器 + 操作 */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-gray-200 bg-white px-4">
        {/* 会话下拉 */}
        <select
          value={activeId ?? ""}
          onChange={(e) => handleSwitchSession(e.target.value)}
          aria-label="选择会话"
          className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm text-gray-700 focus:border-blue-400 focus:outline-none"
        >
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title || "未命名会话"} ({s.message_count} 条消息)
            </option>
          ))}
        </select>

        {/* 新对话 */}
        <button
          onClick={handleNewSession}
          aria-label="新建对话"
          className="shrink-0 rounded bg-blue-500 px-3 py-1 text-xs text-white transition-colors hover:bg-blue-600"
          title="新建对话"
        >
          + 新对话
        </button>

        {/* 删除当前会话 */}
        {activeSession && (
          <button
            onClick={() => handleDeleteSession(activeSession.id)}
            aria-label="删除当前会话"
            className="shrink-0 rounded px-2 py-1 text-xs text-gray-400 transition-colors hover:bg-red-50 hover:text-red-500"
            title="删除当前会话"
          >
            删除
          </button>
        )}
      </header>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto bg-white">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="mb-2 text-gray-400">开始与 AI 助教对话吧!</p>
              <p className="text-xs text-gray-300">
                输入你的问题，AI 会根据课件内容为你解答
              </p>
            </div>
          </div>
        ) : (
          <div className="py-2" role="log" aria-live="polite">
            {messages.map((msg) => {
              const isCurrentStreaming =
                isStreaming && msg.id === streamingMsgIdRef.current;
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isStreaming={isCurrentStreaming}
                  streamingTokens={
                    isCurrentStreaming ? streamingTokens : undefined
                  }
                />
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* 流式错误 / 重连提示 */}
        {(streamError || isReconnecting) && (
          <div className="mx-4 mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700" role="alert">
            {isReconnecting ? "正在重连..." : streamError}
            {streamError && !isReconnecting && (
              <button
                onClick={() => setStreamError(null)}
                aria-label="关闭错误提示"
                className="ml-2 text-amber-500 hover:text-amber-700"
              >
                x
              </button>
            )}
          </div>
        )}
      </div>

      {/* 输入区域 */}
      <div className="shrink-0 border-t border-gray-200 bg-white p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="输入消息"
            placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
            rows={2}
            disabled={isStreaming}
            className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-blue-400 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
          />
          {isStreaming ? (
            <button
              onClick={handleCancel}
              className="shrink-0 rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
            >
              停止
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!inputValue.trim()}
              className="shrink-0 rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-blue-300"
            >
              发送
            </button>
          )}
        </div>
        <p className="mt-1 text-xs text-gray-300">
          AI 回复仅供参考，请以课件内容为准
        </p>
      </div>
    </div>
  );
}
