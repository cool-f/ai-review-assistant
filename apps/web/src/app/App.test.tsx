import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import client from "@/shared/api/client";
import App from "./App";

vi.mock("@/shared/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("@/features/library/DirectoryTree", () => ({ default: () => <div>library</div> }));
vi.mock("@/features/chat/ChatPanel", () => ({ default: () => <div>chat</div> }));
vi.mock("@/features/practice/PracticePanel", () => ({ default: () => <div>practice</div> }));
vi.mock("@/features/study/DetailPanel", () => ({ default: () => <div>detail</div> }));
vi.mock("@/features/usage/UsagePanel", () => ({ default: () => <div>usage</div> }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("creates the first course and makes it the active business context", async () => {
  const course = {
    id: "course-1", name: "高等数学", term: "2026 春", description: "",
    courseware_count: 0, homework_count: 0, folder_count: 0, session_count: 0,
    created_at: "2026-07-16T00:00:00Z", updated_at: "2026-07-16T00:00:00Z",
  };
  vi.mocked(client.get).mockResolvedValue({ data: [] } as never);
  vi.mocked(client.post).mockResolvedValue({ data: course } as never);
  vi.spyOn(window, "prompt")
    .mockReturnValueOnce("  高等数学  ")
    .mockReturnValueOnce("  2026 春  ");

  render(<App />);
  await waitFor(() => expect(client.get).toHaveBeenCalledWith("/courses"));
  fireEvent.click(screen.getByRole("button", { name: "新建课程" }));

  await waitFor(() => expect(client.post).toHaveBeenCalledWith(
    "/courses/",
    { name: "高等数学", term: "2026 春" },
  ));
  expect(screen.getByRole("combobox")).toHaveValue("course-1");
  expect(screen.getByRole("option", { name: /高等数学/ })).toBeInTheDocument();
});
