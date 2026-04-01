import axios from "axios";
import type { InternalAxiosRequestConfig } from "axios";

const baseURL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

interface ApiErrorPayload {
  error?: string;
  detail?: unknown;
}

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _authRedirectTriggered?: boolean;
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object") {
          const message = "msg" in item ? item.msg : null;
          const location = "loc" in item && Array.isArray(item.loc) ? item.loc.join(".") : null;
          return [location, message].filter(Boolean).join(": ");
        }
        return null;
      })
      .filter(Boolean)
      .join(" | ");
  }
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return null;
    }
  }
  return null;
}

function redirectToLogin() {
  if (typeof window === "undefined") {
    return;
  }

  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (path.startsWith("/login")) {
    return;
  }

  const next = encodeURIComponent(path || "/dashboard");
  window.location.href = `/login?next=${next}`;
}

export function getErrorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (axios.isAxiosError<ApiErrorPayload>(error)) {
    const detail = formatDetail(error.response?.data?.detail);
    if (detail) {
      return detail;
    }
    if (error.response?.data?.error) {
      return error.response.data.error;
    }
    if (error.message) {
      return error.message;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallback;
}

export const api = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json"
  }
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestConfig = error.config as RetryableRequestConfig | undefined;
    if (typeof window !== "undefined" && error.response?.status === 401 && !requestConfig?._authRedirectTriggered) {
      if (requestConfig) {
        requestConfig._authRedirectTriggered = true;
      }
      redirectToLogin();
    }

    if (axios.isAxiosError<ApiErrorPayload>(error)) {
      const message = getErrorMessage(error);
      if (message) {
        error.message = message;
      }
    }

    return Promise.reject(error);
  }
);
