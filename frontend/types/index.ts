export type MessageRole = "user" | "assistant";
export type TurnStatus = "streaming" | "complete" | "waiting_approval" | "error" | null;

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
  conversation_id?: string | null;
  to: string;
  subject: string;
  body: string;
  draft_type: "reply" | "fresh";
  status?: string | null;
  description?: string | null;
}

export type ApprovalAction = "approve" | "edit" | "reject";

export interface ApprovalDraftPayload {
  id?: string;
  conversation_id?: string | null;
  to: string;
  subject: string;
  body: string;
  draft_type: "reply" | "fresh";
  status?: string | null;
  description?: string | null;
}

export interface MarkdownBlock {
  type: "markdown";
  content: string;
}

export interface StatusBlock {
  type: "status";
  label: string;
  tone?: "neutral" | "pending" | "success" | "warning" | "error";
  detail?: string | null;
}

export interface ToolActionBlock {
  type: "tool_action";
  label: string;
  state: "running" | "complete" | "waiting" | "error";
  detail?: string | null;
}

export interface EmailListBlock {
  type: "email_list";
  title?: string | null;
  emails: EmailSummary[];
}

export interface SummaryBlock {
  type: "summary";
  title?: string | null;
  content: string;
}

export interface ResearchReportBlock {
  type: "research_report";
  title?: string | null;
  content: string;
}

export interface DraftEmailBlock {
  type: "draft_email";
  draft_id: string;
  conversation_id?: string | null;
  to: string;
  subject: string;
  body_preview: string;
  draft_type: "reply" | "fresh";
  approval_state: "draft_ready" | "waiting_approval" | "rewrite_requested" | "sent" | "error";
}

export interface SystemNoticeBlock {
  type: "system_notice";
  title?: string | null;
  content: string;
}

export type ChatContentBlock =
  | MarkdownBlock
  | StatusBlock
  | ToolActionBlock
  | EmailListBlock
  | SummaryBlock
  | ResearchReportBlock
  | DraftEmailBlock
  | SystemNoticeBlock;

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  content_blocks?: ChatContentBlock[] | null;
  status?: TurnStatus;
  turn_id?: string | null;
  metadata?: {
    draft_id?: string;
    is_waiting_approval?: boolean;
  };
  created_at: string;
}

export interface SSEEvent {
  type:
    | "token"
    | "turn_started"
    | "action_started"
    | "action_completed"
    | "artifact_available"
    | "approval_pending"
    | "approval_required"
    | "email_sent"
    | "email_rejected"
    | "turn_completed"
    | "error"
    | "done"
    | "ping";
  turn_id?: string;
  content?: string;
  draft_id?: string;
  conversation_id?: string;
  draft?: ApprovalDraftPayload;
  description?: string;
  title?: string;
  body?: string;
  gmail_message_id?: string;
}
