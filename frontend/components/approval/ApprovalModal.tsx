"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, getErrorMessage } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { useApprovalStore } from "@/stores/approvalStore";

export function ApprovalModal() {
  const { draft, originalDraft, isOpen, close, markPending, clearPending, updateDraft, feedback, setFeedback } = useApprovalStore();
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(action: "approve" | "reject") {
    if (!draft || isSubmitting) {
      return;
    }
    if (action === "reject" && !feedback.trim()) {
      toast({
        title: "Feedback Required",
        description: "Add revision feedback before rejecting the draft."
      });
      return;
    }

    setIsSubmitting(true);
    const submittedDraft = { ...draft };
    markPending(submittedDraft.id);
    close();

    try {
      const isEdited =
        submittedDraft.to !== originalDraft?.to ||
        submittedDraft.subject !== originalDraft?.subject ||
        submittedDraft.body !== originalDraft?.body;

      await api.post(`/approve/${submittedDraft.id}`, {
        action: action === "approve" ? (isEdited ? "edit" : "approve") : "reject",
        edited_to: submittedDraft.to,
        edited_subject: submittedDraft.subject,
        edited_body: submittedDraft.body,
        feedback: feedback.trim() || undefined
      });
      toast({
        title: action === "reject" ? "Revision Requested" : "Approval Submitted",
        description:
          action === "reject"
            ? "The agent is revising the draft using your feedback."
            : "The draft was resumed and the agent is finishing the workflow."
      });
    } catch (error) {
      clearPending(submittedDraft.id);
      useApprovalStore.getState().open(submittedDraft);
      useApprovalStore.getState().setFeedback(feedback);
      toast({
        title: "Approval Error",
        description: getErrorMessage(error, "Failed to process the draft.")
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && close()}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden p-0 sm:max-h-[85vh]">
        <DialogHeader className="shrink-0 border-b border-border px-6 py-5 pr-12">
          <DialogTitle>Approval required</DialogTitle>
          <DialogDescription>
            Review the generated draft before the workflow resumes and sends it through Gmail.
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="space-y-4">
          {draft?.description ? (
            <p className="whitespace-pre-wrap rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm leading-6">
              {draft.description}
            </p>
          ) : null}
          <Input
            value={draft?.to ?? ""}
            onChange={(event) => updateDraft({ to: event.target.value })}
            placeholder="Recipient"
          />
          <Input
            value={draft?.subject ?? ""}
            onChange={(event) => updateDraft({ subject: event.target.value })}
            placeholder="Subject"
          />
          <Textarea
            value={draft?.body ?? ""}
            onChange={(event) => updateDraft({ body: event.target.value })}
            placeholder="Draft body"
            className="min-h-[18rem]"
          />
          <Textarea
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            placeholder="Feedback for rewrite if you reject this draft"
            className="min-h-[8rem]"
          />
          </div>
        </div>
        <DialogFooter className="shrink-0 border-t border-border bg-card px-6 py-4">
          <Button variant="outline" onClick={() => void submit("reject")} disabled={isSubmitting}>
            Request Rewrite
          </Button>
          <Button onClick={() => void submit("approve")} disabled={isSubmitting || !draft}>
            {isSubmitting ? "Submitting" : "Approve"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
