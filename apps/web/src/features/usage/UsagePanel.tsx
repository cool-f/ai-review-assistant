import { useCallback, useEffect, useState } from "react";

import client from "@/shared/api/client";


interface Budget {
  today_usage: number; daily_budget: number; percentage: number;
  within_budget: boolean; call_count_today: number; warning: string | null;
}

interface UsageRow {
  purpose?: string; provider?: string; total_tokens: number; call_count: number;
  estimated_cost_usd?: number;
}

interface DailyUsageRow {
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  call_count: number;
}

const PURPOSE_LABELS: Record<string, string> = {
  chat: "课程问答", chat_retrieval: "问答检索", courseware_extraction: "课件提取",
  vision_extraction: "视觉识别", embedding: "向量化", knowledge_reindex: "知识点重索引",
  homework_solve: "作业解答", homework_matching: "作业匹配",
  question_generation: "AI 出题", practice_grading: "AI 判题", unspecified: "其他",
};

export default function UsagePanel({ courseId }: { courseId: string }) {
  const [budget, setBudget] = useState<Budget | null>(null);
  const [daily, setDaily] = useState<DailyUsageRow[]>([]);
  const [purposes, setPurposes] = useState<UsageRow[]>([]);
  const [providers, setProviders] = useState<UsageRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [budgetResponse, dailyResponse, purposeResponse, providerResponse] = await Promise.all([
        client.get<Budget>("/admin/token-usage/budget"),
        client.get<{ items: DailyUsageRow[] }>("/admin/token-usage", { params: { days: 7, course_id: courseId } }),
        client.get<{ items: UsageRow[] }>("/admin/token-usage/by-purpose", { params: { days: 7, course_id: courseId } }),
        client.get<{ items: UsageRow[] }>("/admin/token-usage/by-provider", { params: { days: 7, course_id: courseId } }),
      ]);
      setBudget(budgetResponse.data);
      setDaily(dailyResponse.data.items);
      setPurposes(purposeResponse.data.items);
      setProviders(providerResponse.data.items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "用量加载失败");
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="flex h-full items-center justify-center text-sm text-gray-400">加载用量…</div>;
  if (error) return <div className="flex h-full flex-col items-center justify-center gap-3"><p className="text-sm text-red-600">{error}</p><button onClick={() => void load()} className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white">重试</button></div>;

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex items-center justify-between">
          <div><h2 className="text-lg font-semibold text-gray-800">AI 用量与预算</h2><p className="text-sm text-gray-500">当前课程近 7 天用量；预算为本机全局每日上限。</p></div>
          <button onClick={() => void load()} className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600">刷新</button>
        </div>
        {budget && (
          <section className="rounded-lg border border-gray-200 bg-white p-5">
            <div className="flex justify-between text-sm"><span>今日预算</span><span>{budget.today_usage.toLocaleString()} / {budget.daily_budget.toLocaleString()} tokens</span></div>
            <div className="mt-3 h-3 overflow-hidden rounded-full bg-gray-200"><div className={`h-full ${budget.within_budget ? "bg-blue-500" : "bg-red-500"}`} style={{ width: `${Math.min(100, budget.percentage)}%` }} /></div>
            <p className={`mt-2 text-xs ${budget.within_budget ? "text-gray-500" : "text-red-600"}`}>{budget.warning ?? `今日 ${budget.call_count_today} 次调用，已使用 ${budget.percentage}%`}</p>
          </section>
        )}
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 font-medium text-gray-800">每日用量</h3>
          {daily.length === 0 ? <p className="text-sm text-gray-400">暂无调用记录</p> : (
            <div className="divide-y divide-gray-100">
              {daily.map((row) => (
                <div key={row.date} className="grid grid-cols-3 py-2 text-sm">
                  <span>{row.date}</span>
                  <span className="text-right text-gray-600">{row.total_tokens.toLocaleString()} tokens</span>
                  <span className="text-right text-gray-400">{row.call_count} 次</span>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 font-medium text-gray-800">按业务用途</h3>
          {purposes.length === 0 ? <p className="text-sm text-gray-400">暂无调用记录</p> : <div className="divide-y divide-gray-100">{purposes.map((row) => <div key={row.purpose} className="grid grid-cols-3 py-2 text-sm"><span>{PURPOSE_LABELS[row.purpose ?? ""] ?? row.purpose}</span><span className="text-right text-gray-600">{row.total_tokens.toLocaleString()} tokens</span><span className="text-right text-gray-400">{row.call_count} 次</span></div>)}</div>}
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 font-medium text-gray-800">按提供商</h3>
          {providers.length === 0 ? <p className="text-sm text-gray-400">暂无调用记录</p> : <div className="divide-y divide-gray-100">{providers.map((row) => <div key={row.provider} className="grid grid-cols-3 py-2 text-sm"><span>{row.provider}</span><span className="text-right text-gray-600">{row.total_tokens.toLocaleString()} tokens</span><span className="text-right text-gray-400">{row.call_count} 次</span></div>)}</div>}
        </section>
      </div>
    </div>
  );
}
