import { useCallback, useEffect, useRef, useState } from "react";

export interface UseSSECallbacks {
  onToken: (content: string) => void;
  onReplace?: (content: string) => void;
  onDone: (data: {
    message_id: string;
    token_count: number;
    citations?: unknown[];
  }) => void;
  onError: (message: string) => void;
}

export interface UseSSEReturn {
  start: (url: string, body?: Record<string, unknown>) => void;
  stop: () => void;
  isStreaming: boolean;
  isReconnecting: boolean;
  error: string | null;
}

const SSE_TIMEOUT_MS = 120_000;
const MAX_RECONNECT = 3;

class SSEHttpError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
  ) {
    super(message);
  }
}

/**
 * POST SSE client with bounded reconnects.
 *
 * Reconnects reuse the original request body, including its idempotency key.
 * A generation number prevents a stopped or superseded request from reconnecting.
 */
export function useSSE(callbacks: UseSSECallbacks): UseSSEReturn {
  const [isStreaming, setIsStreaming] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectCountRef = useRef(0);
  const generationRef = useRef(0);
  const isMountedRef = useRef(true);
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;

  const lastParamsRef = useRef<{
    url: string;
    method: "POST";
    body?: unknown;
  } | null>(null);

  const clearConnection = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const clearReconnect = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    generationRef.current += 1;
    clearConnection();
    clearReconnect();
    reconnectCountRef.current = 0;
    lastParamsRef.current = null;
    setIsStreaming(false);
    setIsReconnecting(false);
    setError(null);
  }, [clearConnection, clearReconnect]);

  const doConnect = useCallback(
    async (
      url: string,
      method: "POST",
      body: unknown,
      generation: number,
    ) => {
      const isCurrent = () =>
        isMountedRef.current && generationRef.current === generation;
      if (!isCurrent()) return;

      const controller = new AbortController();
      abortRef.current = controller;
      let timedOut = false;
      const timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, SSE_TIMEOUT_MS);
      timeoutRef.current = timeoutId;

      try {
        const response = await fetch(url, {
          method,
          headers: { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        });

        if (!response.ok) {
          const responseMessage = await response.text().catch(() => "");
          throw new SSEHttpError(
            responseMessage || `请求失败 (${response.status})`,
            response.status >= 500 || response.status === 408,
          );
        }
        if (!response.body) {
          throw new Error("响应体不可读");
        }

        if (isCurrent()) {
          setIsReconnecting(false);
          setError(null);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let receivedTerminalEvent = false;

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const events = buffer.split("\n\n");
            buffer = events.pop() ?? "";

            for (const rawEvent of events) {
              const dataLine = rawEvent
                .split("\n")
                .find((line) => line.startsWith("data:"));
              if (!dataLine) continue;

              let event: Record<string, unknown>;
              try {
                event = JSON.parse(dataLine.slice(5).trim()) as Record<string, unknown>;
              } catch {
                continue;
              }
              if (!isCurrent()) return;

              switch (event.type) {
                case "chunk":
                  callbacksRef.current.onToken(String(event.content ?? ""));
                  break;
                case "replace":
                  callbacksRef.current.onReplace?.(String(event.content ?? ""));
                  break;
                case "done":
                  receivedTerminalEvent = true;
                  callbacksRef.current.onDone({
                    message_id: String(event.message_id ?? ""),
                    token_count: Number(event.token_count ?? 0),
                    citations: event.citations as unknown[] | undefined,
                  });
                  break;
                case "error":
                  receivedTerminalEvent = true;
                  callbacksRef.current.onError(String(event.message ?? "请求失败"));
                  break;
              }
            }
          }
        } finally {
          reader.releaseLock();
        }

        if (!receivedTerminalEvent) {
          throw new Error("流式响应提前结束");
        }
        if (isCurrent()) {
          reconnectCountRef.current = 0;
          setIsStreaming(false);
          setIsReconnecting(false);
        }
      } catch (caught: unknown) {
        if (!isCurrent()) return;
        const wasUserAbort =
          caught instanceof DOMException && caught.name === "AbortError" && !timedOut;
        if (wasUserAbort) {
          setIsStreaming(false);
          return;
        }

        const retryable =
          !(caught instanceof SSEHttpError) || caught.retryable;
        if (retryable && reconnectCountRef.current < MAX_RECONNECT) {
          reconnectCountRef.current += 1;
          setIsReconnecting(true);
          setError("正在重连…");
          const delay = 2 ** (reconnectCountRef.current - 1) * 1000;
          const params = lastParamsRef.current;
          reconnectTimerRef.current = setTimeout(() => {
            reconnectTimerRef.current = null;
            if (isCurrent() && params) {
              void doConnect(params.url, params.method, params.body, generation);
            }
          }, delay);
          return;
        }

        const message = caught instanceof Error ? caught.message : "连接失败";
        setIsStreaming(false);
        setIsReconnecting(false);
        setError(message);
        callbacksRef.current.onError(message);
      } finally {
        clearTimeout(timeoutId);
        if (timeoutRef.current === timeoutId) timeoutRef.current = null;
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [],
  );

  const start = useCallback(
    (url: string, body?: Record<string, unknown>) => {
      generationRef.current += 1;
      const generation = generationRef.current;
      clearConnection();
      clearReconnect();
      reconnectCountRef.current = 0;
      lastParamsRef.current = { url, method: "POST", body };
      setIsStreaming(true);
      setIsReconnecting(false);
      setError(null);
      void doConnect(url, "POST", body, generation);
    },
    [clearConnection, clearReconnect, doConnect],
  );

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      generationRef.current += 1;
      clearConnection();
      clearReconnect();
    };
  }, [clearConnection, clearReconnect]);

  return { start, stop, isStreaming, isReconnecting, error };
}
