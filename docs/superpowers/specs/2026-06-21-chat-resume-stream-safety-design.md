# Chat Resume and Streaming Safety Design

## Context

Two related issues were observed in the dashboard chat flow:

1. A normal chat message resumed a previous LangGraph human-in-the-loop interruption and completed an old draft send.
2. The live chat stream exposed internal agent/tool content, including raw research and tool JSON, instead of a clean user-facing progress stream.

Both issues cross the same backend boundary: `/api/chat/message` currently invokes the coordinator on the conversation-scoped LangGraph thread and forwards all `messages` stream chunks to the browser.

## Goals

- Normal chat messages must never resume or complete a pending send approval.
- Only `/api/approve/{draft_id}` may resume a LangGraph HITL interruption with `Command(resume=...)`.
- Streaming chat must show user-safe progress and final assistant prose only.
- Tool calls, tool outputs, raw JSON payloads, internal sub-agent transcripts, and research provider payloads must not stream as markdown text.
- The final visible answer remains the structured conversation history loaded from `/api/chat/history/{conversation_id}`.

## Non-Goals

- Do not redesign the entire agent architecture.
- Do not create a new conversation storage model.
- Do not add a frontend test framework in this change.
- Do not add a developer debug stream yet.

## Approved Approach

Use a hard HITL boundary plus a filtered stream contract.

## Backend Design

### Pending Approval Guard

Before `/api/chat/message` invokes the coordinator, it checks for a pending approval draft owned by the current user and conversation:

- `EmailDraft.user_id == current_user.id`
- `EmailDraft.conversation_id == payload.conversation_id`
- `EmailDraft.status == "pending_approval"`

If a pending draft exists, the chat endpoint does not call `get_coordinator_agent()` and does not call `coordinator.astream()`.

Instead, it returns request-scoped SSE events:

- `turn_started`
- `approval_blocked`
- `done`

`approval_blocked` includes:

- `draft_id`
- `conversation_id`
- a user-facing message such as `Review the pending draft before sending another message in this conversation.`

This preserves the active conversation while preventing normal chat from accidentally driving an interrupted send to completion.

### Approval Resume Boundary

`/api/approve/{draft_id}` remains the only endpoint that calls:

```python
Command(resume={"decisions": [...]})
```

The approval endpoint keeps the current behavior for approve, edit, and reject, but implementation tests must verify that normal chat does not resume a pending approval.

### Filtered Chat Stream

`/api/chat/message` stops forwarding every LangGraph `messages` chunk as a `token`.

The stream contract becomes:

- `turn_started`: created when request processing begins.
- `action_started`: emitted when a known agent/tool step begins.
- `action_completed`: emitted when a known step completes.
- `approval_pending`: emitted when a draft approval interrupt is persisted.
- `token`: emitted only for safe assistant prose intended for the user.
- `turn_completed`: emitted when the agent finishes without blocking.
- `done`: terminal event.
- `error`: user-facing error.
- `approval_blocked`: emitted when normal chat is blocked by an existing pending draft.

Known tool labels stay consistent with history rendering:

- `call_mail_reader` -> `Inbox reviewed`
- `call_web_search` -> `Research completed`
- `call_mailing_agent` -> `Draft generated`
- `send_email` -> `Email sent`

Tool call metadata, tool message contents, JSON payloads, and provider raw content are not emitted as `token`.

## Frontend Design

`useChat` handles the cleaner event stream:

- `action_started` and `action_completed` update the optimistic assistant message with status/action blocks.
- `approval_pending` marks the assistant message as waiting for approval and reloads conversation history.
- `approval_blocked` marks the assistant message as waiting for approval, shows a toast, and reloads history so the draft card/modal state remains authoritative.
- `token` appends only safe assistant prose.
- `turn_completed` and `done` reload conversation history, replacing optimistic status content with backend-serialized structured blocks.

The frontend must not render raw internal payloads as markdown during streaming.

## Error Handling

- Pending approval guard is not an error response. It is a successful SSE stream with an `approval_blocked` event.
- If the pending draft cannot be loaded by the frontend reload, the user still sees the toast and the existing conversation state.
- Existing `error` events remain for unexpected backend failures.

## Testing Plan

Backend tests:

- A pending draft in the target conversation causes `/api/chat/message` to emit `approval_blocked` and skip coordinator invocation.
- A pending draft in another conversation does not block the current conversation.
- Stream filtering does not emit tool JSON or tool message contents as `token`.
- Existing pure backend service tests continue passing.

Frontend verification:

- `npm run build` must pass.
- Manual browser check verifies pending approval blocks normal chat and clean status/prose streaming remains readable.

## Acceptance Criteria

- Sending a normal chat message in a conversation with a pending draft cannot send the email.
- Approve/edit/reject still resumes the pending draft through `/api/approve/{draft_id}`.
- During streaming, the browser never displays raw tool JSON, internal sub-agent payloads, or provider result objects as markdown.
- Final chat history still renders research, summaries, email lists, and draft cards as structured blocks.
