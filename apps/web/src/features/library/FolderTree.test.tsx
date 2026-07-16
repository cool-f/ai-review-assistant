import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import client from "@/shared/api/client";
import FolderTree from "./FolderTree";

vi.mock("@/shared/api/client", () => ({
  default: { delete: vi.fn(), get: vi.fn(), patch: vi.fn(), post: vi.fn() },
}));

const courseware = (overrides: Record<string, unknown> = {}) => ({
  id: "cw-1", course_id: "course-1", title: "线性代数讲义", file_type: "pdf",
  file_size: 2048, status: "completed", parse_status: "completed",
  knowledge_status: "completed", embedding_status: "completed", linking_status: "completed",
  failed_stage: null, retry_count: 0, error_message: null, page_count: 10,
  folder_id: null, created_at: "2026-07-16T00:00:00Z", updated_at: "2026-07-16T00:00:00Z",
  ...overrides,
});

function mockTreeLoad(itemFactory: () => ReturnType<typeof courseware>) {
  vi.mocked(client.get).mockImplementation(async (url) => {
    if (url === "/folders/") return { data: { items: [], total: 0 } } as never;
    if (url === "/coursewares/") {
      return { data: { items: [itemFactory()], total: 1, page: 1, size: 100, pages: 1 } } as never;
    }
    return { data: { items: [] } } as never;
  });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

test("shows explicit semantic degradation and retries a partial ingestion", async () => {
  mockTreeLoad(() => courseware({
    status: "partial", embedding_status: "failed", failed_stage: "embedding",
  }));
  vi.mocked(client.post).mockResolvedValue({ data: { status: "processing" } } as never);

  render(<FolderTree courseId="course-1" category="courseware" />);
  await waitFor(() => expect(screen.getByText("语义能力降级")).toBeInTheDocument());
  fireEvent.click(screen.getByText("线性代数讲义"));
  await waitFor(() => expect(client.get).toHaveBeenCalledWith(
    "/coursewares/cw-1/knowledge-points/",
    { params: { course_id: "course-1", size: 100 } },
  ));
  fireEvent.click(screen.getByRole("button", { name: "重试" }));

  await waitFor(() => expect(client.post).toHaveBeenCalledWith(
    "/coursewares/cw-1/knowledge-points/extract",
    {},
    { params: { course_id: "course-1" } },
  ));
});

test("polls processing courseware until it reaches a terminal state", async () => {
  vi.useFakeTimers();
  let coursewareLoads = 0;
  mockTreeLoad(() => {
    coursewareLoads += 1;
    return courseware({ status: coursewareLoads === 1 ? "processing" : "completed" });
  });

  render(<FolderTree courseId="course-1" category="courseware" />);
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(screen.getByText("处理中")).toBeInTheDocument();

  await act(async () => { await vi.advanceTimersByTimeAsync(2600); });
  expect(coursewareLoads).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("已完成")).toBeInTheDocument();
});

test("requires explicit confirmation before destructive full re-extraction", async () => {
  mockTreeLoad(() => courseware({ status: "failed", failed_stage: "knowledge" }));
  vi.mocked(client.post)
    .mockRejectedValueOnce({ response: { status: 409 } })
    .mockResolvedValueOnce({ data: { status: "processing" } } as never);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<FolderTree courseId="course-1" category="courseware" />);
  await waitFor(() => expect(screen.getByText("线性代数讲义")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "重试" }));

  await waitFor(() => expect(client.post).toHaveBeenNthCalledWith(
    2,
    "/coursewares/cw-1/knowledge-points/extract",
    { force: true },
    { params: { course_id: "course-1" } },
  ));
  expect(confirm).toHaveBeenCalledOnce();
  confirm.mockRestore();
});
