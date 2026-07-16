import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import client from "@/shared/api/client";
import UsagePanel from "./UsagePanel";

vi.mock("@/shared/api/client", () => ({
  default: { get: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("loads and displays daily, purpose, and provider usage for the course", async () => {
  vi.mocked(client.get).mockImplementation(async (url) => {
    if (url === "/admin/token-usage/budget") {
      return { data: {
        today_usage: 240, daily_budget: 1000, percentage: 24,
        within_budget: true, call_count_today: 3, warning: null,
      } } as never;
    }
    if (url === "/admin/token-usage") {
      return { data: { items: [{
        date: "2026-07-16", prompt_tokens: 100, completion_tokens: 140,
        total_tokens: 240, call_count: 3,
      }] } } as never;
    }
    if (url === "/admin/token-usage/by-purpose") {
      return { data: { items: [{ purpose: "chat", total_tokens: 180, call_count: 2 }] } } as never;
    }
    return { data: { items: [{ provider: "openai", total_tokens: 240, call_count: 3 }] } } as never;
  });

  render(<UsagePanel courseId="course-1" />);

  await waitFor(() => expect(screen.getByText("2026-07-16")).toBeInTheDocument());
  expect(screen.getAllByText("240 tokens").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("openai")).toBeInTheDocument();
  expect(client.get).toHaveBeenCalledWith(
    "/admin/token-usage",
    { params: { days: 7, course_id: "course-1" } },
  );
});
