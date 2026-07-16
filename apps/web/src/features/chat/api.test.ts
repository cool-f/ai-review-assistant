import { beforeEach, describe, expect, it, vi } from "vitest";

import client from "@/shared/api/client";
import { createSession, listSessions } from "./api";


vi.mock("@/shared/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));


describe("chat API paths", () => {
  beforeEach(() => vi.clearAllMocks());

  it("does not duplicate the shared /api base path", async () => {
    vi.mocked(client.post).mockResolvedValue({ data: { id: "session-1" } });
    vi.mocked(client.get).mockResolvedValue({ data: { items: [] } });

    await createSession({ course_id: "course-1", title: "new" });
    await listSessions("course-1");

    expect(client.post).toHaveBeenCalledWith(
      "/chat/sessions",
      expect.objectContaining({ course_id: "course-1" }),
    );
    expect(client.get).toHaveBeenCalledWith(
      "/chat/sessions",
      expect.objectContaining({ params: expect.objectContaining({ course_id: "course-1" }) }),
    );
  });
});
