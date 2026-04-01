"use client";

import { create } from "zustand";

import type { EmailDraft } from "@/types";

interface ApprovalState {
  isOpen: boolean;
  draft: EmailDraft | null;
  originalDraft: EmailDraft | null;
  feedback: string;
  pendingDraftIds: string[];
  open: (draft: EmailDraft) => void;
  close: () => void;
  markPending: (draftId: string) => void;
  clearPending: (draftId: string) => void;
  isPending: (draftId: string) => boolean;
  updateDraft: (patch: Partial<EmailDraft>) => void;
  setFeedback: (feedback: string) => void;
}

export const useApprovalStore = create<ApprovalState>((set, get) => ({
  isOpen: false,
  draft: null,
  originalDraft: null,
  feedback: "",
  pendingDraftIds: [],
  open: (draft) =>
    set((state) => {
      if (state.pendingDraftIds.includes(draft.id)) {
        return state;
      }
      return { draft: { ...draft }, originalDraft: { ...draft }, feedback: "", isOpen: true };
    }),
  close: () => set({ draft: null, originalDraft: null, feedback: "", isOpen: false }),
  markPending: (draftId) =>
    set((state) => ({
      pendingDraftIds: state.pendingDraftIds.includes(draftId)
        ? state.pendingDraftIds
        : [...state.pendingDraftIds, draftId]
    })),
  clearPending: (draftId) =>
    set((state) => ({
      pendingDraftIds: state.pendingDraftIds.filter((id) => id !== draftId)
    })),
  isPending: (draftId) => get().pendingDraftIds.includes(draftId),
  updateDraft: (patch) =>
    set((state) => ({
      draft: state.draft ? { ...state.draft, ...patch } : null
    })),
  setFeedback: (feedback) => set({ feedback })
}));
