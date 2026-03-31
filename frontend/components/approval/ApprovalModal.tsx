"use client";

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
import { useApprovalStore } from "@/stores/approvalStore";

export function ApprovalModal() {
  const { draft, isOpen, close, updateDraft } = useApprovalStore();

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Approval required</DialogTitle>
          <DialogDescription>
            Draft review is scaffolded now so the LangGraph HITL flow can plug in cleanly during Phase 5.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
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
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={close}>
            Reject
          </Button>
          <Button onClick={close}>Approve</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

