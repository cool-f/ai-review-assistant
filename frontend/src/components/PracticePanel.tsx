import { useState, useEffect, useCallback, useRef } from "react";
import client from "../api/client";
import type { GeneratedQuestion } from "../types";

/* ── Props ──────────────────────────────────────────── */
export interface PracticePanelProps {
  selectedCoursewareId: string | null;
  onQuoteToChat: (text: string) => void;
  onSelectQuestion?: (question: GeneratedQuestion) => void;
}

/* ── 题型颜色映射 ─────────────────────────────────── */
const TYPE_COLORS: Record<string, string> = {
  "选择题": "bg-blue-100 text-blue-700",
  "填空题": "bg-purple-100 text-purple-700",
  "计算题": "bg-orange-100 text-orange-700",
  "证明题": "bg-green-100 text-green-700",
};

const DIFFICULTY_LABELS: Record<string, string> = {
  "简单": "bg-green-50 text-green-600 border-green-200",
  "中等": "bg-yellow-50 text-yellow-600 border-yellow-200",
  "困难": "bg-red-50 text-red-600 border-red-200",
};

/* ── 题目卡片 ──────────────────────────────────────── */
function QuestionCard({
  question,
  onQuote,
  onSelect,
}: {
  question: GeneratedQuestion;
  onQuote: (q: GeneratedQuestion) => void;
  onSelect: (q: GeneratedQuestion) => void;
}) {
  const [showAnswer, setShowAnswer] = useState(false);

  return (
    <div
      className="cursor-pointer rounded-lg border border-gray-200 bg-white p-4 transition-colors hover:border-blue-200 hover:shadow-sm"
      onClick={() => onSelect(question)}
      role="button"
      tabIndex={0}
      aria-label={`题目: ${question.question_text.slice(0, 40)}...`}
      onKeyDown={(e) => { if (e.key === 'Enter') onSelect(question); }}
    >
      {/* 标题行：题型 + 难度 */}
      <div className="mb-2 flex items-center gap-2">
        <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TYPE_COLORS[question.question_type] || "bg-gray-100 text-gray-600"}`}>
          {question.question_type}
        </span>
        <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${DIFFICULTY_LABELS[question.difficulty] || "border-gray-200 text-gray-500"}`}>
          {question.difficulty}
        </span>
        {question.source_style === "from_example" && (
          <span className="text-xs text-gray-400">参考例题</span>
        )}
      </div>

      {/* 题目正文 */}
      <p className="text-sm text-gray-800 leading-relaxed">{question.question_text}</p>

      {/* 选择题选项 */}
      {question.options && question.options.length > 0 && (
        <div className="mt-2 space-y-1">
          {question.options.map((opt, i) => (
            <p key={i} className="text-sm text-gray-600">{opt}</p>
          ))}
        </div>
      )}

      {/* 答案区域（默认隐藏） */}
      {showAnswer && (
        <div className="mt-3 rounded-md border border-green-100 bg-green-50 p-3">
          <p className="text-sm font-medium text-green-800">答案</p>
          <p className="mt-1 text-sm text-green-700">{question.answer_text}</p>
          {question.explanation && (
            <>
              <p className="mt-2 text-sm font-medium text-green-800">解析</p>
              <div className="prose prose-sm mt-1 max-w-none text-green-700">
                {question.explanation}
              </div>
            </>
          )}
        </div>
      )}

      {/* 操作按钮 */}
      <div className="mt-3 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          onClick={() => setShowAnswer(!showAnswer)}
          className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50"
          aria-label={showAnswer ? "隐藏答案" : "显示答案"}
        >
          {showAnswer ? "隐藏答案" : "显示答案"}
        </button>
        <button
          type="button"
          onClick={() => onQuote(question)}
          className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50"
          aria-label="引用到聊天"
        >
          💬 引用到聊天
        </button>
      </div>
    </div>
  );
}

/* ── 练习主面板 ────────────────────────────────────── */
export default function PracticePanel({
  selectedCoursewareId,
  onQuoteToChat,
  onSelectQuestion,
}: PracticePanelProps) {
  const [questions, setQuestions] = useState<GeneratedQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchQuestions = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    try {
      const params = selectedCoursewareId
        ? `?courseware_id=${selectedCoursewareId}&size=100`
        : "?size=100";
      const res = await client.get<{ items: GeneratedQuestion[] }>(
        `/questions${params}`,
        { signal: controller.signal }
      );
      if (!controller.signal.aborted) {
        setQuestions(res.data.items || []);
      }
    } catch (err: unknown) {
      if ((err as any)?.name === "CanceledError" || controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : "加载题目失败");
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [selectedCoursewareId]);

  useEffect(() => {
    fetchQuestions();
    return () => { abortRef.current?.abort(); };
  }, [fetchQuestions]);

  const handleQuote = useCallback(
    (q: GeneratedQuestion) => {
      const text = `**${q.question_text}**\n\n答案：${q.answer_text}${q.explanation ? `\n\n解析：${q.explanation}` : ""}`;
      onQuoteToChat(text);
    },
    [onQuoteToChat],
  );

  // ── 加载态 ───────────────────────────────────
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <svg className="mx-auto h-6 w-6 animate-spin text-gray-400" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="mt-2 text-sm text-gray-400">加载练习题...</p>
        </div>
      </div>
    );
  }

  // ── 错误态 ───────────────────────────────────
  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
        <p className="text-sm text-red-500">{error}</p>
        <button onClick={fetchQuestions} className="rounded bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600">
          重试
        </button>
      </div>
    );
  }

  // ── 空态 ─────────────────────────────────────
  if (questions.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6">
        <svg className="h-12 w-12 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-3-3v6m-8 4h16a1 1 0 001-1V7a1 1 0 00-1-1H5a1 1 0 00-1 1v11a1 1 0 001 1z" />
        </svg>
        <p className="text-center text-sm text-gray-500">
          {selectedCoursewareId
            ? "该课件暂无练习题"
            : "还没有生成练习题，请在知识点详情中点击「出题练习」生成"}
        </p>
        {!selectedCoursewareId && (
          <p className="text-xs text-gray-400">
            也可以先在左侧选中一个课件，再生成练习题
          </p>
        )}
      </div>
    );
  }

  // ── 正常态 ────────────────────────────────────
  return (
    <div className="flex h-full flex-col">
      {/* 顶部提示 */}
      <div className="flex shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <div>
          <h2 className="text-base font-semibold text-gray-800">
            {selectedCoursewareId ? "当前课件的练习题" : "全部练习题"}
          </h2>
          <p className="mt-0.5 text-xs text-gray-400">
            {questions.length} 道题 · 点击题目查看详情，点击「显示答案」查看解答
          </p>
        </div>
        <button
          onClick={fetchQuestions}
          className="rounded-md border border-gray-200 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50"
          aria-label="刷新题目列表"
        >
          刷新
        </button>
      </div>

      {/* 题目列表 */}
      <div className="flex-1 overflow-y-auto bg-gray-50 p-6">
        {questions.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            暂无练习题
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {questions.map((q) => (
              <QuestionCard
                key={q.id}
                question={q}
                onQuote={handleQuote}
                onSelect={(qObj) => onSelectQuestion?.(qObj)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
