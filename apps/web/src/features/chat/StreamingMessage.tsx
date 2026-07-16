import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { remarkPlugins, rehypePlugins } from "@/shared/markdown/markdown";

/* ── 组件属性 ────────────────────────────────────── */

export interface StreamingMessageProps {
  /** SSE 逐块到达的文本 token 数组 */
  tokens: string[];
  /** 是否仍在流式接收中（false 时隐藏光标，强制渲染完整 Markdown） */
  isStreaming: boolean;
}

/* ── 辅助函数 ────────────────────────────────────── */

/**
 * 将累积的 tokens 按段落完整性拆分：
 * - 已闭合段落（以 \n\n 结尾）→ 可安全渲染 Markdown
 * - 最后一个未闭合片段 → 纯文本展示，避免 Markdown 解析一半的标签
 */
function splitParagraphs(
  text: string,
  acceptLast: boolean,
): { closed: string; open: string } {
  if (!text) return { closed: "", open: "" };

  // 当流式已结束（acceptLast=true），全部视为已闭合段落
  if (acceptLast) {
    return { closed: text, open: "" };
  }

  // 找到最后一个 \n\n 的位置
  const lastDoubleNewline = text.lastIndexOf("\n\n");

  if (lastDoubleNewline === -1) {
    // 没有闭合段落 — 全部视为未完成
    return { closed: "", open: text };
  }

  const closed = text.slice(0, lastDoubleNewline + 2); // 包含结尾的 \n\n
  const open = text.slice(lastDoubleNewline + 2);

  return { closed, open };
}

/* ── StreamingMessage 组件 ───────────────────────── */

/**
 * 流式消息渲染组件
 *
 * - 将 tokens 拼接为完整文本，按 \n\n 检测段落闭合
 * - 已闭合段落通过 ReactMarkdown 渲染
 * - 未闭合片段以纯文本展示，避免 Markdown 语法碎片
 * - 流式接收中显示闪烁光标
 */
export default function StreamingMessage({
  tokens,
  isStreaming,
}: StreamingMessageProps) {
  const fullContent = useMemo(() => tokens.join(""), [tokens]);

  const { closed, open } = useMemo(() => {
    if (!fullContent) return { closed: "", open: "" };
    // isStreaming=true 时最后一段可能未闭合
    return splitParagraphs(fullContent, !isStreaming);
  }, [fullContent, isStreaming]);

  // 无内容时的占位
  if (!fullContent) {
    return (
      <span className="inline">
        <span className="animate-cursor-blink text-gray-400">|</span>
      </span>
    );
  }

  return (
    <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-code:rounded prose-code:bg-gray-200 prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-pre:bg-gray-800 prose-pre:text-gray-100">
      {/* 已闭合段落 — 安全渲染 Markdown */}
      {closed && (
        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
          {closed}
        </ReactMarkdown>
      )}

      {/* 未闭合片段 — 纯文本 + 闪烁光标 */}
      {open && (
        <p className="whitespace-pre-wrap break-words">
          {open}
          {isStreaming && (
            <span className="animate-cursor-blink font-normal text-gray-400">
              |
            </span>
          )}
        </p>
      )}

      {/* 无未闭合片段时的光标（所有段落皆已闭合，但仍在流式接收） */}
      {!open && isStreaming && (
        <span className="animate-cursor-blink text-gray-400">|</span>
      )}
    </div>
  );
}
