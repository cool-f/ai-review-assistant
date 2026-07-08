import { useState, useRef, useCallback, useEffect } from "react";

/* ── 类型定义 ────────────────────────────────────── */

/** SSE 流式回调 */
export interface UseSSECallbacks {
  /** 收到文本块 */
  onToken: (content: string) => void;
  /** 流式完成 */
  onDone: (data: { message_id: string; token_count: number }) => void;
  /** 错误发生 */
  onError: (message: string) => void;
}

/** useSSE 返回值 */
export interface UseSSEReturn {
  /** 发起 SSE 连接（默认 POST） */
  start: (url: string, body?: Record<string, unknown>) => void;
  /** 取消当前连接 */
  stop: () => void;
  /** 是否正在接收流 */
  isStreaming: boolean;
  /** 是否正在重连 */
  isReconnecting: boolean;
  /** 最近一次错误消息 */
  error: string | null;
}

/* ── 常量 ────────────────────────────────────────── */

const SSE_TIMEOUT_MS = 120_000; // 120 秒超时
const MAX_RECONNECT = 3; // 最多重连 3 次

/* ── useSSE Hook ─────────────────────────────────── */

/**
 * SSE 流式连接 Hook
 *
 * 使用 fetch + ReadableStream 建立 SSE 连接，支持 POST 请求体。
 * 自动解析 SSE data: 行，按 type 字段分发到 onToken / onDone / onError。
 * 内置 120s 超时断开、AbortController 取消、断线自动重连（最多3次）。
 *
 * @example
 * const { start, stop, isStreaming, isReconnecting, error } = useSSE({
 *   onToken: (chunk) => appendToMessage(chunk),
 *   onDone:  (data) => archiveMessage(data),
 *   onError: (msg)  => showError(msg),
 * });
 * // 开始聊天
 * start("/api/chat/sessions/abc/messages", { content: "你好" });
 * // 取消
 * stop();
 */
export function useSSE(callbacks: UseSSECallbacks): UseSSEReturn {
  // ── 渲染状态 ────────────────────────────────────
  const [isStreaming, setIsStreaming] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── 可变引用（避免闭包过期） ──────────────────────
  const abortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectCountRef = useRef(0);
  const isMountedRef = useRef(true);

  // 保存最近一次连接参数用于重连
  const lastParamsRef = useRef<{
    url: string;
    method: string;
    body?: unknown;
  } | null>(null);

  // 回调引用 — 始终指向最新的 callbacks
  const cbRef = useRef<UseSSECallbacks>(callbacks);
  cbRef.current = callbacks;

  // ── 内部辅助 ────────────────────────────────────

  /** 清理当前连接资源 */
  const cleanup = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  /** 停止一切：取消连接 + 重置状态 */
  const stop = useCallback(() => {
    cleanup();
    setIsStreaming(false);
    setIsReconnecting(false);
    setError(null);
    reconnectCountRef.current = 0;
    lastParamsRef.current = null;
  }, [cleanup]);

  // ── 核心连接逻辑 ────────────────────────────────

  /**
   * 执行一次 SSE 连接。
   * 所有可变状态通过 ref 访问，避免 useCallback 依赖导致闭包过期。
   */
  const doConnect = useCallback(
    async (url: string, method: string, body?: unknown) => {
      const controller = new AbortController();
      abortRef.current = controller;

      // 120s 超时定时器
      const timeoutId = setTimeout(() => {
        controller.abort();
      }, SSE_TIMEOUT_MS);
      timeoutRef.current = timeoutId;

      try {
        // ── 发起 fetch ──────────────────────────────
        const fetchInit: RequestInit = {
          method,
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
        };

        if (body !== undefined) {
          fetchInit.body = JSON.stringify(body);
        }

        const response = await fetch(url, fetchInit);

        if (!response.ok) {
          let message: string;
          try {
            message = await response.text();
          } catch {
            message = `请求失败 (${response.status})`;
          }
          throw new Error(message || `请求失败 (${response.status})`);
        }

        if (!response.body) {
          throw new Error("响应体不可读");
        }

        // ── 连接成功，重置重连计数 ──────────────────
        reconnectCountRef.current = 0;
        if (isMountedRef.current) {
          setIsReconnecting(false);
          setError(null);
        }

        // ── 读取流 ──────────────────────────────────
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            // 增量解码
            buffer += decoder.decode(value, { stream: true });

            // 按 \n\n 分割 SSE 事件（最后一个可能不完整，保留在 buffer 中）
            const parts = buffer.split("\n\n");
            buffer = parts.pop() || "";

            for (const part of parts) {
              const trimmed = part.trim();
              if (!trimmed) continue;

              // 提取 "data: {...}" 中的 JSON 部分
              let dataLine = trimmed;
              if (trimmed.startsWith("data: ")) {
                dataLine = trimmed.slice(6);
              }

              try {
                const event = JSON.parse(dataLine);

                switch (event.type) {
                  case "chunk":
                    cbRef.current.onToken(event.content);
                    break;
                  case "done":
                    cbRef.current.onDone({
                      message_id: event.message_id,
                      token_count: event.token_count,
                    });
                    break;
                  case "error":
                    cbRef.current.onError(event.message);
                    break;
                }
              } catch {
                // 忽略无法解析的 SSE 行（如注释、心跳等）
                console.warn("SSE 解析失败:", dataLine);
              }
            }
          }
        } finally {
          reader.releaseLock();
          clearTimeout(timeoutId);
          timeoutRef.current = null;
        }

        // ── 流正常结束 ──────────────────────────────
        if (isMountedRef.current) {
          setIsStreaming(false);
        }
      } catch (err: unknown) {
        clearTimeout(timeoutId);
        timeoutRef.current = null;

        // AbortError: 用户取消或超时 —— 不重连
        if (err instanceof DOMException && err.name === "AbortError") {
          if (isMountedRef.current) {
            setIsStreaming(false);
          }
          return;
        }

        // 网络错误 / 服务端错误 —— 尝试重连
        if (
          isMountedRef.current &&
          reconnectCountRef.current < MAX_RECONNECT
        ) {
          reconnectCountRef.current++;
          setIsReconnecting(true);
          setError("正在重连...");

          // 指数退避: 1s, 2s, 4s
          const delay = Math.pow(2, reconnectCountRef.current - 1) * 1000;
          const params = lastParamsRef.current;

          setTimeout(() => {
            if (isMountedRef.current && params) {
              doConnect(params.url, params.method, params.body);
            }
          }, delay);
        } else {
          // 重连次数耗尽
          if (isMountedRef.current) {
            setIsReconnecting(false);
            setIsStreaming(false);
            const message =
              err instanceof Error ? err.message : "连接失败";
            setError(message);
            cbRef.current.onError(message);
          }
        }
      }
    },
    [], // 空依赖 — 所有可变状态通过 ref 访问，函数体不变
  );

  // ── 公开 API ────────────────────────────────────

  /** 发起 SSE 连接 */
  const start = useCallback(
    (url: string, body?: Record<string, unknown>) => {
      // 先停止当前连接
      cleanup();
      reconnectCountRef.current = 0;
      lastParamsRef.current = { url, method: "POST", body };
      setIsStreaming(true);
      setIsReconnecting(false);
      setError(null);
      doConnect(url, "POST", body);
    },
    [cleanup, doConnect],
  );

  // ── 组件卸载清理 ────────────────────────────────

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  return { start, stop, isStreaming, isReconnecting, error };
}
