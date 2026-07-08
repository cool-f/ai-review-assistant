/** 聊天相关 TypeScript 类型定义 */

/** 会话 */
export interface ChatSession {
  id: string;
  title: string;
  courseware_id: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** 会话分页列表 */
export interface ChatSessionListResponse {
  items: ChatSession[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

/** 创建会话请求 */
export interface ChatSessionCreate {
  title?: string;
  courseware_id?: string | null;
}

/** 单条消息 */
export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  token_count: number;
  created_at: string;
}

/** 历史消息响应 */
export interface ChatHistoryResponse {
  session_id: string;
  messages: ChatMessage[];
  total: number;
}

/** SSE 流式块 */
export interface SSEChunk {
  type: "chunk";
  content: string;
}

/** SSE 完成事件 */
export interface SSEDone {
  type: "done";
  message_id: string;
  token_count: number;
}

/** SSE 错误事件 */
export interface SSEError {
  type: "error";
  message: string;
}

/** SSE 事件联合类型 */
export type SSEEvent = SSEChunk | SSEDone | SSEError;
