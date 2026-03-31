"use client";

import { useEffect } from "react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import type { UserProfile } from "@/types";

export function useAuth() {
  const { user, status, setStatus, setUser, reset } = useAuthStore();

  async function refreshUser() {
    setStatus("loading");
    try {
      const response = await api.get<UserProfile>("/auth/me");
      setUser(response.data);
      return response.data;
    } catch {
      reset();
      return null;
    }
  }

  async function logout() {
    try {
      await api.post("/auth/logout");
    } finally {
      reset();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
  }

  useEffect(() => {
    if (status === "idle") {
      void (async () => {
        setStatus("loading");
        try {
          const response = await api.get<UserProfile>("/auth/me");
          setUser(response.data);
        } catch {
          reset();
        }
      })();
    }
  }, [reset, setStatus, setUser, status]);

  return { user, status, refreshUser, logout };
}
