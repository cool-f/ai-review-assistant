import { useState, useEffect, useCallback, useRef } from "react";
import client from "@/shared/api/client";
import type { GeneratedQuestion } from "@/shared/types";

/* ── Props ──────────────────────────────────────────── */
export interface PracticePanelProps {
  courseId: string;
  selectedCoursewareId: string | null;
  onQuoteToChat: (text: string) => void;
  onSelectQuestion?: (question: GeneratedQuestion) => void;
  onProgressChange?: () => void;
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

interface QuestionAttempt {
  id: string;
  question_id: string;
  submitted_answer: string;
  is_correct: boolean;
  feedback: string;
  grading_method: string;
  counted_for_progress: boolean;
  created_at: string;
}

/* ── 题目卡片 ──────────────────────────────────────── */
export function QuestionCard({
  question,
  courseId,
  onQuote,
  onSelect,
  onProgressChange,
}: {
  question: GeneratedQuestion;
  courseId: string;
  onQuote: (q: GeneratedQuestion) => void;
  onSelect: (q: GeneratedQuestion) => void;
  onProgressChange?: () => void;
}) {
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{
    correct: boolean; feedback: string; counted: boolean; status: string;
  } | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<QuestionAttempt[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadAttemptHistory = useCallback(async () => {
    try {
      const response = await client.get<QuestionAttempt[]>(
        `/questions/${question.id}/attempts`,
        { params: { course_id: courseId } },
      );
      setAttempts(response.data);
      setHistoryError(null);
    } catch {
      setHistoryError("作答历史加载失败");
    }
  }, [courseId, question.id]);

  useEffect(() => {
    void loadAttemptHistory();
  }, [loadAttemptHistory]);

  const submitAnswer = async () => {
    if (!answer.trim() || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await client.post<{
        attempt: QuestionAttempt;
        progress: { status: string };
      }>(`/questions/${question.id}/attempts`, { answer: answer.trim() }, { params: { course_id: courseId } });
      setResult({
        correct: response.data.attempt.is_correct,
        feedback: response.data.attempt.feedback,
        counted: response.data.attempt.counted_for_progress,
        status: response.data.progress.status,
      });
      setAttempts((current) => [
        response.data.attempt,
        ...current.filter((attempt) => attempt.id !== response.data.attempt.id),
      ]);
      onProgressChange?.();
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "提交失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

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

      {/* 作答区 */}
      {question.options && question.options.length > 0 && (
        <div className="mt-2 space-y-1">
          {question.options.map((opt, i) => (
            <label key={i} className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
              <input
                type="radio"
                name={`answer-${question.id}`}
                value={opt}
                checked={answer === opt}
                onChange={() => setAnswer(opt)}
              />
              <span>{opt}</span>
            </label>
          ))}
        </div>
      )}
      {!question.options?.length && (
        <textarea
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          onClick={(event) => event.stopPropagation()}
          rows={3}
          placeholder="请输入你的答案"
          className="mt-3 w-full rounded-md border border-gray-300 p-2 text-sm outline-none focus:border-blue-500"
        />
      )}

      {result && (
        <div className={`mt-3 rounded-md border p-3 ${result.correct ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-800"}`}>
          <p className="text-sm font-medium">{result.correct ? "回答正确" : "回答不正确"}</p>
          <p className="mt-1 text-sm">{result.feedback}</p>
          <p className="mt-1 text-xs opacity-75">最新进度：{result.status}{result.counted ? " · 本题已计入进度" : " · 本题此前已计入，当前仅保留作答历史"}</p>
        </div>
      )}
      {submitError && <p className="mt-2 text-xs text-red-600">{submitError}</p>}

      {/* 操作按钮 */}
      <div className="mt-3 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          onClick={() => void submitAnswer()}
          disabled={!answer.trim() || submitting}
          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          aria-label="提交答案"
        >
          {submitting ? "判分中…" : result ? "再次提交" : "提交答案"}
        </button>
        <button
          type="button"
          onClick={() => onQuote(question)}
          className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50"
          aria-label="引用到聊天"
        >
          💬 引用到聊天
        </button>
        <button
          type="button"
          onClick={() => setHistoryOpen((current) => !current)}
          className="rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
          aria-expanded={historyOpen}
        >
          作答历史（{attempts.length}）
        </button>
      </div>

      {historyOpen && (
        <div
          className="mt-3 space-y-2 border-t border-gray-100 pt-3"
          onClick={(event) => event.stopPropagation()}
        >
          {historyError && <p className="text-xs text-red-600">{historyError}</p>}
          {!historyError && attempts.length === 0 && (
            <p className="text-xs text-gray-400">还没有作答记录</p>
          )}
          {attempts.map((attempt) => (
            <div key={attempt.id} className="rounded-md bg-gray-50 p-3 text-xs text-gray-600">
              <div className="flex flex-wrap items-center gap-2">
                <span className={attempt.is_correct ? "font-medium text-green-700" : "font-medium text-red-700"}>
                  {attempt.is_correct ? "正确" : "错误"}
                </span>
                <span>{attempt.grading_method === "deterministic" ? "规则判分" : "AI 判分"}</span>
                <span>{attempt.counted_for_progress ? "已计入进度" : "未重复计入进度"}</span>
                <time dateTime={attempt.created_at}>
                  {new Date(attempt.created_at).toLocaleString("zh-CN")}
                </time>
              </div>
              <p className="mt-1 break-words">作答：{attempt.submitted_answer}</p>
              <p className="mt-1 break-words text-gray-500">反馈：{attempt.feedback}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── 练习主面板 ────────────────────────────────────── */
export default function PracticePanel({
  courseId,
  selectedCoursewareId,
  onQuoteToChat,
  onSelectQuestion,
  onProgressChange,
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
        ? `?course_id=${courseId}&courseware_id=${selectedCoursewareId}&size=100`
        : `?course_id=${courseId}&size=100`;
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
  }, [courseId, selectedCoursewareId]);

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
            {questions.length} 道题 · 作答并提交后获得判分、反馈和最新掌握度
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
                courseId={courseId}
                onQuote={handleQuote}
                onSelect={(qObj) => onSelectQuestion?.(qObj)}
                onProgressChange={onProgressChange}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
