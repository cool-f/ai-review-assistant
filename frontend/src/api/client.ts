import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

/**
 * Axios 实例 —— 统一的后端 API 通信客户端
 *
 * - baseURL='/api'  由 Vite dev-server proxy 转发到 FastAPI :8000
 * - timeout=30000   30 秒超时，避免无限等待
 * - 请求拦截器：可扩展注入 Authorization header
 * - 响应拦截器：将后端错误统一转换为可展示的 Error
 */

const client = axios.create({
  baseURL: "/api",
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

/* ── 请求拦截器 ─────────────────────────────────── */
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 预留：将来可从 auth store 读取 token 并注入
    // const token = getAuthToken();
    // if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

/* ── 响应拦截器 ─────────────────────────────────── */
client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    // 统一提取后端错误消息
    if (error.response) {
      const detail =
        error.response.data?.detail ??
        (typeof error.response.data === "string" ? error.response.data : undefined) ??
        `请求失败 (${error.response.status})`;

      const unified = new Error(detail);
      (unified as Error & { status: number }).status = error.response.status;
      return Promise.reject(unified);
    }

    if (error.request) {
      return Promise.reject(new Error("网络连接失败，请检查网络后重试"));
    }

    return Promise.reject(new Error(error.message || "未知请求错误"));
  },
);

export default client;
