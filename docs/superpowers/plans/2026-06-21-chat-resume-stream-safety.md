# Chat Resume and Streaming Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent normal chat from resuming pending email approvals and keep live chat streaming free of internal tool JSON.

**Architecture:** Add a backend pending-approval guard before coordinator invocation, then restrict chat SSE to safe progress/prose events. Update frontend stream handling for `approval_blocked`, `action_started`, and `action_completed`, relying on `/chat/history` reloads for final structured content.

**Tech Stack:** FastAPI, SQLAlchemy async, LangChain/LangGraph, stdlib `unittest`, Next.js 14, React 18, Zustand, TypeScript.

---

## File Structure

- Modify `backend/app/routers/chat.py`: add pending draft helper, blocked SSE branch, safe stream filtering helpers, and action events.
- Create `backend/tests/test_chat_stream_contract.py`: pure/unit tests for pending approval guard query behavior and stream filtering helpers.
- Modify `frontend/types/index.ts`: add `approval_blocked` to `SSEEvent.type`.
- Modify `frontend/hooks/useChat.ts`: render action events, block normal chat on pending approval, and avoid rendering internal stream payloads as markdown.
- Use existing verification commands:
  - Backend: `.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract`
  - Backend compile: `.\venv\Scripts\python.exe -m compileall app`
  - Frontend: `npm run build`

---

## Task 1: Backend Pending Approval Guard

**Files:**
- Modify: `backend/app/routers/chat.py`
- Create: `backend/tests/test_chat_stream_contract.py`

- [ ] **Step 1: Write failing tests for pending approval lookup and blocked event shape**

Create `backend/tests/test_chat_stream_contract.py` with this initial content:

```python
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from app.models.email_draft import EmailDraft
from app.routers import chat


class PendingApprovalGuardTests(IsolatedAsyncioTestCase):
    async def test_get_pending_approval_draft_returns_first_matching_draft(self):
        draft = EmailDraft(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            draft_type="fresh",
            to_address="recipient@example.com",
            subject="Subject",
            body="Body",
            status="pending_approval",
        )
        scalars_result = SimpleNamespace(first=lambda: draft)
        db = SimpleNamespace(scalars=AsyncMock(return_value=scalars_result))

        result = await chat._get_pending_approval_draft(
            db,
            user_id=draft.user_id,
            conversation_id=str(draft.conversation_id),
        )

        self.assertIs(result, draft)
        db.scalars.assert_awaited_once()

    async def test_get_pending_approval_draft_returns_none_when_no_match(self):
        scalars_result = SimpleNamespace(first=lambda: None)
        db = SimpleNamespace(scalars=AsyncMock(return_value=scalars_result))

        result = await chat._get_pending_approval_draft(
            db,
            user_id=uuid.uuid4(),
            conversation_id=str(uuid.uuid4()),
        )

        self.assertIsNone(result)
        db.scalars.assert_awaited_once()


class ApprovalBlockedEventTests(TestCase):
    def test_approval_blocked_event_has_user_safe_shape(self):
        draft_id = uuid.uuid4()
        conversation_id = uuid.uuid4()

        event = chat._approval_blocked_event(
            draft_id=str(draft_id),
            conversation_id=str(conversation_id),
            turn_id="turn-123",
        )

        self.assertEqual(event["type"], "approval_blocked")
        self.assertEqual(event["draft_id"], str(draft_id))
        self.assertEqual(event["conversation_id"], str(conversation_id))
        self.assertEqual(event["turn_id"], "turn-123")
        self.assertIn("pending draft", event["content"].lower())
        self.assertNotIn("{", event["content"])
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract
```

Expected: fail with `AttributeError` for missing `chat._get_pending_approval_draft` and/or `chat._approval_blocked_event`.

- [ ] **Step 3: Implement minimal backend guard helpers**

In `backend/app/routers/chat.py`, add this helper after `_serialize_history`:

```python
async def _get_pending_approval_draft(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: str,
) -> EmailDraft | None:
    result = await db.scalars(
        select(EmailDraft)
        .where(
            EmailDraft.user_id == user_id,
            EmailDraft.conversation_id == uuid.UUID(conversation_id),
            EmailDraft.status == "pending_approval",
        )
        .order_by(desc(EmailDraft.created_at))
        .limit(1)
    )
    return result.first()
```

Add this helper after `_sse`:

```python
def _approval_blocked_event(*, draft_id: str, conversation_id: str, turn_id: str) -> dict[str, Any]:
    return {
        "type": "approval_blocked",
        "draft_id": draft_id,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "content": "Review the pending draft before sending another message in this conversation.",
    }
```

- [ ] **Step 4: Run tests to verify green**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract
```

Expected: all tests in `tests.test_chat_stream_contract` pass.

- [ ] **Step 5: Wire guard into `/api/chat/message`**

In `backend/app/routers/chat.py`, inside `stream_chat_message` after conversation title/timestamp commit and before `event_stream()` is defined, add:

```python
    pending_draft = await _get_pending_approval_draft(
        db,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
    )
```

Inside `event_stream()`, immediately after yielding `turn_started`, add:

```python
            if pending_draft is not None:
                yield _sse(
                    _approval_blocked_event(
                        draft_id=str(pending_draft.id),
                        conversation_id=payload.conversation_id,
                        turn_id=turn_id,
                    )
                )
                yield _sse({"type": "done", "turn_id": turn_id})
                return
```

Keep this branch before `get_valid_access_token(...)`, `GmailService(...)`, and `get_coordinator_agent(...)`.

- [ ] **Step 6: Run backend test and compile**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract
.\venv\Scripts\python.exe -m compileall app
```

Expected: tests pass and compile exits `0`.

- [ ] **Step 7: Commit Task 1**

Run:

```powershell
git add backend/app/routers/chat.py backend/tests/test_chat_stream_contract.py
git commit -m "fix: block chat when draft approval is pending"
```

---

## Task 2: Backend Safe Stream Filtering

**Files:**
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/tests/test_chat_stream_contract.py`

- [ ] **Step 1: Add failing tests for safe token filtering and action events**

Append these tests to `backend/tests/test_chat_stream_contract.py`:

```python
class StreamFilteringTests(TestCase):
    def test_tool_call_chunks_do_not_emit_tokens(self):
        chunk = SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "name": "call_web_search",
                    "args": {"topic": "AI trends"},
                }
            ],
        )

        self.assertIsNone(chat._safe_token_content(chunk))

    def test_json_payload_chunks_do_not_emit_tokens(self):
        chunk = SimpleNamespace(
            content='{"query":"AI trends","results":[{"url":"https://example.com"}]}',
            tool_calls=[],
        )

        self.assertIsNone(chat._safe_token_content(chunk))

    def test_plain_assistant_text_can_emit_tokens(self):
        chunk = SimpleNamespace(content="Here is a concise answer.", tool_calls=[])

        self.assertEqual(chat._safe_token_content(chunk), "Here is a concise answer.")

    def test_action_event_for_known_tool_update(self):
        event = chat._action_started_event("call_web_search", turn_id="turn-123")

        self.assertEqual(event["type"], "action_started")
        self.assertEqual(event["tool"], "call_web_search")
        self.assertEqual(event["label"], "Research completed")
        self.assertEqual(event["turn_id"], "turn-123")

    def test_action_completed_event_for_known_tool_update(self):
        event = chat._action_completed_event("call_web_search", turn_id="turn-123")

        self.assertEqual(event["type"], "action_completed")
        self.assertEqual(event["tool"], "call_web_search")
        self.assertEqual(event["label"], "Research completed")
        self.assertEqual(event["turn_id"], "turn-123")

    def test_tool_call_names_extracts_dict_tool_calls(self):
        chunk = SimpleNamespace(
            content="",
            tool_calls=[
                {"name": "call_web_search", "args": {"topic": "AI trends"}},
                {"name": "call_mailing_agent", "args": {"task": "Draft"}},
            ],
        )

        self.assertEqual(
            chat._tool_call_names(chunk),
            ["call_web_search", "call_mailing_agent"],
        )
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract
```

Expected: fail with `AttributeError` for missing `_safe_token_content` and `_action_completed_event`.

- [ ] **Step 3: Implement safe stream helpers**

In `backend/app/routers/chat.py`, add after `_label_for_tool`:

```python
def _looks_like_json_payload(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    if not (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


def _safe_token_content(chunk: Any) -> str | None:
    if getattr(chunk, "tool_calls", None):
        return None
    content = _message_text(getattr(chunk, "content", "")).strip()
    if not content:
        return None
    if _looks_like_json_payload(content):
        return None
    return content


def _tool_call_names(chunk: Any) -> list[str]:
    names: list[str] = []
    for tool_call in getattr(chunk, "tool_calls", None) or []:
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
        else:
            name = getattr(tool_call, "name", None)
        if name:
            names.append(str(name))
    return names


def _action_started_event(tool_name: str, *, turn_id: str) -> dict[str, Any]:
    return {
        "type": "action_started",
        "tool": tool_name,
        "label": _label_for_tool(tool_name),
        "turn_id": turn_id,
    }


def _action_completed_event(tool_name: str, *, turn_id: str) -> dict[str, Any]:
    return {
        "type": "action_completed",
        "tool": tool_name,
        "label": _label_for_tool(tool_name),
        "turn_id": turn_id,
    }
```

- [ ] **Step 4: Update stream loop to use action-start events and safe token helper**

In `backend/app/routers/chat.py`, replace:

```python
                    text = _message_text(chunk.content)
                    if text:
                        yield _sse({"type": "token", "content": text, "turn_id": turn_id})
```

with:

```python
                    tool_call_names = _tool_call_names(chunk)
                    if tool_call_names:
                        for tool_name in tool_call_names:
                            yield _sse(_action_started_event(tool_name, turn_id=turn_id))
                        continue
                    text = _safe_token_content(chunk)
                    if text:
                        yield _sse({"type": "token", "content": text, "turn_id": turn_id})
```

- [ ] **Step 5: Emit action completion events from updates**

In the `elif part["type"] == "updates":` block, before interrupt handling, add:

```python
                    for node_update in updates.values():
                        if not isinstance(node_update, dict):
                            continue
                        for message in node_update.get("messages", []):
                            if isinstance(message, ToolMessage) and message.name:
                                yield _sse(_action_completed_event(message.name, turn_id=turn_id))
```

Do not emit tool message content in these events.

- [ ] **Step 6: Run backend tests and compile**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract
.\venv\Scripts\python.exe -m compileall app
```

Expected: tests pass and compile exits `0`.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add backend/app/routers/chat.py backend/tests/test_chat_stream_contract.py
git commit -m "fix: filter internal chat stream payloads"
```

---

## Task 3: Frontend Stream Event Handling

**Files:**
- Modify: `frontend/types/index.ts`
- Modify: `frontend/hooks/useChat.ts`

- [ ] **Step 1: Add frontend event type**

In `frontend/types/index.ts`, update `SSEEvent.type` to include:

```typescript
    | "approval_blocked"
```

Add optional fields used by action events:

```typescript
  tool?: string;
  label?: string;
```

- [ ] **Step 2: Add helper for action blocks in `useChat`**

In `frontend/hooks/useChat.ts`, after `buildStatusBlock`, add:

```typescript
function buildToolActionBlock(
  label: string,
  state: "running" | "complete" | "waiting" | "error",
  detail?: string
): ChatContentBlock {
  return { type: "tool_action", label, state, detail };
}
```

- [ ] **Step 3: Handle action events**

In `frontend/hooks/useChat.ts`, inside the SSE payload branch after `token` handling and before `approval_pending`, add:

```typescript
          } else if (payload.type === "action_started") {
            updateMessage(assistantId, {
              status: "streaming",
              content: assistantContent,
              content_blocks: [
                buildStatusBlock("Working", "pending", "The agent is preparing the response."),
                buildToolActionBlock(payload.label ?? "Working", "running"),
                ...(assistantContent ? [buildMarkdownBlock(assistantContent)] : [])
              ]
            });
          } else if (payload.type === "action_completed") {
            updateMessage(assistantId, {
              status: "streaming",
              content: assistantContent,
              content_blocks: [
                buildStatusBlock("Working", "pending", "The agent is preparing the response."),
                buildToolActionBlock(payload.label ?? "Step completed", "complete"),
                ...(assistantContent ? [buildMarkdownBlock(assistantContent)] : [])
              ]
            });
```

- [ ] **Step 4: Handle approval blocked**

In `frontend/hooks/useChat.ts`, inside the SSE payload branch before `approval_pending`, add:

```typescript
          } else if (payload.type === "approval_blocked") {
            updateMessage(assistantId, {
              status: "waiting_approval",
              content: payload.content ?? "",
              content_blocks: [
                buildStatusBlock(
                  "Waiting for approval",
                  "pending",
                  payload.content ?? "Review the pending draft before continuing."
                )
              ],
              metadata: {
                draft_id: payload.draft_id,
                is_waiting_approval: true
              }
            });
            toast({
              title: "Approval Required",
              description: payload.content ?? "Review the pending draft before continuing."
            });
            await reloadConversation(conversationId);
```

- [ ] **Step 5: Verify frontend types/build**

Run:

```powershell
cd frontend
npm run build
```

Expected: Next.js build succeeds with no TypeScript errors.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add frontend/types/index.ts frontend/hooks/useChat.ts
git commit -m "fix: handle safe chat stream events"
```

---

## Task 4: End-to-End Verification and Cleanup

**Files:**
- Verify: `backend/app/routers/chat.py`
- Verify: `frontend/hooks/useChat.ts`
- Verify: browser at `http://localhost:3000/dashboard`

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_chat_stream_contract
```

Expected: all tests pass.

- [ ] **Step 2: Run existing stable backend tests**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_auth_service tests.test_email_parser tests.test_gmail_service tests.test_notification_service tests.test_llm
```

Expected: all tests pass.

- [ ] **Step 3: Run backend compile**

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m compileall app
```

Expected: exits `0`.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: exits `0`.

- [ ] **Step 5: Browser manual check for pending approval guard**

Use the active browser at `http://localhost:3000/dashboard`.

Manual path:

1. Open a conversation with a visible pending approval draft.
2. Send a normal chat message.
3. Confirm the UI shows `Waiting for approval`.
4. Confirm no `Email Sent` toast appears.
5. Confirm no raw JSON appears in the assistant message.

If there is no pending draft available locally, use API/database setup from the implementation worker to create one, then repeat the same browser path.

- [ ] **Step 6: Browser manual check for clean streaming**

Manual path:

1. Start a new conversation.
2. Send a read/research/draft prompt.
3. Confirm live stream shows status/action blocks and safe prose only.
4. Confirm final history reload shows structured research/draft blocks.
5. Confirm no raw `{"query": ...}`, `results`, `tool_outputs`, or provider payload object is rendered as markdown.

- [ ] **Step 7: Commit verification notes only if code/docs changed**

If verification requires any code fix, commit that fix:

```powershell
git add <changed-files>
git commit -m "fix: complete chat stream safety verification"
```

If no files changed, do not create an empty commit.

---

## Self-Review Checklist

- Spec goal “normal chat must never resume pending approval” maps to Task 1.
- Spec goal “only approval endpoint resumes HITL” is preserved by Task 1 guard and verified by blocked branch before coordinator invocation.
- Spec goal “streaming must not show tool JSON/internal payloads” maps to Task 2 and Task 3.
- Spec goal “frontend handles approval_blocked/action events” maps to Task 3.
- Spec goal “final structured history remains source of truth” maps to Task 3 reload behavior and Task 4 browser checks.
- No placeholders remain in task steps.
- All commands use repo-approved `unittest`, `compileall`, and `npm run build`.
