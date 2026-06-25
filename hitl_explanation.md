# Human-in-the-Loop (HITL) in the Autonomous Emailing Agent

A complete walkthrough of how drafts are paused for human review, how approval/edit/rejection decisions are wired through the LangGraph coordinator, and how the frontend surfaces the approval modal and SSE events.

## 1. The big picture

The HITL boundary is the `send_email` tool. Every other step (mail reading, web research, drafting) is autonomous; the moment the coordinator decides to actually send mail, LangGraph's `HumanInTheLoopMiddleware` parks the run, the backend persists a `pending_approval` row, the user reviews/edits the draft in a modal, and the result is fed back into the same LangGraph run via `Command(resume=...)`.

```
LLM calls send_email
    -> HumanInTheLoopMiddleware interrupts
    -> persist_hitl_interrupts() writes EmailDraft(status="pending_approval")
    -> approval_required SSE event broadcast + yielded on chat stream
    -> User clicks Approve / Edit / Reject in ApprovalModal
    -> POST /approve/{draft_id}
    -> _build_decision() shapes approve | edit | reject for the middleware
    -> coordinator.astream(Command(resume={"decisions": [...]}))
    -> send_email tool fires; updates EmailDraft row to "sent" + gmail_sent_id
    -> email_sent SSE broadcast
```

## 2. Where the interrupt happens

### 2.1 Coordinator middleware configuration

`backend/app/agents/coordinator.py:227-251` — only `send_email` is interrupt-gated:

```python
_coordinator_agent = create_agent(
    model=get_llm(),
    tools=make_coordinator_tools(checkpointer),
    system_prompt=COORDINATOR_SYSTEM_PROMPT,
    state_schema=EmailAgentState,
    context_schema=AgentContext,
    checkpointer=checkpointer,
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "send_email": {
                    "allowed_decisions": ["approve", "edit", "reject"],
                    "description": _send_email_review_description,
                }
            }
        )
    ],
    name="coordinator",
)
```

The allowed decisions are exactly the three actions the modal exposes. Any other tool in `make_coordinator_tools` (`call_mail_reader`, `call_web_search`, `call_mailing_agent`) runs without interruption.

### 2.2 Description formatter

`backend/app/agents/coordinator.py:63-70` — `_send_email_review_description` provides the human-readable text shown in the SSE `description` field and persisted in `notifications.metadata`:

```python
def _send_email_review_description(
    tool_call: ToolCall,
    state: EmailAgentState,
    runtime: Runtime[AgentContext],
) -> str:
    draft = state.get("current_draft") or tool_call.get("args", {})
    draft_type = str(draft.get("draft_type") or "fresh")
    return f"Review this {draft_type} email before sending."
```

## 3. Coordinator state — the carrier for the draft

`backend/app/agents/coordinator.py:21-24` — three extra fields on the LangGraph state:

```python
class EmailAgentState(AgentState):
    current_draft = Dict[str, Any] | None
    research_summary = str | None
    draft_feedback = str | None
```

- `current_draft` is written by the `call_mailing_agent` tool (the LLM-produced JSON) and overwritten on edit/approve.
- `draft_feedback` is set on reject; `call_mailing_agent` injects it into the next mailing-agent prompt.
- `research_summary` is written by `call_web_search` and passed to the mailing agent.

The sub-agents (`mailing_agent`, `web_search_agent`, `mail_reader_agent`) are invoked with **user-scoped** `thread_id`s (`mailing_{user_id}`, `search_{user_id}`, `mail_reader_{user_id}`) — `coordinator.py:130-134`, `152-157`, `203-207`. Only the coordinator uses the conversation's `thread_id`. This means the coordinator's checkpoint is what survives a HITL pause.

## 4. The `send_email` tool — the actual boundary

`backend/app/agents/tools/draft_tools.py:66-172` — this is what `HumanInTheLoopMiddleware` interrupts on. It does **not** send by itself: it expects that a `pending_approval` row already exists.

Key flow inside the tool:

1. `_pending_draft(runtime)` (`draft_tools.py:23-36`) — find the latest `EmailDraft` where `user_id` matches, `conversation_id` matches, and `status == "pending_approval"`.
2. `_normalize_optional_identifier` (`draft_tools.py:14-20`) — guard against the LLM passing `"null"`/`"none"`/`""` for `in_reply_to` / `thread_id`.
3. Call `runtime.context.gmail_service.send_email(...)` (the real Gmail API call in `services/gmail_service.py:66-91`).
4. On success: `_mark_draft_sent` flips the row to `status="sent"`, records `gmail_sent_id`, and stores any user edits that diverged from the LLM draft.
5. On failure: `_mark_draft_send_failed` flips the row to `status="send_failed"`, creates an `error` notification, and broadcasts a `type: "error"` SSE event.
6. Always broadcasts an `email_sent` SSE event with `gmail_message_id`, then returns a `Command(update={current_draft: None, draft_feedback: None, ...})` to clear the resume state.

The tool's docstring says it all: "Send the final email after human approval." It is the **only** place Gmail `messages.send` is called.

## 5. Persisting the interrupt — `hitl_service`

`backend/app/services/hitl_service.py:54-105` — the bridge between LangGraph's `__interrupt__` payload and the database.

```python
async def persist_hitl_interrupts(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    interrupt_value: dict[str, Any],
    notification_service: NotificationService,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for request in _send_email_requests(interrupt_value):
        args = request["args"]
        description = request["description"]
        draft = EmailDraft(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            conversation_id=uuid.UUID(conversation_id),
            draft_type=str(args.get("draft_type") or "fresh"),
            to_address=str(args.get("to") or "").strip(),
            subject=str(args.get("subject") or "").strip(),
            body=str(args.get("body") or "").strip(),
            in_reply_to=str(args.get("in_reply_to")) if args.get("in_reply_to") else None,
            thread_id=str(args.get("thread_id")) if args.get("thread_id") else None,
            status="pending_approval",
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        draft_payload = serialize_draft_for_frontend(draft, description=description)
        event = {
            "type": "approval_required",
            "draft_id": str(draft.id),
            "conversation_id": conversation_id,
            "draft": draft_payload,
            "description": description,
        }
        await notification_service.create_notification(
            db, user_id,
            type="approval_required", title="Approval Required",
            body="A draft is waiting for your approval.",
            metadata={"draft_id": ..., "conversation_id": ..., "draft": ..., "description": ...},
        )
        await notification_service.broadcast(user_id, event)
        events.append(event)
    return events
```

It is called from two places:

- `backend/app/routers/chat.py:745-751` — when the chat stream sees an `__interrupt__` carrying a `send_email` request.
- `backend/app/routers/approve.py:181-187` — when the resume run after approval produces *another* interrupt (e.g. the LLM edited the draft and re-called `send_email`).

`is_hitl_interrupt(interrupt_value)` (`hitl_service.py:37-38`) checks that the interrupt payload is a dict containing at least one `send_email` `action_request`. `_send_email_requests` (`hitl_service.py:12-34`) extracts the `{args, description}` tuples for every such request.

`serialize_draft_for_frontend` (`hitl_service.py:41-51`) projects an `EmailDraft` row to the wire shape — preferring any user `edited_*` values over the original `to_address`/`subject`/`body`.

## 6. The `EmailDraft` model

`backend/app/models/email_draft.py:13-50` — the source of truth between LLM and Gmail:

```python
class EmailDraft(Base):
    __tablename__ = "email_drafts"
    __table_args__ = (
        CheckConstraint("draft_type IN ('reply', 'fresh')", name="ck_email_drafts_draft_type"),
        CheckConstraint(
            "status IN ('pending_approval', 'approved', 'rejected', 'sent', 'send_failed')",
            name="ck_email_drafts_status",
        ),
    )
```

Status transitions drive the whole UI:

| Status             | Set by                                                        |
| ------------------ | ------------------------------------------------------------- |
| `pending_approval` | `persist_hitl_interrupts` when interrupt lands (`hitl_service.py:76`) |
| `rejected`         | `approve.py:127` when user rejects                            |
| `sent`             | `_mark_draft_sent` in `draft_tools.py:49` after Gmail success |
| `send_failed`      | `_mark_draft_send_failed` in `draft_tools.py:61`              |

(`approved` is a valid enum value but is not actually written by the current code path — approve/edit both flow through `send_email` which flips to `sent`.)

`edited_to` / `edited_subject` / `edited_body` capture user edits without overwriting the LLM's original — they are only set when the user actually changed the field, which is what `serialize_draft_for_frontend` and the `edit` decision path read.

## 7. The chat stream — surfacing the interrupt over SSE

`backend/app/routers/chat.py:590-777` — `stream_chat_message` is an SSE endpoint. Two important HITL hooks:

### 7.1 Block on existing pending draft (`chat.py:84-105`)

```python
async def _pending_approval_blocked_stream_events(
    db: AsyncSession, *, user_id, conversation_id, turn_id,
) -> list[str] | None:
    pending_draft = await _get_pending_approval_draft(db, user_id=user_id, conversation_id=conversation_id)
    if pending_draft is None:
        return None
    return [
        _sse(event) for event in _blocked_approval_events(
            draft_id=str(pending_draft.id), conversation_id=conversation_id, turn_id=turn_id,
        )
    ]
```

If the user tries to send a new message in a conversation that still has a `pending_approval` row, the stream short-circuits with `approval_blocked` + `done` events. The user must resolve the existing draft first.

### 7.2 Capture the interrupt (`chat.py:741-764`)

```python
interrupts = updates.get("__interrupt__", ())
for interrupt in interrupts:
    interrupt_value = getattr(interrupt, "value", interrupt)
    if is_hitl_interrupt(interrupt_value):
        events = await persist_hitl_interrupts(
            db, user_id=..., conversation_id=payload.conversation_id,
            interrupt_value=interrupt_value, notification_service=notification_service,
        )
        for event in events:
            yield _sse({**event, "turn_id": turn_id})
```

`persist_hitl_interrupts` both persists the row and broadcasts the SSE event for other tabs; the chat stream also re-yields the same event with `turn_id` so the active tab can open the modal even if the global EventSource is reconnecting.

Also note the `draft_artifact` path (`chat.py:723-740`) — when `call_mailing_agent` finishes drafting, the chat stream yields a `draft_artifact` event so the frontend can render the `draft_email` block in real time *before* the interrupt happens. This is what makes the in-chat "draft card" appear as the coordinator writes.

## 8. The approve router — POST /approve/{draft_id}

`backend/app/routers/approve.py` — the user-facing decision endpoint.

### 8.1 Schema

`backend/app/schemas/approval.py`:

```python
class ApprovalRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_to: str | None = None
    edited_subject: str | None = None
    edited_body: str | None = None
    feedback: str | None = None

class ApprovalResponse(BaseModel):
    success: bool
    status: str
    gmail_message_id: str | None = None
```

### 8.2 GET /approve/pending

`approve.py:84-97` — used by the frontend to recover from dropped SSE events; returns all `pending_approval` drafts for the current user, newest first.

### 8.3 POST /approve/{draft_id}

`approve.py:100-198` — the full lifecycle:

1. Load + auth the draft (`approve.py:108-114`).
2. **Persist edits on `edit`/`approve`** (`approve.py:116-125`): write `edited_to` / `edited_subject` / `edited_body` only when the user actually changed them (keeps the columns null when unchanged so `serialize_draft_for_frontend` falls back to the originals).
3. **Mark rejected** (`approve.py:126-150`): flip to `rejected`, create an `email_rejected` notification, broadcast a `type: "email_rejected"` SSE event. The run isn't resumed here; the LLM picks it back up on the user's next chat message (because the coordinator is in a paused state and the next message will resume it via `draft_feedback`).
4. **Build the middleware decision** — `_build_decision(draft, payload)` (`approve.py:40-70`):
   - `reject` → `{type: "reject", message: feedback or "Please revise the draft based on my feedback."}`
   - `edit` or any of the three edited fields diverged from the LLM's original → `{type: "edit", edited_action: {name: "send_email", args: {...edited values...}}}`
   - plain `approve` with no edits → `{type: "approve"}`
5. **Resume the coordinator** (`approve.py:161-187`):
   ```python
   coordinator = get_coordinator_agent(request.app.state.checkpointer)
   async for part in coordinator.astream(
       Command(
           resume={"decisions": [_build_decision(draft, payload)]},
           update={
               "current_draft": _current_draft_payload(draft, payload),
               "draft_feedback": payload.feedback if payload.action == "reject" else None,
           },
       ),
       config={"configurable": {"thread_id": str(draft.conversation_id)}},
       context=context,
       stream_mode=["updates"],
       version="v2",
   ):
       ...
       if is_hitl_interrupt(interrupt_value):
           await persist_hitl_interrupts(...)
   ```
   The `Command(resume=...)` is the magic: LangGraph's `HumanInTheLoopMiddleware` consumes the `decisions` list, unpauses the interrupted tool, and the tool call finally executes — which is when `send_email` actually fires and writes the `sent` row + broadcasts `email_sent`.
6. **Return the final status** (`approve.py:189-197`): `db.refresh(draft)` to read back the `status` and `gmail_sent_id` written by `_mark_draft_sent` and return `ApprovalResponse`.

`_current_draft_payload` (`approve.py:73-81`) seeds the next `state.current_draft` so the coordinator sees the (possibly edited) values and downstream nodes don't re-call the mailing agent.

## 9. Notification backbone — SSE for cross-tab delivery

`backend/app/services/notification_service.py` — a single in-process `NotificationService` with per-user `asyncio.Queue` lists.

- `subscribe(user_id)` adds a queue; `unsubscribe(user_id, queue)` removes it.
- `broadcast(user_id, event)` puts the event on every queue subscribed for that user.
- `create_notification(...)` writes a `Notification` row to Postgres (used for the notifications dropdown/inbox).

`backend/app/routers/notifications.py:34-59` — `GET /api/notifications/stream` is a long-lived SSE endpoint that pops events from the user's queue (with a 30s ping timeout to keep proxies happy) and serializes them as `data: {...}\n\n`. This is the channel that delivers `approval_required`, `email_sent`, `email_rejected`, and `error` events to the dashboard.

The same events are also yielded on the **request-scoped** chat SSE stream (`chat.py:759-764`). The duplication is deliberate: the chat stream is the authoritative path for the active tab, while the notifications stream is best-effort and covers other tabs/devices.

## 10. Frontend — Zustand store, modal, SSE hook

### 10.1 `useApprovalStore`

`frontend/stores/approvalStore.ts:22-52` — Zustand store holding the modal state:

```typescript
{
  isOpen, draft, originalDraft, feedback,
  pendingDraftIds: string[],
  open(draft), close(),
  markPending(id), clearPending(id), isPending(id),
  updateDraft(patch), setFeedback(text)
}
```

- `open` snapshots `originalDraft` so the modal can later diff to detect edits.
- `markPending` / `clearPending` track drafts whose decision is in flight (used by the SSE hook to suppress duplicate toasts on `email_sent` for the same draft id).

### 10.2 SSE hook

`frontend/hooks/useSSE.ts:14-114` — opens an `EventSource` to `/api/notifications/stream` with `withCredentials: true` (cookie-based auth). On each message:

- `approval_required` → call `useApprovalStore.open(...)`, refresh history if it's the active conversation.
- `email_sent` / `email_rejected` / `error` → toast, `clearPending(draft_id)`, refresh history.
- Reconnects on `onerror` with exponential backoff capped at 10s.

### 10.3 Chat stream handling

`frontend/hooks/useChat.ts` parses the request-scoped SSE stream and reacts to HITL events:

- `approval_required` with `payload.draft` → `useApprovalStore.open(...)` + flip the assistant message to `status: "waiting_approval"` with a `Waiting for approval` status block. The `payload.draft` carries the full body so the modal can open even if the global EventSource is dead.
- `approval_blocked` → toast + status update (informs the user a draft is already pending).
- `approval_pending` → same status update as above (sent by the SSE hook path).
- `turn_completed` / `done` → reload history; if the modal isn't open after a blocked turn, `openPendingDraftIfNeeded` queries `GET /approve/pending` as a recovery path.
- `draft_artifact` → update the in-chat `draft_email` block live as the mailing agent finishes.
- `email_sent` is not consumed in the chat stream (the SSE hook handles it), but the reloadConversation call after the POST in `ApprovalModal` is the source-of-truth UI update for the just-approved draft.

### 10.4 The approval modal

`frontend/components/approval/ApprovalModal.tsx:21-132` — the user-facing decision UI:

- Renders an editable `Input` for `to`, `Input` for `subject`, and two `Textarea`s for `body` and `feedback` (for reject).
- The "Approve" button submits with `action: action === "approve" ? (isEdited ? "edit" : "approve") : "reject"` — so an "Approve" click that the user edited first automatically becomes an `edit` decision server-side. The diff is computed against `originalDraft`.
- On submit: `markPending(draft.id)`, `close()` (optimistically), then `api.post('/approve/{id}', ...)`. On error, `clearPending` + reopen the modal with the same content. On success, `reloadConversation(conversation_id)` to flip the in-chat card to `sent` immediately (the SSE `email_sent` event would also do it, but the EventSource can be reconnecting and the broadcast is in-memory).
- Reject requires non-empty `feedback` (UI-side guard at `ApprovalModal.tsx:31-37`).

## 11. End-to-end flow, step by step

1. **User sends a chat message** → `POST /api/chat/message` (SSE response). The chat router yields `turn_started`, streams tokens, `action_started`/`action_completed` for sub-agent tools, and finally `draft_artifact` (live `draft_email` block) and `research_report` if research was used.
2. **Coordinator decides to send** → calls `send_email` tool. `HumanInTheLoopMiddleware` raises an interrupt, the run is checkpointed and paused.
3. **Chat router sees `__interrupt__`** → `is_hitl_interrupt(interrupt_value)` is true → `persist_hitl_interrupts()` inserts `EmailDraft(status="pending_approval")`, creates an `approval_required` notification row, broadcasts the SSE event, and yields the same event on the chat stream.
4. **Frontend** receives the `approval_required` SSE on the chat stream → `useChat` calls `useApprovalStore.open(...)` and flips the assistant message to `waiting_approval`. The notification stream independently triggers a toast in other tabs.
5. **User opens the modal, edits/keeps, clicks Approve (or Request Rewrite)** → `POST /api/approve/{draft_id}` with `ApprovalRequest`.
6. **Approve router** persists edits, builds the middleware decision, and resumes the coordinator via `Command(resume={"decisions": [...]})`. The same LangGraph checkpointed run picks up where it left off; the middleware unpauses the `send_email` tool call; the tool reads the `pending_approval` row, calls Gmail, and writes the `sent` row + `email_sent` SSE event.
7. **Frontend** gets `email_sent` on the notification stream (toast) and re-renders the chat history (draft card → `sent`).
8. **If user rejects** → `EmailDraft.status = "rejected"`, an `email_rejected` notification is broadcast, the coordinator is **not** resumed from `/approve/{id}`. The next user chat message in that conversation resumes the run (carrying the `draft_feedback`), the coordinator routes back to `call_mailing_agent` (with the feedback), and the loop continues until either the user accepts or the conversation is abandoned.

## 12. Key invariants and design notes

- **Single source of truth for "is there a draft to review?"** is the `email_drafts` table filtered by `status='pending_approval'`. The chat router blocks new messages on it (`_pending_approval_blocked_stream_events`), the approve router validates it (`draft.status != "pending_approval"` → 409), and the `openPendingDraftIfNeeded` recovery in `useChat` queries it directly. The SSE path is convenience; the DB row is the contract.
- **The `send_email` tool assumes a `pending_approval` row already exists.** It looks it up by `(user_id, conversation_id, status=pending_approval)` and reads the (possibly user-edited) values from it. The middleware decision is just the gate; the tool reads the user's edits from Postgres.
- **Edited fields are stored separately** (`edited_to`, `edited_subject`, `edited_body`) so the LLM's original is preserved for audit and so the next rewrite can diff against the LLM, not the user's edits.
- **Sub-agents have user-scoped thread IDs** while the coordinator uses the conversation's thread ID. This is what lets the coordinator checkpoint survive across a HITL pause even though the sub-agents are stateless from the coordinator's perspective.
- **Two SSE paths** (request-scoped + long-lived notifications) are deliberately duplicated: the chat stream is the authoritative channel for the active tab, the notifications stream covers other tabs and the toast UX. Both `persist_hitl_interrupts` and the chat stream handler call the same `notification_service.broadcast` + yield, so events aren't lost when the chat request ends.
- **The approve router doesn't mark the draft as approved.** It only marks `rejected` (because that path doesn't immediately call `send_email`); the `edit`/`approve` paths let the tool itself flip the row to `sent`. The `ApprovalResponse.status` is whatever the tool left behind.
- **Rejection doesn't resume the run.** The coordinator stays paused; the user must send another message. That message becomes the resume payload (LangGraph's `Command(resume=...)` is implicit in `coordinator.astream({"messages": [HumanMessage(...)]}, config={"configurable": {"thread_id": conversation_id}})` — the run is at the interrupt point and the new human message is interpreted as the resume input, carrying `draft_feedback` along via `state` updates triggered by the next middleware decision).

## 13. File index

| File | Role |
| --- | --- |
| `backend/app/agents/coordinator.py` | Coordinator agent, `HumanInTheLoopMiddleware` config, `EmailAgentState` |
| `backend/app/agents/tools/draft_tools.py` | `send_email` tool — the actual send boundary |
| `backend/app/services/gmail_service.py` | Gmail API wrapper, `messages.send` |
| `backend/app/services/hitl_service.py` | `is_hitl_interrupt`, `persist_hitl_interrupts`, `serialize_draft_for_frontend` |
| `backend/app/services/notification_service.py` | In-process per-user event bus + notification row writer |
| `backend/app/models/email_draft.py` | `EmailDraft` model + status enum |
| `backend/app/routers/chat.py` | Chat SSE stream — yields `approval_blocked` and `approval_required` events |
| `backend/app/routers/approve.py` | `GET /approve/pending`, `POST /approve/{draft_id}` |
| `backend/app/routers/notifications.py` | Long-lived `/api/notifications/stream` SSE |
| `backend/app/schemas/approval.py` | `ApprovalRequest`, `ApprovalResponse` |
| `backend/app/agents/context.py` | `AgentContext` (db, gmail, notification service) shared with tools |
| `frontend/stores/approvalStore.ts` | Zustand store: modal state, pending draft ids |
| `frontend/components/approval/ApprovalModal.tsx` | Modal UI, submit (approve/edit/reject) |
| `frontend/hooks/useSSE.ts` | Global `EventSource` to `/notifications/stream` |
| `frontend/hooks/useChat.ts` | Chat SSE parser, `openPendingDraftIfNeeded` recovery |
| `frontend/types/index.ts` | `SSEEvent`, `ApprovalDraftPayload`, `DraftEmailBlock` types |
