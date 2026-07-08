import { useCallback, useEffect, useRef, useState } from "react";
import client from "../api/client";
import type { Courseware, Homework, KnowledgePoint, OverallProgress } from "../types";
import FolderTree from "./FolderTree";
import ConfirmModal from "./ConfirmModal";

/** 支持上传的文件格式 */
const ACCEPTED_TYPES = ".pdf,.pptx,.docx,.doc,.txt,.md";

type PanelTab = "courseware" | "homework";

export type SelectableNode = Courseware | Homework | KnowledgePoint;

export interface DirectoryTreeProps {
  /** 选中节点回调 */
  onSelect?: (node: SelectableNode) => void;
  /** 是否收起 */
  collapsed?: boolean;
  /** 切换收起/展开 */
  onToggleCollapse?: () => void;
  /** 进度刷新键（DetailPanel 修改进度后递增） */
  progressRefreshKey?: number;
}

export default function DirectoryTree({
  onSelect,
  collapsed = false,
  onToggleCollapse,
  progressRefreshKey = 0,
}: DirectoryTreeProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>("courseware");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [, setRefreshKey] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Token 预估弹窗状态 ──────────────────────
  interface PreflightResult {
    filename: string;
    readable?: boolean;
    suggested_mode?: string;
    vision_unavailable?: boolean;
    vision_error?: string;
    page_count?: number;
    estimated_total_tokens?: number;
    estimated_knowledge_points: number;
    estimated_cost: {
      extraction: number;
      embedding: number;
      vision?: { per_page_extraction: number; merge_step: number; total_vision: number };
      total: number;
      currency: string;
      note: string;
    };
    provider: string;
    model: string;
  }
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [preflighting, setPreflighting] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [preflightVisionMode, setPreflightVisionMode] = useState(false);

  // ── 上传 ───────────────────────────────────
  const handleUploadClick = useCallback(() => {
    setUploadError(null);
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setUploadError(null);
      setPreflightError(null);
      setPreflighting(true);

      try {
        // ── 第一步：调用 preflight 获取预估 ──
        const formData = new FormData();
        formData.append("file", file);

        const pfEndpoint =
          activeTab === "courseware"
            ? "/coursewares/preflight"
            : "/homeworks/preflight";

        const pfResult = await client.post<PreflightResult>(pfEndpoint, formData, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 30_000,
        });

        setPreflight(pfResult.data);
        setPendingFile(file);
        setPreflightVisionMode(pfResult.data.suggested_mode === "vision");

        // 提供商不支持 Vision 时直接显示错误，不弹出确认弹窗
        if (pfResult.data.vision_unavailable) {
          setPreflight(null);
          setPendingFile(null);
          setUploadError(pfResult.data.vision_error || "当前 AI 提供商不支持图片识别");
        }

        // 文本完全不可读（非 Vision 场景），直接显示错误
        if (pfResult.data.readable === false && !pfResult.data.suggested_mode) {
          setPreflight(null);
          setPendingFile(null);
          setUploadError(pfResult.data.estimated_cost?.note || "无法从文件中提取到文本内容");
        }
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "预估失败，请重试";
        setPreflightError(message);
        // 重置文件 input
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      } finally {
        setPreflighting(false);
      }
    },
    [activeTab],
  );

  // ── 用户确认后执行实际上传 ──────────────────
  const handleConfirmUpload = useCallback(async () => {
    if (!pendingFile) return;

    setPreflight(null);
    setPendingFile(null);
    setUploading(true);
    setUploadError(null);
    setPreflightVisionMode(false);

    const endpoint =
      activeTab === "courseware" ? "/coursewares/upload" : "/homeworks/upload";

    try {
      const formData = new FormData();
      formData.append("file", pendingFile);
      if (preflightVisionMode) {
        formData.append("use_vision", "true");
      }

      await client.post(endpoint, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60_000,
      });

      setRefreshKey((prev) => prev + 1);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "上传失败，请重试";
      setUploadError(message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }, [pendingFile, activeTab]);

  // ── 用户取消预估弹窗 ──────────────────────────
  const handleCancelPreflight = useCallback(() => {
    setPreflight(null);
    setPendingFile(null);
    setPreflightError(null);
    setPreflightVisionMode(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  // ── 收起状态 ──────────────────────────────
  if (collapsed) {
    return (
      <aside className="flex w-[36px] shrink-0 flex-col items-center border-r border-gray-200 bg-gray-50 py-3">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="mb-3 rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
          title="展开课件目录"
          aria-label="展开课件目录"
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
        <span
          className="select-none text-xs font-medium text-gray-400"
          style={{ writingMode: "vertical-rl" }}
        >
          课件目录
        </span>
      </aside>
    );
  }

  // ── 正常状态 ──────────────────────────────
  return (
    <aside className="flex w-[250px] shrink-0 flex-col border-r border-gray-200 bg-gray-50 transition-[width] duration-200">
      {/* 隐藏文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        className="hidden"
        aria-label={activeTab === "courseware" ? "上传课件文件" : "上传作业文件"}
        onChange={(e) => {
          void handleFileChange(e);
        }}
      />

      {/* 标题栏 + 课件/作业切换 */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 px-4">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("courseware")}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              activeTab === "courseware"
                ? "bg-blue-100 text-blue-700"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
            aria-label="显示课件目录"
          >
            🎓 课件
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("homework")}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              activeTab === "homework"
                ? "bg-blue-100 text-blue-700"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
            aria-label="显示作业目录"
          >
            📝 作业
          </button>
        </div>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-600"
          aria-label="收起课件目录"
          title="收起"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 5l-7 7 7 7" />
          </svg>
        </button>
      </div>

      {/* 文件夹树 */}
      <FolderTree
        category={activeTab}
        onSelect={(node) => onSelect?.(node)}
        progressRefreshKey={progressRefreshKey}
      />

      {/* 全局进度条（仅课件 Tab） */}
      {activeTab === "courseware" && (
        <GlobalProgressBar refreshKey={progressRefreshKey ?? 0} />
      )}

      {/* 上传按钮 */}
      <div className="shrink-0 border-t border-gray-200 p-2">
        <button
          type="button"
          onClick={handleUploadClick}
          disabled={uploading || preflighting}
          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-blue-500 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-60"
        >
          {uploading ? (
            <>
              <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              上传中…
            </>
          ) : preflighting ? (
            <>
              <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              估算中…
            </>
          ) : (
            <>
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              上传{activeTab === "courseware" ? "课件" : "作业"}
            </>
          )}
        </button>

        {uploadError && (
          <p className="mt-1.5 text-center text-xs text-red-500">{uploadError}</p>
        )}

        {/* Token 预估确认弹窗 */}
        <ConfirmModal
          open={preflight !== null}
          title={preflightVisionMode ? "确认使用视觉识别模式" : "确认上传并开始 AI 提取"}
          message={
            preflight
              ? `文件: ${preflight.filename}\n\n` +
                (preflightVisionMode && preflight.estimated_cost.vision
                  ? `📄 页数: ${preflight.page_count} 页\n` +
                    `📚 预估提取知识点: ~${preflight.estimated_knowledge_points} 个\n` +
                    `💰 视觉识别费用: $${preflight.estimated_cost.vision.total_vision}\n` +
                    `   ├ 逐页提取: $${preflight.estimated_cost.vision.per_page_extraction}\n` +
                    `   └ 合并去重: $${preflight.estimated_cost.vision.merge_step}\n` +
                    `💰 嵌入费用: $${preflight.estimated_cost.embedding}\n` +
                    `💰 预估总费用: $${preflight.estimated_cost.total} ${preflight.estimated_cost.currency}\n` +
                    `🔧 提供商: ${preflight.provider} / ${preflight.model}\n\n` +
                    `${preflight.estimated_cost.note}`
                  : `📖 文件可读取（标准文本模式）\n` +
                    `📊 预估 Token 用量: ${(preflight.estimated_total_tokens ?? 0).toLocaleString()}\n` +
                    `📚 预估提取知识点: ~${preflight.estimated_knowledge_points} 个\n` +
                    `💰 预估费用: $${preflight.estimated_cost.total} ${preflight.estimated_cost.currency}\n` +
                    `🔧 提供商: ${preflight.provider} / ${preflight.model}\n\n` +
                    `${preflight.estimated_cost.note}`)
              : ""
          }
          confirmLabel="开始提取"
          cancelLabel="取消"
          onConfirm={handleConfirmUpload}
          onCancel={handleCancelPreflight}
        />

        {/* Preflight 错误提示 */}
        {preflightError && (
          <div className="mt-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-600">
            {preflightError}
            <button
              onClick={() => setPreflightError(null)}
              className="ml-2 text-red-400 hover:text-red-600"
            >
              关闭
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

/* ── GlobalProgressBar 子组件 ──────────────────────── */

function GlobalProgressBar({ refreshKey }: { refreshKey: number }) {
  const [progress, setProgress] = useState<OverallProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchProgress = useCallback(async () => {
    // 取消上一次未完成的请求，防止竞态（Blocker 5 + 建议 AbortController）
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const res = await client.get<OverallProgress>("/progress/overall");
      // 请求可能被取消，检查 signal
      if (controller.signal.aborted) return;
      setProgress(res.data);
    } catch (err: unknown) {
      if (controller.signal.aborted) return;
      const message = err instanceof Error ? err.message : "加载进度失败";
      setError(message);
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchProgress();
    // 组件卸载时取消请求
    return () => {
      abortRef.current?.abort();
    };
  }, [fetchProgress, refreshKey]);

  if (loading) {
    return (
      <div className="shrink-0 border-t border-gray-200 px-3 py-2">
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          加载进度…
        </div>
      </div>
    );
  }

  if (error || !progress) {
    return (
      <div className="shrink-0 border-t border-gray-200 px-3 py-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-red-500">{error || "无法加载进度"}</span>
          <button
            onClick={fetchProgress}
            className="text-blue-500 hover:text-blue-600"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  const { total_knowledge_points, mastered_count } = progress;
  const pct = total_knowledge_points > 0
    ? Math.round((mastered_count / total_knowledge_points) * 100)
    : 0;

  return (
    <div className="shrink-0 border-t border-gray-200 px-3 py-2.5">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-medium text-gray-600">复习进度</span>
        <span className="text-gray-500">
          {mastered_count}/{total_knowledge_points}
          <span className="ml-1 font-medium text-gray-700">{pct}%</span>
        </span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-gray-200"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`复习进度 ${mastered_count}/${total_knowledge_points}（${pct}%）`}
      >
        <div
          className="h-full rounded-full bg-green-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-gray-400">
        <span title="已掌握">{progress.mastered_count} 已掌握</span>
        <span title="学习中">{progress.in_progress_count} 学习中</span>
        <span title="未开始">{progress.not_started_count} 未开始</span>
        <span title="需加强">{progress.struggling_count} 需加强</span>
      </div>
    </div>
  );
}

// PracticeList 已移除 — 移至顶部 Tab「练习」面板
