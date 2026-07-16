/**
 * 聊天 API 客户端
 */

import client from "@/shared/api/client";
import type {
  ChatSession,
  ChatSessionListResponse,
  ChatSessionCreate,
  ChatHistoryResponse,
} from "./types";

const BASE = "/chat";

// ── 会话 ──────────────────────────────────────────

/** 创建新会话 */
export async function createSession(
  data: ChatSessionCreate
): Promise<ChatSession> {
  const res = await client.post<ChatSession>(`${BASE}/sessions`, data);
  return res.data;
}

/** 获取会话分页列表 */
export async function listSessions(
  courseId: string,
  page = 1,
  size = 20
): Promise<ChatSessionListResponse> {
  const res = await client.get<ChatSessionListResponse>(`${BASE}/sessions`, {
    params: { course_id: courseId, page, size },
  });
  return res.data;
}

/** 获取单个会话详情 */
export async function getSession(
  sessionId: string,
  courseId: string,
): Promise<ChatSession> {
  const res = await client.get<ChatSession>(`${BASE}/sessions/${sessionId}`, {
    params: { course_id: courseId },
  });
  return res.data;
}

/** 删除会话 */
export async function deleteSession(sessionId: string, courseId: string): Promise<void> {
  await client.delete(`${BASE}/sessions/${sessionId}`, {
    params: { course_id: courseId },
  });
}

// ── 消息 ──────────────────────────────────────────

/** 获取会话历史消息 */
export async function getHistory(
  sessionId: string,
  courseId: string,
): Promise<ChatHistoryResponse> {
  const res = await client.get<ChatHistoryResponse>(
    `${BASE}/sessions/${sessionId}/messages`,
    { params: { course_id: courseId } },
  );
  return res.data;
}
