"use client";

import { create } from "zustand";

import type { UserProfile } from "@/types";

type AuthStatus = "idle" | "loading" | "authenticated" | "unauthenticated";

interface AuthState {
  user: UserProfile | null;
  status: AuthStatus;
  setUser: (user: UserProfile | null) => void;
  setStatus: (status: AuthStatus) => void;
  reset: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: "idle",
  setUser: (user) =>
    set({
      user,
      status: user ? "authenticated" : "unauthenticated"
    }),
  setStatus: (status) => set({ status }),
  reset: () => set({ user: null, status: "unauthenticated" })
}));

