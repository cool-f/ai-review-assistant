import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSSE } from "./useSSE";


describe("useSSE reconnect lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("cancels a scheduled reconnect when the user stops", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);
    const callbacks = {
      onToken: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    };
    const { result } = renderHook(() => useSSE(callbacks));

    act(() => {
      result.current.start("/api/stream", { idempotency_key: "request-1" });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => result.current.stop());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  it("reuses the exact idempotent request body when reconnecting", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);
    const callbacks = {
      onToken: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    };
    const { result } = renderHook(() => useSSE(callbacks));
    const body = { content: "hello", idempotency_key: "request-2" };

    act(() => result.current.start("/api/stream", body));
    await act(async () => {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(1_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstInit = fetchMock.mock.calls[0][1] as RequestInit;
    const secondInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(firstInit.body).toBe(JSON.stringify(body));
    expect(secondInit.body).toBe(firstInit.body);

    act(() => result.current.stop());
  });
});
