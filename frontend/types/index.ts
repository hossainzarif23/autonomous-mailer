export type MessageRole = "user" | "assistant";

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  picture_url: string | null;
  gmail_scope_granted: boolean;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  metadata?: {
    emails?: EmailSummary[];
    draft_id?: string;
    is_waiting_approval?: boolean;
  };
  created_at: string;
}

export interface EmailSummary {
  message_id: string;
  thread_id: string;
  from_name: string;
  from_email: string;
  subject: string;
  snippet: string;
  date: string;
}

export interface EmailDraft {
  id: string;
  to: string;
  subject: string;
  body: string;
  draft_type: "reply" | "fresh";
  description?: string | null;
}

export type ApprovalAction = "approve" | "edit" | "reject";

export interface ApprovalDraftPayload {
  to: string;
  subject: string;
  body: string;
  draft_type: "reply" | "fresh";
  description?: string | null;
}

export interface SSEEvent {
  type:
    | "token"
    | "approval_pending"
    | "approval_required"
    | "email_sent"
    | "email_rejected"
    | "error"
    | "done"
    | "ping";
  content?: string;
  draft_id?: string;
  draft?: ApprovalDraftPayload;
  description?: string;
  title?: string;
  body?: string;
  gmail_message_id?: string;
}
