/**
 * 聊天 API 客户端
 */

import axios from "axios";
import type {
  ChatSession,
  ChatSessionListResponse,
  ChatSessionCreate,
  ChatHistoryResponse,
} from "../types/chat";

const BASE = "/api/chat";

// ── 会话 ──────────────────────────────────────────

/** 创建新会话 */
export async function createSession(
  data: ChatSessionCreate
): Promise<ChatSession> {
  const res = await axios.post<ChatSession>(`${BASE}/sessions`, data);
  return res.data;
}

/** 获取会话分页列表 */
export async function listSessions(
  page = 1,
  size = 20
): Promise<ChatSessionListResponse> {
  const res = await axios.get<ChatSessionListResponse>(`${BASE}/sessions`, {
    params: { page, size },
  });
  return res.data;
}

/** 获取单个会话详情 */
export async function getSession(
  sessionId: string
): Promise<ChatSession> {
  const res = await axios.get<ChatSession>(`${BASE}/sessions/${sessionId}`);
  return res.data;
}

/** 删除会话 */
export async function deleteSession(sessionId: string): Promise<void> {
  await axios.delete(`${BASE}/sessions/${sessionId}`);
}

// ── 消息 ──────────────────────────────────────────

/** 获取会话历史消息 */
export async function getHistory(
  sessionId: string
): Promise<ChatHistoryResponse> {
  const res = await axios.get<ChatHistoryResponse>(
    `${BASE}/sessions/${sessionId}/messages`
  );
  return res.data;
}
