import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import client from "@/shared/api/client";
import { QuestionCard } from "./PracticePanel";
import type { GeneratedQuestion } from "@/shared/types";


vi.mock("@/shared/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});


test("submits an answer and shows grading plus progress feedback", async () => {
  vi.mocked(client.get).mockResolvedValue({ data: [] } as never);
  vi.mocked(client.post).mockResolvedValue({
    data: {
      attempt: {
        id: "attempt-1", question_id: "q-1", submitted_answer: "A. 正确",
        is_correct: true, feedback: "回答正确", grading_method: "deterministic",
        counted_for_progress: true, created_at: "2026-01-01T00:00:00Z",
      },
      progress: { status: "in_progress" },
    },
  } as never);
  const onProgressChange = vi.fn();
  const question: GeneratedQuestion = {
    id: "q-1", courseware_id: "cw-1", knowledge_point_id: "kp-1",
    question_type: "选择题", question_text: "正确选项是？",
    options: ["A. 正确", "B. 错误"], answer_text: "A. 正确", explanation: null,
    source_style: "ai_generated", difficulty: "简单", knowledge_points: [],
    created_at: "2026-01-01T00:00:00Z",
  };

  render(
    <QuestionCard
      question={question}
      courseId="course-1"
      onQuote={vi.fn()}
      onSelect={vi.fn()}
      onProgressChange={onProgressChange}
    />,
  );
  fireEvent.click(screen.getByLabelText("A. 正确"));
  fireEvent.click(screen.getByLabelText("提交答案"));

  await waitFor(() => expect(screen.getAllByText("回答正确").length).toBeGreaterThan(0));
  expect(screen.getByText(/本题已计入进度/)).toBeInTheDocument();
  expect(onProgressChange).toHaveBeenCalledOnce();
});


test("loads and displays persisted attempt history", async () => {
  vi.mocked(client.get).mockResolvedValue({
    data: [{
      id: "attempt-old", question_id: "q-1", submitted_answer: "B. 错误",
      is_correct: false, feedback: "请复习定义", grading_method: "ai",
      counted_for_progress: true, created_at: "2026-01-01T00:00:00Z",
    }],
  } as never);
  const question: GeneratedQuestion = {
    id: "q-1", courseware_id: "cw-1", knowledge_point_id: "kp-1",
    question_type: "选择题", question_text: "正确选项是？",
    options: ["A. 正确", "B. 错误"], answer_text: "A. 正确", explanation: null,
    source_style: "ai_generated", difficulty: "简单", knowledge_points: [],
    created_at: "2026-01-01T00:00:00Z",
  };

  render(
    <QuestionCard
      question={question}
      courseId="course-1"
      onQuote={vi.fn()}
      onSelect={vi.fn()}
    />,
  );
  await waitFor(() => expect(screen.getByText("作答历史（1）")).toBeInTheDocument());
  fireEvent.click(screen.getByText("作答历史（1）"));
  expect(screen.getByText("作答：B. 错误")).toBeInTheDocument();
  expect(screen.getByText("反馈：请复习定义")).toBeInTheDocument();
  expect(client.get).toHaveBeenCalledWith(
    "/questions/q-1/attempts",
    { params: { course_id: "course-1" } },
  );
});
