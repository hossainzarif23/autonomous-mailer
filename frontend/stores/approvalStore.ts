"use client";

import { create } from "zustand";

import type { EmailDraft } from "@/types";

interface ApprovalState {
  isOpen: boolean;
  draft: EmailDraft | null;
  originalDraft: EmailDraft | null;
  feedback: string;
  open: (draft: EmailDraft) => void;
  close: () => void;
  updateDraft: (patch: Partial<EmailDraft>) => void;
  setFeedback: (feedback: string) => void;
}

export const useApprovalStore = create<ApprovalState>((set) => ({
  isOpen: false,
  draft: null,
  originalDraft: null,
  feedback: "",
  open: (draft) => set({ draft: { ...draft }, originalDraft: { ...draft }, feedback: "", isOpen: true }),
  close: () => set({ draft: null, originalDraft: null, feedback: "", isOpen: false }),
  updateDraft: (patch) =>
    set((state) => ({
      draft: state.draft ? { ...state.draft, ...patch } : null
    })),
  setFeedback: (feedback) => set({ feedback })
}));
