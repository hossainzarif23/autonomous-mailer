"use client";

import { create } from "zustand";

import type { EmailDraft } from "@/types";

interface ApprovalState {
  isOpen: boolean;
  draft: EmailDraft | null;
  open: (draft: EmailDraft) => void;
  close: () => void;
  updateDraft: (patch: Partial<EmailDraft>) => void;
}

export const useApprovalStore = create<ApprovalState>((set) => ({
  isOpen: false,
  draft: null,
  open: (draft) => set({ draft, isOpen: true }),
  close: () => set({ draft: null, isOpen: false }),
  updateDraft: (patch) =>
    set((state) => ({
      draft: state.draft ? { ...state.draft, ...patch } : null
    }))
}));

