import { lazy, Suspense, useState, useCallback, useEffect } from "react";
import DirectoryTree from "@/features/library/DirectoryTree";
import client from "@/shared/api/client";
import type { Course, Courseware, KnowledgePoint, Homework, GeneratedQuestion } from "@/shared/types";

const ChatPanel = lazy(() => import("@/features/chat/ChatPanel"));
const PracticePanel = lazy(() => import("@/features/practice/PracticePanel"));
const DetailPanel = lazy(() => import("@/features/study/DetailPanel"));
const UsagePanel = lazy(() => import("@/features/usage/UsagePanel"));

type TopTab = "chat" | "practice" | "usage";

/* ── 顶部导航栏 ───────────────────────────────── */
function TopNavbar({
  activeTab,
  onTabChange,
  courses,
  currentCourseId,
  onCourseChange,
  onCreateCourse,
}: {
  activeTab: TopTab;
  onTabChange: (tab: TopTab) => void;
  courses: Course[];
  currentCourseId: string | null;
  onCourseChange: (courseId: string) => void;
  onCreateCourse: () => void;
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
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "usage"}
          onClick={() => onTabChange("usage")}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${activeTab === "usage" ? "bg-blue-50 text-blue-600" : "text-gray-500 hover:bg-gray-100"}`}
        >
          用量
        </button>
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <label className="sr-only" htmlFor="course-selector">当前课程</label>
        <select
          id="course-selector"
          value={currentCourseId ?? ""}
          onChange={(event) => onCourseChange(event.target.value)}
          disabled={courses.length === 0}
          className="max-w-56 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700"
        >
          {courses.length === 0 ? <option value="">尚未创建课程</option> : null}
          {courses.map((course) => (
            <option key={course.id} value={course.id}>
              {course.name}{course.term ? ` · ${course.term}` : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onCreateCourse}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          新建课程
        </button>
      </div>
    </header>
  );
}

/* ── 根布局 ───────────────────────────────────── */
export default function App() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [currentCourseId, setCurrentCourseId] = useState<string | null>(null);
  const [courseError, setCourseError] = useState<string | null>(null);

  const loadCourses = useCallback(async () => {
    try {
      const response = await client.get<Course[]>("/courses");
      setCourses(response.data);
      setCurrentCourseId((current) =>
        current && response.data.some((course) => course.id === current)
          ? current
          : response.data[0]?.id ?? null,
      );
      setCourseError(null);
    } catch (error) {
      setCourseError(error instanceof Error ? error.message : "课程加载失败");
    }
  }, []);

  useEffect(() => {
    void loadCourses();
  }, [loadCourses]);

  const handleCreateCourse = useCallback(async () => {
    const name = window.prompt("课程名称");
    if (!name?.trim()) return;
    const term = window.prompt("学期（可留空）") ?? "";
    try {
      const response = await client.post<Course>("/courses/", { name: name.trim(), term: term.trim() });
      setCourses((current) => [response.data, ...current]);
      setCurrentCourseId(response.data.id);
      setCourseError(null);
    } catch (error) {
      setCourseError(error instanceof Error ? error.message : "创建课程失败");
    }
  }, []);

  const handleCourseChange = useCallback((courseId: string) => {
    setCurrentCourseId(courseId);
    setSelectedCoursewareId(null);
    setSelectedCoursewareTitle(null);
    setSelectedKp(null);
    setSelectedHomework(null);
    setSelectedQuestion(null);
  }, []);
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
          const res = await client.get<KnowledgePoint>(
            `/knowledge-points/${node.id}`,
            { params: { course_id: currentCourseId } },
          );
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
            `/homeworks/${node.id}`,
            { params: { course_id: currentCourseId } },
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
    [currentCourseId],
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

  const handleHomeworkRefresh = useCallback(async () => {
    if (selectedHomework) {
      await handleTreeSelect(selectedHomework);
    }
  }, [selectedHomework, handleTreeSelect]);

  const handleKnowledgePointOpen = useCallback(async (knowledgePointId: string) => {
    setDetailLoading(true);
    try {
      const response = await client.get<KnowledgePoint>(
        `/knowledge-points/${knowledgePointId}`,
        { params: { course_id: currentCourseId } },
      );
      setSelectedKp(response.data);
      setSelectedHomework(null);
      setSelectedQuestion(null);
    } finally {
      setDetailLoading(false);
    }
  }, [currentCourseId]);

  return (
    <div className="flex h-screen flex-col">
      {/* 顶部导航栏（含 Tab 切换） */}
      <TopNavbar
        activeTab={activeTopTab}
        onTabChange={setActiveTopTab}
        courses={courses}
        currentCourseId={currentCourseId}
        onCourseChange={handleCourseChange}
        onCreateCourse={handleCreateCourse}
      />

      {/* 三栏内容区 */}
      {courseError ? (
        <div className="flex flex-1 items-center justify-center bg-gray-50">
          <div className="text-center">
            <p className="mb-3 text-sm text-red-600">{courseError}</p>
            <button type="button" onClick={() => void loadCourses()} className="rounded bg-blue-600 px-4 py-2 text-sm text-white">重试</button>
          </div>
        </div>
      ) : !currentCourseId ? (
        <div className="flex flex-1 items-center justify-center bg-gray-50">
          <div className="text-center">
            <h2 className="text-lg font-semibold text-gray-800">先创建一门课程</h2>
            <p className="mt-2 text-sm text-gray-500">课件、作业、练习和对话都将归属于课程。</p>
            <button type="button" onClick={handleCreateCourse} className="mt-4 rounded bg-blue-600 px-4 py-2 text-sm text-white">创建课程</button>
          </div>
        </div>
      ) : <div className="flex flex-1 overflow-hidden">
        {/* 左侧 — 课件目录树 */}
        <DirectoryTree
          key={`library-${currentCourseId}`}
          courseId={currentCourseId}
          onSelect={handleTreeSelect}
          collapsed={leftCollapsed}
          onToggleCollapse={() => setLeftCollapsed((v) => !v)}
          progressRefreshKey={progressRefreshKey}
        />

        <Suspense fallback={<div className="flex flex-1 items-center justify-center text-sm text-gray-400">正在加载功能…</div>}>
          {/* 中间 — 根据顶部 Tab 切换 */}
          <main className="flex flex-1 flex-col overflow-hidden bg-white">
          {activeTopTab === "chat" ? (
            <ChatPanel
              key={`chat-${currentCourseId}`}
              courseId={currentCourseId}
              quoteText={quoteText}
              quoteKey={quoteKey}
              coursewareId={selectedCoursewareId}
              coursewareTitle={selectedCoursewareTitle}
            />
          ) : activeTopTab === "practice" ? (
            <PracticePanel
              courseId={currentCourseId}
              selectedCoursewareId={selectedCoursewareId}
              onQuoteToChat={handleQuoteToChat}
              onSelectQuestion={handleSelectQuestion}
              onProgressChange={handleProgressChange}
            />
          ) : <UsagePanel courseId={currentCourseId} />}
          </main>

          {/* 右侧 — 详情面板 */}
          <DetailPanel
          courseId={currentCourseId}
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
          onHomeworkRefresh={handleHomeworkRefresh}
          onKnowledgePointUpdated={setSelectedKp}
          onKnowledgePointOpen={(knowledgePointId) => void handleKnowledgePointOpen(knowledgePointId)}
          />
        </Suspense>
      </div>}
    </div>
  );
}
