import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";

import client from "@/shared/api/client";
import type { HomeworkDetail, KnowledgePoint } from "@/shared/types";
import DetailPanel from "./DetailPanel";

vi.mock("@/shared/api/client", () => ({
  default: {
    defaults: { baseURL: "/api" },
    get: vi.fn(), patch: vi.fn(),
  },
}));

const baseKnowledgePoint: KnowledgePoint = {
  id: "kp-1", courseware_id: "cw-1", title: "矩阵秩", content: "定义内容",
  page_number: 8, order_index: 1, revision: 2, indexing_status: "processing",
  indexing_error: null, examples: [], created_at: "2026-07-16T00:00:00Z",
  updated_at: "2026-07-16T00:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test("polls a knowledge point to indexing terminal state then refreshes links", async () => {
  vi.useFakeTimers();
  const completed = { ...baseKnowledgePoint, indexing_status: "completed" as const };
  const onUpdated = vi.fn();
  vi.mocked(client.get).mockImplementation(async (url) => {
    if (url === "/knowledge-points/kp-1") return { data: completed } as never;
    if (url === "/knowledge-points/kp-1/links") {
      return { data: { links: [{
        id: "link-1", similarity: 0.91,
        linked_kp: { id: "kp-2", title: "线性相关", courseware_id: "cw-2", courseware_title: "习题课" },
      }] } } as never;
    }
    return { data: {
      knowledge_point_id: "kp-1", status: "not_started", manual_status: null,
      quiz_correct_count: 0, quiz_total_count: 0, correct_streak: 0,
      answered_question_count: 0, last_reviewed_at: null, updated_at: "2026-07-16T00:00:00Z",
    } } as never;
  });

  function Harness() {
    const [knowledgePoint, setKnowledgePoint] = useState(baseKnowledgePoint);
    return (
      <DetailPanel
        courseId="course-1" knowledgePoint={knowledgePoint} homework={null}
        selectedQuestion={null} loading={false} error={null}
        onQuoteToChat={vi.fn()}
        onKnowledgePointUpdated={(next) => { onUpdated(next); setKnowledgePoint(next); }}
      />
    );
  }

  render(<Harness />);
  await act(async () => { await vi.advanceTimersByTimeAsync(900); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });

  expect(onUpdated).toHaveBeenCalledWith(completed);
  expect(client.get).toHaveBeenCalledWith(
    "/knowledge-points/kp-1",
    { params: { course_id: "course-1" } },
  );
  expect(client.get).toHaveBeenCalledWith(
    "/knowledge-points/kp-1/links",
    { params: { course_id: "course-1" } },
  );
  expect(screen.getByText("跨课件关联")).toBeInTheDocument();
  expect(screen.getByText(/线性相关/)).toBeInTheDocument();
});

test("continues a partial homework and refreshes after the SSE stream ends", async () => {
  const homework: HomeworkDetail = {
    id: "hw-1", course_id: "course-1", title: "作业一", file_type: "pdf",
    file_size: 1024, status: "partial", error_message: "第二题失败", folder_id: null,
    created_at: "2026-07-16T00:00:00Z", updated_at: "2026-07-16T00:00:00Z",
    solutions: [{
      id: "solution-1", question_number: 1, question_text: "证明命题",
      answer_text: null, thinking_process: null, created_at: "2026-07-16T00:00:00Z",
      knowledge_point_links: [],
    }],
  };
  const onHomeworkRefresh = vi.fn().mockResolvedValue(undefined);
  const fetchMock = vi.fn().mockResolvedValue(new Response(
    'data: {"type":"done"}\n\n',
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  ));
  vi.stubGlobal("fetch", fetchMock);

  render(
    <DetailPanel
      courseId="course-1" knowledgePoint={null} homework={homework}
      selectedQuestion={null} loading={false} error={null}
      onQuoteToChat={vi.fn()} onHomeworkRefresh={onHomeworkRefresh}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "继续解题" }));

  await waitFor(() => expect(onHomeworkRefresh).toHaveBeenCalledOnce());
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/homeworks/hw-1/solve?course_id=course-1",
    { method: "POST", headers: { "Content-Type": "application/json" } },
  );
});
