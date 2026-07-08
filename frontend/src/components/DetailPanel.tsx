import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { remarkPlugins, rehypePlugins } from "../lib/markdown";
import client from "../api/client";
import type { KnowledgePoint, Homework, HomeworkDetail, GeneratedQuestion, ProgressStatus, StudyProgress } from "../types";

/* ── 组件 Props ──────────────────────────────── */

export interface DetailPanelProps {
  knowledgePoint: KnowledgePoint | null;
  homework: Homework | null;
  selectedQuestion: GeneratedQuestion | null;
  loading: boolean;
  error: string | null;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onQuoteToChat: (text: string) => void;
  onRetry?: () => void;
  onGenerateQuestions?: (kpId: string) => void;
  onProgressChange?: () => void;
}

/* ── 小图标 ──────────────────────────────────── */

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-3 w-3 text-gray-400 transition-transform ${open ? "rotate-90" : ""}`}
      fill="currentColor"
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <path d="M6 4l8 6-8 6V4z" />
    </svg>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-8">
      <svg
        className="h-5 w-5 animate-spin text-gray-400"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
    </div>
  );
}

/* ── 例题卡片 ────────────────────────────────── */

function ExampleCard({
  question,
  answer,
  explanation,
}: {
  question: string;
  answer: string;
  explanation: string | null;
}) {
  const [answerOpen, setAnswerOpen] = useState(false);

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <button
        type="button"
        onClick={() => setAnswerOpen((v) => !v)}
        className="flex w-full items-start gap-2 px-4 py-3 text-left hover:bg-gray-50"
      >
        <span className="mt-0.5">
          <ChevronIcon open={answerOpen} />
        </span>
        <span className="text-sm text-gray-800">{question}</span>
      </button>

      {answerOpen && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-2">
          <div>
            <span className="text-xs font-medium text-gray-500">答案</span>
            <p className="mt-1 text-sm text-gray-700">{answer}</p>
          </div>
          {explanation && (
            <div>
              <span className="text-xs font-medium text-gray-500">解析</span>
              <div className="prose prose-sm mt-1 max-w-none text-gray-600">
                <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
                  {explanation}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── 引用按钮 ────────────────────────────────── */

function QuoteButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50"
    >
      <svg
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
        />
      </svg>
      在聊天中引用
    </button>
  );
}

/* ── AnswerBlock 可折叠答案组件 ──────────────── */
function AnswerBlock({ answer, explanation }: { answer: string; explanation?: string | null }) {
  const [showAnswer, setShowAnswer] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setShowAnswer(!showAnswer)}
        className="inline-flex items-center gap-1 rounded-md border border-green-200 px-3 py-1.5 text-xs font-medium text-green-600 transition-colors hover:bg-green-50"
        aria-label={showAnswer ? "隐藏答案" : "显示答案"}
      >
        {showAnswer ? "隐藏答案" : "显示答案"}
      </button>
      {showAnswer && (
        <div className="mt-2 rounded-md border border-green-100 bg-green-50 p-3">
          <p className="text-sm font-medium text-green-800">答案</p>
          <p className="mt-1 text-sm text-green-700">{answer}</p>
          {explanation && (
            <>
              <p className="mt-2 text-sm font-medium text-green-800">解析</p>
              <div className="prose prose-sm mt-1 max-w-none text-green-700">
                {explanation}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── DetailPanel ─────────────────────────────── */

export default function DetailPanel({
  knowledgePoint,
  homework,
  selectedQuestion,
  loading,
  error,
  collapsed = false,
  onToggleCollapse,
  onQuoteToChat,
  onRetry,
  onGenerateQuestions,
  onProgressChange,
}: DetailPanelProps) {
  const [generatingQuestions, setGeneratingQuestions] = useState(false);
  const [generatedQuestions, setGeneratedQuestions] = useState<GeneratedQuestion[]>([]);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [generationStream, setGenerationStream] = useState("");
  const [expandedGenIds, setExpandedGenIds] = useState<Set<string>>(new Set());

  // 进度状态
  const [progressStatus, setProgressStatus] = useState<ProgressStatus | null>(null);
  const [progressLoading, setProgressLoading] = useState(false);

  // 当知识点变化时获取进度
  useEffect(() => {
    if (!knowledgePoint) {
      setProgressStatus(null);
      return;
    }

    let cancelled = false;
    const fetchProgress = async () => {
      setProgressLoading(true);
      try {
        const res = await client.get<StudyProgress>(
          `/knowledge-points/${knowledgePoint.id}/progress`,
        );
        if (!cancelled) {
          setProgressStatus(res.data.status as ProgressStatus);
        }
      } catch {
        if (!cancelled) {
          setProgressStatus("not_started");
        }
      } finally {
        if (!cancelled) {
          setProgressLoading(false);
        }
      }
    };

    void fetchProgress();
    return () => {
      cancelled = true;
    };
  }, [knowledgePoint?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 标记状态
  const handleMarkStatus = useCallback(
    async (status: ProgressStatus) => {
      if (!knowledgePoint) return;

      try {
        const res = await client.patch<StudyProgress>(
          `/knowledge-points/${knowledgePoint.id}/progress`,
          { action: "mark_status", manual_status: status },
        );
        setProgressStatus(res.data.status as ProgressStatus);
        onProgressChange?.();
      } catch {
        // silently fail
      }
    },
    [knowledgePoint, onProgressChange],
  );

  const handleGenerateQuestions = async (kpId: string) => {
    if (onGenerateQuestions) {
      onGenerateQuestions(kpId);
      return;
    }

    // 内置 SSE 流式处理
    setGeneratingQuestions(true);
    setGenerationError(null);
    setGeneratedQuestions([]);
    setGenerationStream("");

    const controller = new AbortController();

    try {
      // 从 axios client 实例读取 baseURL 和 headers，避免绕过 interceptor
      const baseURL = client.defaults.baseURL ?? "/api";
      const url = `${baseURL}/knowledge-points/${kpId}/generate-questions`;

      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: 3, question_type: "auto" }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `请求失败 (${response.status})`);
      }

      if (!response.body) {
        throw new Error("响应体不可读");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";

          for (const part of parts) {
            const trimmed = part.trim();
            if (!trimmed) continue;

            let dataLine = trimmed;
            if (trimmed.startsWith("data: ")) {
              dataLine = trimmed.slice(6);
            }

            try {
              const event = JSON.parse(dataLine);

              switch (event.type) {
                case "chunk":
                  setGenerationStream((prev) => prev + event.content);
                  break;
                case "question_parsed":
                  setGeneratedQuestions((prev) => [...prev, event.question]);
                  break;
                case "done":
                  setGeneratingQuestions(false);
                  break;
                case "error":
                  setGenerationError(event.message);
                  setGeneratingQuestions(false);
                  break;
              }
            } catch {
              // 忽略无法解析的行
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      const message =
        err instanceof Error ? err.message : "出题请求失败";
      setGenerationError(message);
    } finally {
      setGeneratingQuestions(false);
    }
  };

  const handleQuote = () => {
    if (knowledgePoint) {
      const summary = `**${knowledgePoint.title}**\n\n${knowledgePoint.content.slice(0, 300)}${knowledgePoint.content.length > 300 ? "..." : ""}`;
      onQuoteToChat(summary);
    }
  };

  // ── 收起状态 ──────────────────────────────
  if (collapsed) {
    return (
      <aside className="flex w-[36px] shrink-0 flex-col items-center border-l border-gray-200 bg-gray-50 py-3 transition-[width] duration-200">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="mb-3 rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
          title="展开详情面板"
          aria-label="展开详情面板"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 5l-7 7 7 7" />
          </svg>
        </button>
        <span
          className="select-none text-xs font-medium text-gray-400"
          style={{ writingMode: "vertical-rl" }}
        >
          详情
        </span>
      </aside>
    );
  }

  // ── 正常状态 ──────────────────────────────
  return (
    <aside className="flex w-[350px] shrink-0 flex-col border-l border-gray-200 bg-gray-50 transition-[width] duration-200">
      {/* 标题栏 */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 px-4">
        <span className="text-base font-semibold text-gray-700">
          {homework ? "作业详情" : selectedQuestion ? "题目详情" : "知识点详情"}
        </span>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-600"
          aria-label="收起详情面板"
          title="收起"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto">
        {/* ── 加载态 ──────────────────────── */}
        {loading && (
          <div className="flex flex-col items-center gap-2 py-8">
            <Spinner />
            <span className="text-xs text-gray-400">加载详情中…</span>
          </div>
        )}

        {/* ── 错误态 ──────────────────────── */}
        {!loading && error && (
          <div className="flex flex-col items-center gap-3 px-4 py-8">
            <p className="text-center text-sm text-red-600">{error}</p>
            {onRetry && (
              <button
                onClick={onRetry}
                className="rounded-md bg-blue-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600"
              >
                重试
              </button>
            )}
          </div>
        )}

        {/* ── 作业详情 ────────────────────── */}
        {!loading && !error && homework && (
          <div className="space-y-4 p-4">
            <h2 className="text-lg font-semibold text-gray-800">
              {homework.title}
            </h2>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span className={`inline-block rounded-full px-2 py-px text-[10px] font-medium ${
                homework.status === "completed" ? "bg-green-100 text-green-700" :
                homework.status === "processing" ? "bg-yellow-100 text-yellow-700" :
                homework.status === "failed" ? "bg-red-100 text-red-700" :
                "bg-gray-100 text-gray-500"
              }`}>
                {homework.status === "completed" ? "已完成" :
                 homework.status === "processing" ? "处理中" :
                 homework.status === "failed" ? "失败" : homework.status}
              </span>
              <span>{homework.file_type.toUpperCase()}</span>
              <span>{(homework.file_size / 1024).toFixed(0)} KB</span>
            </div>

            {/* 解答列表 */}
            {(homework as HomeworkDetail).solutions != null && (homework as HomeworkDetail).solutions.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-gray-700">
                  解答 ({(homework as HomeworkDetail).solutions.length} 题)
                </h3>
                {(homework as HomeworkDetail).solutions.map(
                  (s) => (
                    <div
                      key={s.id}
                      className="rounded-lg border border-gray-200 bg-white p-3"
                    >
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <span className="font-medium">第 {s.question_number} 题</span>
                        {s.answer_text ? (
                          <span className="text-green-600">已解答</span>
                        ) : (
                          <span className="text-yellow-600">待解答</span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-gray-700 line-clamp-3">
                        {s.question_text}
                      </p>
                      {s.answer_text && (
                        <div className="prose prose-sm mt-2 max-w-none text-gray-600">
                          <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
                            {s.answer_text}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  ),
                )}
              </div>
            )}
          </div>
        )}

        {/* ── 知识点详情 ──────────────────── */}
        {!loading && !error && knowledgePoint && !homework && (
          <div className="space-y-4 p-4">
            {/* 出题练习按钮 */}
            <button
              type="button"
              onClick={() => void handleGenerateQuestions(knowledgePoint.id)}
              disabled={generatingQuestions}
              className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-purple-300 bg-purple-50 px-4 py-2.5 text-sm font-medium text-purple-700 transition-colors hover:bg-purple-100 disabled:opacity-60"
            >
              {generatingQuestions ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  AI 正在出题…
                </>
              ) : (
                <>
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                  AI 出题练习
                </>
              )}
            </button>

            {/* 生成流式文本（出题中） */}
            {generatingQuestions && generationStream && (
              <div className="rounded-lg border border-purple-200 bg-purple-50 p-3">
                <p className="text-xs text-purple-600 whitespace-pre-wrap max-h-32 overflow-y-auto">
                  {generationStream}
                </p>
              </div>
            )}

            {/* 生成错误 */}
            {generationError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                <p className="text-sm text-red-600">{generationError}</p>
              </div>
            )}

            {/* 已生成题目 */}
            {generatedQuestions.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-medium text-gray-700">
                  生成题目 ({generatedQuestions.length})
                </h3>
                <div className="space-y-2">
                  {generatedQuestions.map((q) => (
                    <div key={q.id} className="rounded-lg border border-purple-200 bg-white">
                      <button
                        type="button"
                        onClick={() => setExpandedGenIds((prev) => {
                          const next = new Set(prev);
                          if (next.has(q.id)) next.delete(q.id);
                          else next.add(q.id);
                          return next;
                        })}
                        className="flex w-full items-start gap-2 px-4 py-3 text-left hover:bg-gray-50"
                      >
                        <svg
                          className={`mt-0.5 h-3 w-3 shrink-0 text-gray-400 transition-transform ${
                            expandedGenIds.has(q.id) ? "rotate-90" : ""
                          }`}
                          fill="currentColor"
                          viewBox="0 0 20 20"
                          aria-hidden="true"
                        >
                          <path d="M6 4l8 6-8 6V4z" />
                        </svg>
                        <span className={`inline-block rounded px-1.5 py-px text-[10px] font-medium shrink-0 ${
                          q.question_type === "选择题" ? "bg-blue-100 text-blue-700" :
                          q.question_type === "填空题" ? "bg-green-100 text-green-700" :
                          q.question_type === "计算题" ? "bg-orange-100 text-orange-700" :
                          "bg-purple-100 text-purple-700"
                        }`}>
                          {q.question_type}
                        </span>
                        <span className="text-sm text-gray-800">{q.question_text}</span>
                      </button>
                      {expandedGenIds.has(q.id) && (
                      <div className="border-t border-gray-100 bg-gray-50 px-4 py-3 space-y-2">
                        {q.options && q.options.length > 0 && (
                          <div>
                            <span className="text-xs font-medium text-gray-500">选项</span>
                            <ul className="mt-1 space-y-0.5">
                              {q.options.map((opt, idx) => (
                                <li key={idx} className="text-sm text-gray-700">{opt}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div>
                          <span className="text-xs font-medium text-gray-500">答案</span>
                          <p className="mt-1 text-sm text-gray-700 whitespace-pre-wrap">{q.answer_text}</p>
                        </div>
                        {q.explanation && (
                          <div>
                            <span className="text-xs font-medium text-gray-500">解析</span>
                            <p className="mt-1 text-sm text-gray-600 whitespace-pre-wrap">{q.explanation}</p>
                          </div>
                        )}
                      </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 学习进度状态按钮 */}
            <div>
              <span className="mb-1.5 block text-xs font-medium text-gray-500">
                学习进度
                {progressLoading && (
                  <span className="ml-1 inline-block h-3 w-3 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
                )}
              </span>
              <div
                className="flex gap-1.5"
                role="group"
                aria-label="学习进度状态切换"
              >
                {([
                  ["not_started", "未开始", "⚪"],
                  ["in_progress", "学习中", "🟡"],
                  ["struggling", "需加强", "🔴"],
                  ["mastered", "已掌握", "🟢"],
                ] as const).map(([status, label, icon]) => {
                  const isActive = progressStatus === status;
                  return (
                    <button
                      key={status}
                      type="button"
                      onClick={() => void handleMarkStatus(status as ProgressStatus)}
                      disabled={progressLoading}
                      aria-pressed={isActive}
                      aria-label={`标记为${label}`}
                      className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                        isActive
                          ? "bg-blue-500 text-white ring-2 ring-blue-300 ring-offset-1"
                          : "bg-white text-gray-600 ring-1 ring-gray-200 hover:bg-gray-50 hover:ring-gray-300"
                      } disabled:opacity-50`}
                      title={`标记为「${label}」`}
                    >
                      <span className="mr-1">{icon}</span>
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>

            <h2 className="text-lg font-semibold text-gray-800">
              {knowledgePoint.title}
            </h2>

            <div className="flex items-center gap-3 text-xs text-gray-500">
              {knowledgePoint.page_number != null && (
                <span>第 {knowledgePoint.page_number} 页</span>
              )}
            </div>

            <QuoteButton onClick={handleQuote} />

            <div className="prose prose-sm max-w-none text-gray-700">
              <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
                {knowledgePoint.content}
              </ReactMarkdown>
            </div>

            {knowledgePoint.examples.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-medium text-gray-700">
                  相关例题 ({knowledgePoint.examples.length})
                </h3>
                <div className="space-y-2">
                  {knowledgePoint.examples.map((ex) => (
                    <ExampleCard
                      key={ex.id}
                      question={ex.question}
                      answer={ex.answer}
                      explanation={ex.explanation}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 题目详情 ── */}
        {!loading && !error && selectedQuestion && (
          <div className="space-y-4 p-4">
            <h2 className="text-lg font-semibold text-gray-800">题目详情</h2>
            <div className="flex items-center gap-2">
              <span className="inline-block rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-700">
                {selectedQuestion.question_type}
              </span>
              <span className="inline-block rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-500">
                {selectedQuestion.difficulty}
              </span>
            </div>
            <p className="text-sm text-gray-800 leading-relaxed">{selectedQuestion.question_text}</p>
            {selectedQuestion.options && selectedQuestion.options.length > 0 && (
              <div className="space-y-1">
                {selectedQuestion.options.map((opt, i) => (
                  <p key={i} className="text-sm text-gray-600">{opt}</p>
                ))}
              </div>
            )}
            <AnswerBlock answer={selectedQuestion.answer_text} explanation={selectedQuestion.explanation} />
            <button type="button" onClick={() => {
              const text = `**${selectedQuestion.question_text}**\n\n答案：${selectedQuestion.answer_text}${selectedQuestion.explanation ? `\n\n解析：${selectedQuestion.explanation}` : ""}`;
              onQuoteToChat(text);
            }} className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50">
              💬 引用到聊天
            </button>
            {selectedQuestion.knowledge_points && selectedQuestion.knowledge_points.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-medium text-gray-700">考察知识点</h3>
                <div className="flex flex-wrap gap-1.5">
                  {selectedQuestion.knowledge_points.map((kp) => (
                    <span key={kp.id} className="inline-block rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-600">{kp.title}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 空态 ── */}
        {!loading && !error && !knowledgePoint && !homework && !selectedQuestion && (
          <div className="flex flex-col items-center gap-2 py-8 px-4">
            <svg
              className="h-10 w-10 text-gray-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <p className="text-center text-sm text-gray-500">
              请选择左侧知识点查看详情
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
