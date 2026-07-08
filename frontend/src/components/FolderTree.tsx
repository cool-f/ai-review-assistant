import { useCallback, useEffect, useMemo, useState } from "react";
import client from "../api/client";
import type { Folder, Courseware, Homework, KnowledgePoint, PaginatedResponse, StudyProgress, CoursewareProgressSummary } from "../types";
import ConfirmModal from "./ConfirmModal";

/* ── 内部类型 ───────────────────────────────── */

type Category = "courseware" | "homework";
type ItemNode = Courseware | Homework;

interface FolderNode {
  id: string;
  label: string;
  type: "folder";
  data: Folder;
  children: TreeNode[];
}

interface ItemTreeNode {
  id: string;
  label: string;
  type: "courseware" | "homework";
  data: ItemNode;
}

interface KpTreeNode {
  id: string;
  label: string;
  type: "knowledge_point";
  data: KnowledgePoint;
}

type TreeNode = FolderNode | ItemTreeNode | KpTreeNode;

type SelectableNode = Courseware | Homework | KnowledgePoint;

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; folders: FolderNode[]; rootItems: ItemTreeNode[] };

export interface FolderTreeProps {
  category: Category;
  onSelect?: (node: SelectableNode) => void;
  /** 进度刷新键（DetailPanel 修改进度后递增） */
  progressRefreshKey?: number;
}

/* ── 状态徽标 ─────────────────────────────── */

function StatusBadge({ status }: { status: string }) {
  const base =
    "ml-1.5 inline-block shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium leading-snug";
  switch (status) {
    case "processing":
      return <span className={`${base} bg-yellow-100 text-yellow-700`}>处理中</span>;
    case "completed":
      return <span className={`${base} bg-green-100 text-green-700`}>已完成</span>;
    case "failed":
      return <span className={`${base} bg-red-100 text-red-700`}>失败</span>;
    default:
      return <span className={`${base} bg-gray-100 text-gray-500`}>{status}</span>;
  }
}

/* ── Spinner ──────────────────────────────── */

function MiniSpinner() {
  return (
    <svg
      className="h-3 w-3 animate-spin"
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
  );
}

/* ── FolderTree 组件 ─────────────────────── */

export default function FolderTree({ category, onSelect, progressRefreshKey = 0 }: FolderTreeProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [folderChildren, setFolderChildren] = useState<Map<string, ItemTreeNode[]>>(
    new Map()
  );
  const [loadingFolder, setLoadingFolder] = useState<Set<string>>(new Set());

  // 课件展开/知识点状态
  const [expandedCoursewares, setExpandedCoursewares] = useState<Set<string>>(new Set());
  const [coursewareChildren, setCoursewareChildren] = useState<Map<string, KpTreeNode[]>>(new Map());
  const [loadingCourseware, setLoadingCourseware] = useState<Set<string>>(new Set());

  // 进度追踪状态
  const [progressMap, setProgressMap] = useState<Map<string, StudyProgress>>(new Map());
  const [cwProgress, setCwProgress] = useState<Map<string, { mastered: number; total: number }>>(new Map());

  // 文件夹操作状态
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [renamingFolderId, setRenamingFolderId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // 确认对话框
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmConfig, setConfirmConfig] = useState<{
    title: string;
    message: string;
    confirmLabel?: string;
    onConfirm: () => void;
    danger?: boolean;
  }>({ title: "", message: "", onConfirm: () => {} });

  // ── 加载数据 ───────────────────────────
  const loadData = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      // 并行加载文件夹列表和根目录条目
      const [folderRes, itemRes] = await Promise.all([
        client.get<{ items: Folder[]; total: number }>("/folders/", {
          params: { category },
        }),
        client.get<PaginatedResponse<ItemNode>>(
          category === "courseware" ? "/coursewares/" : "/homeworks/",
          { params: { folder_id: "null", size: 100 } },
        ),
      ]);

      const folders: FolderNode[] = folderRes.data.items.map((f) => ({
        id: f.id,
        label: f.name,
        type: "folder" as const,
        data: f,
        children: [],
      }));

      const rootItems: ItemTreeNode[] = (itemRes.data.items ?? []).map(
        (item: ItemNode) => ({
          id: item.id,
          label: item.title,
          type: category,
          data: item,
        }),
      );

      setState({ kind: "ready", folders, rootItems });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "加载失败";
      setState({ kind: "error", message });
    }
  }, [category]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // ── 当进度刷新键变化时（DetailPanel 修改后），并行重新获取已展开课件的进度 ──
  useEffect(() => {
    if (progressRefreshKey === 0) return; // 首次挂载不触发
    const expandedIds = Array.from(expandedCoursewares);
    if (expandedIds.length === 0) return;

    // 静默处理单个失败（allSettled），但只对成功的响应做批量 setState
    Promise.allSettled(
      expandedIds.map((cwId) =>
        client.get<CoursewareProgressSummary>(`/coursewares/${cwId}/progress`),
      ),
    ).then((results) => {
      // 累积变更：先扫描一遍找出成功的响应
      const newCwProgress = new Map<string, { mastered: number; total: number }>();
      const newProgressEntries: Array<[string, StudyProgress]> = [];

      for (const r of results) {
        if (r.status !== "fulfilled") continue;
        const data = r.value.data;
        newCwProgress.set(
          expandedIds[results.indexOf(r)]!,
          { mastered: data.mastered_count, total: data.total_count },
        );
        for (const item of data.items) {
          newProgressEntries.push([item.knowledge_point_id, item]);
        }
      }

      if (newCwProgress.size === 0 && newProgressEntries.length === 0) return;

      // 一次性批量更新两个 Map
      setCwProgress((prev) => {
        const next = new Map(prev);
        for (const [k, v] of newCwProgress) next.set(k, v);
        return next;
      });
      setProgressMap((prev) => {
        const next = new Map(prev);
        for (const [k, v] of newProgressEntries) next.set(k, v);
        return next;
      });
    });
  }, [progressRefreshKey, expandedCoursewares]);

  // ── 展开/折叠文件夹 ─────────────────────
  const toggleFolder = useCallback(
    async (folderId: string) => {
      setExpandedFolders((prev) => {
        const next = new Set(prev);
        if (next.has(folderId)) {
          next.delete(folderId);
        } else {
          next.add(folderId);
        }
        return next;
      });

      // 首次展开时加载文件夹内的条目
      if (!folderChildren.has(folderId) && !expandedFolders.has(folderId)) {
        setLoadingFolder((prev) => new Set(prev).add(folderId));
        try {
          const res = await client.get<PaginatedResponse<ItemNode>>(
            category === "courseware" ? "/coursewares/" : "/homeworks/",
            { params: { folder_id: folderId, size: 100 } },
          );
          const items: ItemTreeNode[] = (res.data.items ?? []).map(
            (item: ItemNode) => ({
              id: item.id,
              label: item.title,
              type: category,
              data: item,
            }),
          );
          setFolderChildren((prev) => new Map(prev).set(folderId, items));
        } catch {
          // silently fail
        } finally {
          setLoadingFolder((prev) => {
            const next = new Set(prev);
            next.delete(folderId);
            return next;
          });
        }
      }
    },
    [category, expandedFolders, folderChildren],
  );

  // ── 展开/折叠课件（加载知识点） ──────────
  const toggleCourseware = useCallback(
    async (coursewareId: string) => {
      setExpandedCoursewares((prev) => {
        const next = new Set(prev);
        if (next.has(coursewareId)) {
          next.delete(coursewareId);
        } else {
          next.add(coursewareId);
        }
        return next;
      });

      // 首次展开时加载知识点 + 进度
      if (!coursewareChildren.has(coursewareId) && !expandedCoursewares.has(coursewareId)) {
        setLoadingCourseware((prev) => new Set(prev).add(coursewareId));
        try {
          const [kpRes, progressRes] = await Promise.all([
            client.get<PaginatedResponse<KnowledgePoint>>(
              `/coursewares/${coursewareId}/knowledge-points/`,
              { params: { size: 100 } },
            ),
            client.get<CoursewareProgressSummary>(
              `/coursewares/${coursewareId}/progress`,
            ),
          ]);

          const kps: KpTreeNode[] = (kpRes.data.items ?? []).map((kp) => ({
            id: kp.id,
            label: kp.title,
            type: "knowledge_point" as const,
            data: kp,
          }));

          const progData = progressRes.data;

          // 一次性 batched setState（避免渲染抖动）
          setCoursewareChildren((prev) => new Map(prev).set(coursewareId, kps));
          setCwProgress((prev) => {
            const next = new Map(prev);
            next.set(coursewareId, {
              mastered: progData.mastered_count,
              total: progData.total_count,
            });
            return next;
          });
          setProgressMap((prev) => {
            const next = new Map(prev);
            for (const item of progData.items) {
              next.set(item.knowledge_point_id, item);
            }
            return next;
          });
        } catch {
          // silently fail
        } finally {
          setLoadingCourseware((prev) => {
            const next = new Set(prev);
            next.delete(coursewareId);
            return next;
          });
        }
      }
    },
    [expandedCoursewares, coursewareChildren],
  );

  // ── 文件夹 CRUD ─────────────────────────
  const handleCreateFolder = useCallback(async () => {
    const name = newFolderName.trim();
    if (!name) return;

    try {
      await client.post("/folders/", { name, category });
      setNewFolderName("");
      setCreatingFolder(false);
      await loadData();
    } catch {
      // error handled by parent
    }
  }, [newFolderName, category, loadData]);

  const handleRenameFolder = useCallback(
    async (folderId: string) => {
      const name = renameValue.trim();
      if (!name) {
        setRenamingFolderId(null);
        return;
      }
      try {
        await client.patch(`/folders/${folderId}`, { name });
        setRenamingFolderId(null);
        await loadData();
      } catch {
        // error handled silently
      }
    },
    [renameValue, loadData],
  );

  const handleDeleteFolder = useCallback(
    (folder: Folder) => {
      setConfirmConfig({
        title: "删除文件夹",
        message: `确定要删除「${folder.name}」吗？文件夹内的课件/作业将移至根目录。`,
        confirmLabel: "删除",
        danger: true,
        onConfirm: async () => {
          try {
            await client.delete(`/folders/${folder.id}`);
            setConfirmOpen(false);
            await loadData();
          } catch {
            // error handled silently
          }
        },
      });
      setConfirmOpen(true);
    },
    [loadData],
  );

  // ── 删除条目 ────────────────────────────
  const handleDeleteItem = useCallback(
    (item: ItemTreeNode) => {
      const label = category === "courseware" ? "课件" : "作业";
      setConfirmConfig({
        title: `删除${label}`,
        message: `确定要删除「${item.label}」吗？此操作不可撤销，关联数据将被级联删除。`,
        confirmLabel: "删除",
        danger: true,
        onConfirm: async () => {
          try {
            await client.delete(
              category === "courseware"
                ? `/coursewares/${item.id}`
                : `/homeworks/${item.id}`,
            );
            setConfirmOpen(false);
            await loadData();
          } catch {
            // error handled silently
          }
        },
      });
      setConfirmOpen(true);
    },
    [category, loadData],
  );

  // ── 渲染文件夹节点 ──────────────────────
  const renderFolderNode = useCallback(
    (folder: FolderNode) => {
      const isExpanded = expandedFolders.has(folder.id);
      const isLoading = loadingFolder.has(folder.id);
      const children = folderChildren.get(folder.id) ?? [];
      const isRenaming = renamingFolderId === folder.id;

      return (
        <li key={folder.id}>
          {/* 文件夹行 */}
          <div
            role="button"
            tabIndex={0}
            onClick={() => toggleFolder(folder.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") toggleFolder(folder.id);
            }}
            className="group flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-100"
          >
            {/* 展开箭头 */}
            <span className="flex w-4 shrink-0 items-center justify-center">
              <svg
                className={`h-3 w-3 text-gray-400 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                fill="currentColor"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path d="M6 4l8 6-8 6V4z" />
              </svg>
            </span>

            {/* 文件夹图标 */}
            <svg
              className="h-4 w-4 shrink-0 text-yellow-500"
              fill="currentColor"
              viewBox="0 0 20 20"
              aria-hidden="true"
            >
              <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
            </svg>

            {/* 名称 */}
            {isRenaming ? (
              <input
                type="text"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={() => handleRenameFolder(folder.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleRenameFolder(folder.id);
                  if (e.key === "Escape") setRenamingFolderId(null);
                }}
                className="min-w-0 flex-1 rounded border border-blue-300 px-1 py-0.5 text-sm outline-none focus:ring-1 focus:ring-blue-400"
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="min-w-0 flex-1 truncate">{folder.label}</span>
            )}

            {/* 文件夹操作按钮 (hover 显示) */}
            <div className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setRenamingFolderId(folder.id);
                  setRenameValue(folder.label);
                }}
                className="rounded p-0.5 text-gray-400 hover:text-blue-500"
                title="重命名"
                aria-label="重命名文件夹"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteFolder(folder.data);
                }}
                className="rounded p-0.5 text-gray-400 hover:text-red-500"
                title="删除"
                aria-label="删除文件夹"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          </div>

          {/* 子节点 */}
          {isExpanded && (
            <ul className="list-none">
              {isLoading ? (
                <li className="flex items-center gap-1.5 py-1.5 pl-10 text-xs text-gray-400">
                  <MiniSpinner /> 加载中...
                </li>
              ) : children.length > 0 ? (
                children.map((child) => renderItemNode(child, 1))
              ) : (
                <li className="py-1.5 pl-10 text-xs text-gray-400">空文件夹</li>
              )}
            </ul>
          )}
        </li>
      );
    },
    [
      expandedFolders,
      loadingFolder,
      folderChildren,
      renamingFolderId,
      renameValue,
      toggleFolder,
      handleRenameFolder,
      handleDeleteFolder,
    ],
  );

  // ── 渲染条目节点 ────────────────────────
  // ── 状态图标映射 ──────────────────────
  const statusIcon = useCallback((status: string): string => {
    switch (status) {
      case "mastered": return "\u{1F7E2}";   // 🟢
      case "in_progress": return "\u{1F7E1}"; // 🟡
      case "struggling": return "\u{1F534}";  // 🔴
      default: return "⚪";               // ⚪ not_started
    }
  }, []);

  const statusLabel = useCallback((status: string): string => {
    switch (status) {
      case "mastered": return "已掌握";
      case "in_progress": return "学习中";
      case "struggling": return "需加强";
      default: return "未开始";
    }
  }, []);

  // ── 渲染知识点节点 ──────────────────────
  const renderKpNode = useCallback(
    (kp: KpTreeNode, depth: number) => {
      const progress = progressMap.get(kp.id);
      const status = progress?.status ?? "not_started";

      return (
        <li key={kp.id}>
          <div
            role="button"
            tabIndex={0}
            onClick={() => onSelect?.(kp.data)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onSelect?.(kp.data);
            }}
            className="flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-2 text-sm text-gray-600 transition-colors hover:bg-blue-50"
            style={{ paddingLeft: `${12 + depth * 16}px` }}
            title={`${kp.label} — ${statusLabel(status)}`}
          >
            {/* 状态图标 */}
            <span
              className="shrink-0 text-xs leading-none"
              title={statusLabel(status)}
              aria-label={statusLabel(status)}
            >
              {statusIcon(status)}
            </span>
            <svg className="h-3 w-3 shrink-0 text-gray-400" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3 3 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2z" clipRule="evenodd" />
            </svg>
            <span className="min-w-0 flex-1 truncate">{kp.label}</span>
          </div>
        </li>
      );
    },
    [onSelect, progressMap, statusIcon, statusLabel],
  );

  // ── 渲染条目节点（课件可展开） ──────────
  const renderItemNode = useCallback(
    (item: ItemTreeNode, depth: number = 0) => {
      const isCourseware = item.type === "courseware";
      const isExpanded = isCourseware && expandedCoursewares.has(item.id);
      const isLoadingKps = isCourseware && loadingCourseware.has(item.id);
      const kpChildren = isCourseware ? (coursewareChildren.get(item.id) ?? []) : [];

      return (
        <li key={item.id}>
          <div
            role="button"
            tabIndex={0}
            onClick={() => {
              if (isCourseware) {
                toggleCourseware(item.id);
              }
              onSelect?.(item.data);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                if (isCourseware) toggleCourseware(item.id);
                onSelect?.(item.data);
              }
            }}
            className="group flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-100"
            style={{ paddingLeft: `${12 + depth * 16}px` }}
            title={item.label}
          >
            {/* 展开箭头（课件）或叶子图标 */}
            <span className="flex w-4 shrink-0 items-center justify-center">
              {isCourseware ? (
                <svg
                  className={`h-3 w-3 text-gray-400 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  fill="currentColor"
                  viewBox="0 0 20 20"
                  aria-hidden="true"
                >
                  <path d="M6 4l8 6-8 6V4z" />
                </svg>
              ) : (
                <svg
                  className="h-4 w-4 shrink-0 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                </svg>
              )}
            </span>

            {/* 名称 */}
            <span className="min-w-0 flex-1 truncate">{item.label}</span>

            {/* 掌握进度（课件） */}
            {isCourseware && cwProgress.has(item.id) && (
              <span className="shrink-0 text-[10px] text-gray-400">
                {cwProgress.get(item.id)!.mastered}/{cwProgress.get(item.id)!.total} 已掌握
              </span>
            )}

            {/* 状态徽标 */}
            <StatusBadge status={(item.data as { status: string }).status} />

            {/* 加载知识点指示器 */}
            {isLoadingKps && <MiniSpinner />}

            {/* 删除按钮 (hover 显示) */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteItem(item);
              }}
              className="hidden shrink-0 rounded p-0.5 text-gray-400 hover:text-red-500 group-hover:flex"
              title={isCourseware ? "删除课件" : "删除作业"}
              aria-label={isCourseware ? "删除课件" : "删除作业"}
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>

          {/* 知识点子节点（课件展开后） */}
          {isCourseware && isExpanded && (
            <ul className="list-none">
              {isLoadingKps ? (
                <li className="flex items-center gap-1.5 py-1.5 text-xs text-gray-400" style={{ paddingLeft: `${12 + (depth + 1) * 16}px` }}>
                  <MiniSpinner /> 加载知识点...
                </li>
              ) : kpChildren.length > 0 ? (
                kpChildren.map((kp) => renderKpNode(kp, depth + 1))
              ) : (
                <li className="py-1.5 text-xs text-gray-400" style={{ paddingLeft: `${12 + (depth + 1) * 16}px` }}>
                  暂无知识点
                </li>
              )}
            </ul>
          )}
        </li>
      );
    },
    [onSelect, handleDeleteItem, expandedCoursewares, loadingCourseware, coursewareChildren, toggleCourseware, renderKpNode, cwProgress],
  );

  // ── 主渲染 ───────────────────────────
  const content = useMemo(() => {
    switch (state.kind) {
      case "loading":
        return (
          <div className="flex flex-col items-center gap-2 py-8">
            <MiniSpinner />
            <span className="text-xs text-gray-400">加载中…</span>
          </div>
        );

      case "error":
        return (
          <div className="flex flex-col items-center gap-3 px-4 py-8">
            <p className="text-center text-sm text-red-600">{state.message}</p>
            <button
              onClick={loadData}
              className="rounded-md bg-blue-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600"
            >
              重试
            </button>
          </div>
        );

      case "ready": {
        const hasFolders = state.folders.length > 0;
        const hasItems = state.rootItems.length > 0;

        if (!hasFolders && !hasItems) {
          return (
            <div className="flex flex-col items-center gap-2 px-4 py-8">
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
                  d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                />
              </svg>
              <p className="text-sm text-gray-500">
                {category === "courseware" ? "暂无课件" : "暂无作业"}
              </p>
            </div>
          );
        }

        return (
          <ul className="list-none space-y-0.5 px-1 py-1">
            {/* 文件夹 */}
            {hasFolders &&
              state.folders.map((folder) => renderFolderNode(folder))}

            {/* 根目录条目 */}
            {hasItems &&
              state.rootItems.map((item) => renderItemNode(item, 0))}
          </ul>
        );
      }
    }
  }, [
    state,
    category,
    renderFolderNode,
    renderItemNode,
    loadData,
  ]);

  // ── 新建文件夹输入行 ────────────────────
  const createFolderUI = creatingFolder ? (
    <div className="flex items-center gap-1.5 px-3 py-1.5">
      <input
        type="text"
        value={newFolderName}
        onChange={(e) => setNewFolderName(e.target.value)}
        onBlur={() => {
          if (!newFolderName.trim()) setCreatingFolder(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") handleCreateFolder();
          if (e.key === "Escape") {
            setNewFolderName("");
            setCreatingFolder(false);
          }
        }}
        placeholder="文件夹名称"
        className="min-w-0 flex-1 rounded border border-blue-300 px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-blue-400"
        autoFocus
      />
      <button
        type="button"
        onClick={handleCreateFolder}
        disabled={!newFolderName.trim()}
        className="rounded bg-blue-500 px-2 py-1 text-xs text-white hover:bg-blue-600 disabled:opacity-50"
      >
        确定
      </button>
      <button
        type="button"
        onClick={() => {
          setNewFolderName("");
          setCreatingFolder(false);
        }}
        className="rounded px-2 py-1 text-xs text-gray-500 hover:text-gray-700"
      >
        取消
      </button>
    </div>
  ) : (
    <button
      type="button"
      onClick={() => setCreatingFolder(true)}
      className="flex w-full items-center gap-1.5 px-3 py-2 text-xs text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
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
          d="M12 4v16m8-8H4"
        />
      </svg>
      新建文件夹
    </button>
  );

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* 文件夹操作区 */}
      <div className="shrink-0 border-b border-gray-100">{createFolderUI}</div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto">{content}</div>

      {/* 确认对话框 */}
      <ConfirmModal
        open={confirmOpen}
        title={confirmConfig.title}
        message={confirmConfig.message}
        confirmLabel={confirmConfig.confirmLabel ?? "确认"}
        danger={confirmConfig.danger}
        onConfirm={confirmConfig.onConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
