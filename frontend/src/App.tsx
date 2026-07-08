import { useState, useCallback } from "react";
import DirectoryTree from "./components/DirectoryTree";
import ChatPanel from "./components/ChatPanel";
import PracticePanel from "./components/PracticePanel";
import DetailPanel from "./components/DetailPanel";
import client from "./api/client";
import type { Courseware, KnowledgePoint, Homework, GeneratedQuestion } from "./types";

type TopTab = "chat" | "practice";

/* ── 顶部导航栏 ───────────────────────────────── */
function TopNavbar({
  activeTab,
  onTabChange,
}: {
  activeTab: TopTab;
  onTabChange: (tab: TopTab) => void;
}) {
  return (
    <header className="flex h-14 shrink-0 items-center border-b border-gray-200 bg-white px-6">
      <h1 className="mr-8 text-xl font-bold text-gray-800">期末复习助手</h1>
      <nav className="flex items-center gap-1" role="tablist" aria-label="主功能切换">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "chat"}
          onClick={() => onTabChange("chat")}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "chat"
              ? "bg-blue-50 text-blue-600"
              : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          }`}
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          对话
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "practice"}
          onClick={() => onTabChange("practice")}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "practice"
              ? "bg-blue-50 text-blue-600"
              : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          }`}
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-3-3v6m-8 4h16a1 1 0 001-1V7a1 1 0 00-1-1H5a1 1 0 00-1 1v11a1 1 0 001 1z" />
          </svg>
          练习
        </button>
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <span className="text-sm text-gray-500">用户</span>
        <div className="h-8 w-8 rounded-full bg-gray-300" />
      </div>
    </header>
  );
}

/* ── 根布局 ───────────────────────────────────── */
export default function App() {
  // ── 顶部 Tab ──────────────────────────────────────
  const [activeTopTab, setActiveTopTab] = useState<TopTab>("chat");

  // ── 面板收起状态 ───────────────────────────────
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  // ── 当前选中的课件 ─────────────────────────────
  const [selectedCoursewareId, setSelectedCoursewareId] = useState<string | null>(null);
  const [selectedCoursewareTitle, setSelectedCoursewareTitle] = useState<string | null>(null);

  // ── 详情面板状态 ───────────────────────────────
  const [selectedKp, setSelectedKp] = useState<KnowledgePoint | null>(null);
  const [selectedHomework, setSelectedHomework] = useState<Homework | null>(null);
  const [selectedQuestion, setSelectedQuestion] = useState<GeneratedQuestion | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // ── 进度刷新键 ─────────────────────────────────
  const [progressRefreshKey, setProgressRefreshKey] = useState(0);

  const handleProgressChange = useCallback(() => {
    try {
      setProgressRefreshKey((prev) => prev + 1);
    } catch (err) {
      console.error("进度刷新失败:", err);
    }
  }, []);

  // ── 引用到聊天 ─────────────────────────────────
  const [quoteText, setQuoteText] = useState("");
  const [quoteKey, setQuoteKey] = useState(0);

  // ── 判断节点类型 ─────────────────────────────
  function isKp(node: Courseware | Homework | KnowledgePoint): node is KnowledgePoint {
    return "courseware_id" in node && "order_index" in node;
  }
  function isHomework(node: Courseware | Homework | KnowledgePoint): node is Homework {
    return "file_type" in node && !("page_count" in node);
  }

  // ── 处理目录树选中 ─────────────────────────────
  const handleTreeSelect = useCallback(
    async (node: Courseware | Homework | KnowledgePoint) => {
      if (isKp(node)) {
        setDetailLoading(true);
        setDetailError(null);
        setSelectedHomework(null);
        setSelectedQuestion(null);
        try {
          const res = await client.get<KnowledgePoint>(`/knowledge-points/${node.id}`);
          setSelectedKp(res.data);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : "加载知识点详情失败";
          setDetailError(message);
          setSelectedKp(null);
        } finally {
          setDetailLoading(false);
        }
      } else if (isHomework(node)) {
        setDetailLoading(true);
        setDetailError(null);
        setSelectedKp(null);
        setSelectedQuestion(null);
        try {
          const res = await client.get<Homework & { solutions: unknown[] }>(
            `/homeworks/${node.id}`
          );
          setSelectedHomework(res.data);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : "加载作业详情失败";
          setDetailError(message);
          setSelectedHomework(null);
        } finally {
          setDetailLoading(false);
        }
      } else {
        const cw = node as Courseware;
        setSelectedCoursewareId(cw.id);
        setSelectedCoursewareTitle(cw.title);
        setSelectedKp(null);
        setSelectedHomework(null);
        setSelectedQuestion(null);
        setDetailError(null);
      }
    },
    [],
  );

  // ── 选中练习题目 → 右栏显示 ───────────────────
  const handleSelectQuestion = useCallback((question: GeneratedQuestion) => {
    setSelectedQuestion(question);
    setSelectedKp(null);
    setSelectedHomework(null);
    setDetailError(null);
  }, []);

  // ── 引用到聊天（切换 Tab） ─────────────────────
  const handleQuoteToChat = useCallback((text: string) => {
    setQuoteText(text);
    setQuoteKey((prev) => prev + 1);
    setActiveTopTab("chat");
  }, []);

  // ── 详情面板重试 ───────────────────────────────
  const handleDetailRetry = useCallback(() => {
    if (selectedKp) handleTreeSelect(selectedKp);
    else if (selectedHomework) handleTreeSelect(selectedHomework);
  }, [selectedKp, selectedHomework, handleTreeSelect]);

  return (
    <div className="flex h-screen flex-col">
      {/* 顶部导航栏（含 Tab 切换） */}
      <TopNavbar activeTab={activeTopTab} onTabChange={setActiveTopTab} />

      {/* 三栏内容区 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧 — 课件目录树 */}
        <DirectoryTree
          onSelect={handleTreeSelect}
          collapsed={leftCollapsed}
          onToggleCollapse={() => setLeftCollapsed((v) => !v)}
          progressRefreshKey={progressRefreshKey}
        />

        {/* 中间 — 根据顶部 Tab 切换 */}
        <main className="flex flex-1 flex-col overflow-hidden bg-white">
          {activeTopTab === "chat" ? (
            <ChatPanel
              quoteText={quoteText}
              quoteKey={quoteKey}
              coursewareId={selectedCoursewareId}
              coursewareTitle={selectedCoursewareTitle}
            />
          ) : (
            <PracticePanel
              selectedCoursewareId={selectedCoursewareId}
              onQuoteToChat={handleQuoteToChat}
              onSelectQuestion={handleSelectQuestion}
            />
          )}
        </main>

        {/* 右侧 — 详情面板 */}
        <DetailPanel
          knowledgePoint={selectedKp}
          homework={selectedHomework}
          selectedQuestion={selectedQuestion}
          loading={detailLoading}
          error={detailError}
          collapsed={rightCollapsed}
          onToggleCollapse={() => setRightCollapsed((v) => !v)}
          onQuoteToChat={handleQuoteToChat}
          onRetry={handleDetailRetry}
          onProgressChange={handleProgressChange}
        />
      </div>
    </div>
  );
}
