import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { remarkPlugins, rehypePlugins } from "@/shared/markdown/markdown";
import StreamingMessage from "./StreamingMessage";
import type { ChatMessage } from "./types";

/* ── 组件属性 ────────────────────────────────────── */

export interface MessageBubbleProps {
  message: ChatMessage;
  /** 是否正在流式接收该消息 */
  isStreaming?: boolean;
  /** 流式 tokens（仅 isStreaming 时使用） */
  streamingTokens?: string[];
}

/* ── 辅助函数 ────────────────────────────────────── */

/** 格式化时间戳 */
function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();

  const time = d.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (isToday) {
    return time;
  }
  return (
    d.toLocaleDateString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
    }) +
    " " +
    time
  );
}

/* ── MessageBubble 组件 ──────────────────────────── */

export default function MessageBubble({
  message,
  isStreaming = false,
  streamingTokens,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  // 提取 role 标签
  const roleLabel = useMemo(() => {
    switch (message.role) {
      case "user":
        return "你";
      case "assistant":
        return "AI 助手";
      case "system":
        return "系统";
      default:
        return message.role;
    }
  }, [message.role]);

  // 系统消息简化展示
  if (message.role === "system") {
    return (
      <div className="flex justify-center py-2">
        <span className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-400">
          {message.content}
        </span>
      </div>
    );
  }

  // 决定助手消息是否使用流式渲染
  const useStreaming = isStreaming && message.role === "assistant";

  return (
    <div
      className={`flex gap-2 px-4 py-2 ${
        isUser ? "flex-row-reverse" : "flex-row"
      }`}
    >
      {/* 头像 */}
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-medium text-white ${
          isUser ? "bg-blue-500" : "bg-gray-500"
        }`}
      >
        {isUser ? "U" : "AI"}
      </div>

      {/* 消息主体 */}
      <div
        className={`flex max-w-[75%] flex-col ${
          isUser ? "items-end" : "items-start"
        }`}
      >
        {/* 角色 & 时间戳 */}
        <div
          className={`mb-0.5 flex items-center gap-2 text-xs text-gray-400 ${
            isUser ? "flex-row-reverse" : "flex-row"
          }`}
        >
          <span>{roleLabel}</span>
          <span>{isStreaming ? "接收中..." : formatTime(message.created_at)}</span>
        </div>

        {/* 气泡 */}
        <div
          className={`rounded-lg px-4 py-2 text-sm leading-relaxed ${
            isUser
              ? "bg-blue-500 text-white"
              : "bg-gray-100 text-gray-800"
          }`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : useStreaming ? (
            <StreamingMessage
              tokens={streamingTokens ?? [message.content]}
              isStreaming={isStreaming}
            />
          ) : (
            <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-code:rounded prose-code:bg-gray-200 prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-pre:bg-gray-800 prose-pre:text-gray-100">
              <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {!isUser && message.citations.length > 0 && !isStreaming && (
          <div className="mt-1.5 w-full rounded-md border border-blue-100 bg-blue-50 p-2">
            <p className="mb-1 text-[11px] font-medium text-blue-700">回答依据</p>
            <div className="space-y-1">
              {message.citations.map((citation, index) => (
                <div key={`${citation.courseware_id}-${citation.page_number}-${index}`} className="text-[11px] text-blue-700">
                  <span className="font-medium">{citation.courseware_title}</span>
                  {citation.page_number != null ? <span> · 第 {citation.page_number} 页</span> : null}
                  {citation.excerpt ? <p className="mt-0.5 line-clamp-2 text-blue-600">{citation.excerpt}</p> : null}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
