# Tool Breakdown — Autonomous Email Agent Backend

> **Scope.** This document explains every LangChain tool the agent exposes to the LLM, what each tool does, how it is implemented, and how the pieces wire together at runtime. The user asked specifically about "tool calls"; in this codebase that term maps cleanly to two distinct things, both covered below:
>
> 1. **Tool-calls the LLM makes** — the `@tool`-decorated functions in `backend/app/agents/tools/` that the LangChain runtime binds to the model. These are the *agent tools*.
> 2. **Tool-calls the backend invokes when running the agent** — i.e. the LangChain `create_agent()` / LangGraph `Command` / `ToolRuntime` machinery. This is the *tool-call substrate* (not user-callable, but worth a section so the LLM-facing tools make sense).
>
> All file references are `path:line` against the on-disk source at the time of writing.

---

## 1. Mental model first

The backend builds a LangChain v1 **deep agent** (`create_agent` in `backend/app/agents/web_search_agent.py:37`, and a similar factory in the coordinator and mail-reader modules). The agent is a graph: nodes are LLM calls or tool calls; edges are control flow; state is a checkpointed message thread.

Tools are the agent's *only* way to affect the world outside its own LLM context. Everything an LLM can do beyond generating tokens is a tool call. In this codebase there are three families:

| Family | File | Purpose | Sub-agent that owns it |
|---|---|---|---|
| Gmail read | `backend/app/agents/tools/gmail_tools.py` | Read inbox / threads / messages via `GmailService` | `mail_reader_agent` (per `agents/mail_reader_agent.py` — see blast radius) |
| Web search | `backend/app/agents/tools/search_tools.py` | Tavily-backed research | `web_search_agent` (`web_search_agent.py:33`) |
| Draft + send | `backend/app/agents/tools/draft_tools.py` | Persist / send emails, **HITL boundary** | coordinator (only `send_email` lives here, which is the approval-resume tool) |

There is no `__init__.py` re-export — the package is a directory marker; each consumer imports the tool symbol it needs directly (e.g. `from app.agents.tools.gmail_tools import get_recent_emails`).

The wiring glue is `AgentContext` (`backend/app/agents/context.py:13`): a `@dataclass` that holds `gmail_service`, `db_session`, `notification_service`, plus `user_id` / `conversation_id` (with `.user_uuid` / `.conversation_uuid` properties). LangChain v1's `ToolRuntime[AgentContext]` injects an instance of this dataclass into every tool call, so tools never close over globals.

---

## 2. The tool-call substrate (how `@tool` becomes a callable)

Before the per-tool breakdown, it helps to understand the substrate, because the same substrate is reused for all eight tools and the user asked for "implementation" details.

### 2.1 `@tool` decorator

`from langchain.tools import tool` (`gmail_tools.py:3`, `search_tools.py:6`, `draft_tools.py:6`).

The decorator introspects the function signature and docstring and builds a `BaseTool` (a `StructuredTool` for async functions). Concretely it does the following at import time:

- Reads parameter names and type hints → produces a JSON-Schema-style argument schema for the LLM.
- Reads the docstring → that becomes the tool's *description* the LLM sees. The descriptions here are intentionally short and imperative ("Fetch the user's most recent emails.", "Send the final email after human approval."). This is what the model uses to decide which tool to call.
- Wraps the callable in a coroutine-aware dispatcher. The function may be `def` (sync) or `async def`; `langchain` awaits async tools automatically.

### 2.2 `ToolRuntime[AgentContext]`

Defined in `langchain.tools`. Type-parameterized with the project-local `AgentContext` (`context.py:13`). At runtime, the LangChain agent runtime injects one argument that is *not* in the LLM-visible schema:

- `runtime.context` — the per-request `AgentContext` instance.
- `runtime.tool_call_id` — the OpenAI-style `tool_call_id` for the current invocation (used to attach the eventual `ToolMessage` correctly).
- `write/edit/Read` of state — for graph-state-bound tools (not used directly by these tools; state writes are done via the `Command` return).

`ToolRuntime` parameters are detected by name (`runtime`) and type-hint; they are stripped from the schema the model sees, so the LLM only ever sees the *real* arguments.

### 2.3 Returning control to the graph

A tool can return:

- A **plain value** (string or dict) — that becomes the content of the `ToolMessage` appended to the message history.
- A **`langgraph.types.Command(update=...)`** — used to write to graph state in addition to the `ToolMessage`. This is how `send_email` flips `current_draft = None` and `draft_feedback = None` after a successful send (`draft_tools.py:160-171`).

### 2.4 HITL interruption

The single most important *non-tool* fact about these tools: `send_email` is **registered as an interruptable tool** in the coordinator's middleware (`HumanInTheLoopMiddleware(interrupt_on={"send_email": ...})`, per the backend `AGENTS.md`). The flow is:

1. The coordinator reasons that a draft should be sent.
2. LangGraph calls the `send_email` tool. **Before** the tool body runs, middleware raises an `interrupt`, snapshotting the graph state to the Postgres checkpointer.
3. The backend's `persist_hitl_interrupts` (`backend/app/services/hitl_service.py:54`) inspects the interrupt value, **persists an `EmailDraft` row with `status="pending_approval"`**, and broadcasts an SSE `approval_required` event to the UI.
4. The user approves (or edits) in the dashboard. The backend's `/approve` router issues `Command(resume={"decisions": [{"type": "approve", "args": ...}]})`, which the middleware translates into *actually calling* `send_email` with the (possibly edited) args.
5. `send_email` then proceeds to Gmail and returns a `Command` that clears the draft state.

This is why `send_email` looks like it does a lot of bookkeeping (status flip, `edited_to`/`edited_subject`/`edited_body` diffs, notification fan-out): it is the resumption of an interrupted call, not a fresh call, and the backend is responsible for closing the loop end-to-end.

---

## 3. Tool-by-tool breakdown

Each entry follows the same structure: **What it does → Signature → Body walk → Side effects → Where it's called → Notes/edge cases**.

---

### 3.1 `get_recent_emails` — `backend/app/agents/tools/gmail_tools.py:54`

**What it does.** Returns the user's *N* most recent inbox messages, formatted as a numbered, multi-line block the LLM can quote in its reply.

**Signature.**
```python
@tool
async def get_recent_emails(
    count: int,
    runtime: ToolRuntime[AgentContext],
) -> str
```

**Body walk.**

1. `gmail = runtime.context.gmail_service` — pulls the per-request `GmailService` (which already holds the user's OAuth access token).
2. `count` is clamped to `[1, 20]` via `max(1, min(count, 20))`. This is a hard cap the LLM cannot exceed even if it asks for `count=1000`.
3. `gmail.list_messages(max_results=...)` — `GmailService.list_messages` (`backend/app/services/gmail_service.py:20`) does the Gmail API work in a thread (`asyncio.to_thread` at `gmail_service.py:40`) so the FastAPI event loop is not blocked. It returns a list of already-parsed dicts.
4. `_format_email_list(emails)` (`gmail_tools.py:8`) renders each message as:
   ```
   N. Subject: <subject or '(no subject)'>
      From: <from_name> <from_email>
      Date: <date>
      Message ID: <message_id>
      Thread ID: <thread_id>
      Snippet: <snippet>
   ```
   `Subject` is the only field with a `'(no subject)'` fallback because that is the only field where Gmail returns `None` consistently. From/date are trusted to be present (parser normalizes to string). Snippet falls back to whatever Gmail returned (never empty for inbox items).

**Side effects.** Read-only. No DB writes, no notifications, no Gmail writes.

**Callers.** Used by the `mail_reader_agent` sub-agent (per blast-radius map from the codegraph index). 1 caller; no direct coverage tests.

**Notes.**
- `_format_email_list` returns the string `"No matching emails were found."` for an empty list (`gmail_tools.py:10`) — a deliberate, deterministic empty-state message the LLM can reason about.
- The `count` clamp is the only "validation" the tool does; the Gmail API itself rejects larger `maxResults` past 500, but the LLM-facing tool caps at 20 to keep context windows manageable.

---

### 3.2 `search_emails_by_sender` — `gmail_tools.py:62`

**What it does.** Searches Gmail for messages whose `From:` header matches a sender.

**Signature.**
```python
@tool
async def search_emails_by_sender(
    sender: str,
    runtime: ToolRuntime[AgentContext],
) -> str
```

**Body walk.**

1. `gmail._build_query(sender=sender)` — composes a Gmail search string. `_build_query` lives on `GmailService` (`gmail_service.py:93`) and turns `sender="Alice"` into `from:Alice`. The query builder is shared across sender/topic/date/raw-query modes (see 3.3).
2. `gmail.list_messages(query=..., max_results=10)` — fixed ceiling of 10 results, *not* the caller's choice. This is a deliberate tool-design tradeoff: the model only gets a small, high-precision list, which forces a follow-up tool call (`get_full_email` or `get_email_thread`) if it needs more.
3. `_format_email_list` reuses the same formatter as `get_recent_emails`.

**Side effects.** Read-only.

**Callers.** 2 in `backend/app/agents/mail_reader_agent.py` (per codegraph). No tests.

**Notes.**
- The `_` prefix on `_build_query` is *just* a Python convention; the tool calls it across module boundaries. It is a stable, public-ish method on the service. There is no `protected` enforcement — `gmail_tools.py:65` and `gmail_tools.py:74` both reach into it directly.

---

### 3.3 `search_emails_by_topic` — `gmail_tools.py:71`

**What it does.** Searches Gmail for messages matching a topic or keyword.

**Signature.**
```python
@tool
async def search_emails_by_topic(
    topic: str,
    runtime: ToolRuntime[AgentContext],
) -> str
```

**Body walk.**

1. `gmail._build_query(topic=topic)` — produces `subject:(<topic>) OR (<topic>)` (see `gmail_service.py:103-104`). The OR-form is intentional: Gmail's full-text search hits subject, body, and headers, so the OR is a recall booster. Empty pieces are dropped by the trailing `if part` filter in `_build_query` (`gmail_service.py:112`).
2. Otherwise identical to 3.2 — same 10-result cap, same formatter, same read-only path.

**Side effects.** Read-only.

**Callers.** 1 in `mail_reader_agent.py` (per codegraph). No tests.

**Notes.**
- The default `days_back=None` means the topic query is *unbounded in time*. If a user asks "what did my team say about the launch last week?", the LLM must compose the `days_back` itself or follow up with `search_emails_by_sender` (no — that won't help) — actually, neither of the current tools lets the model pass `days_back`. This is a known gap: the `_build_query` capability is wider than what the LLM-facing tools expose.

---

### 3.4 `get_email_thread` — `gmail_tools.py:80`

**What it does.** Fetches a full Gmail thread (every message in the conversation) and formats it.

**Signature.**
```python
@tool
async def get_email_thread(
    thread_id: str,
    runtime: ToolRuntime[AgentContext],
) -> str
```

**Body walk.**

1. `gmail.get_thread(thread_id)` (`gmail_service.py:54`) — synchronous thread, returns a `parse_gmail_thread`-shaped dict containing `thread_id` and a `messages` list.
2. `_format_thread` (`gmail_tools.py:29`) prepends `Thread ID: ...\nMessages: <len>` and recycles `_format_email_list` on the messages. The `header + "\n\n" + rows` layout is what the LLM sees as a single tool result.

**Side effects.** Read-only.

**Callers.** 1 in `mail_reader_agent.py`. No tests.

**Notes.**
- There is no schema validation on `thread_id` — an invalid ID surfaces as a Gmail API 404 inside the thread, which the LLM will see as an exception text. There is no `try/except` here, unlike `send_email` (3.7).

---

### 3.5 `get_full_email` — `gmail_tools.py:88`

**What it does.** Fetches a single message by `message_id` and formats the full headers + body.

**Signature.**
```python
@tool
async def get_full_email(
    message_id: str,
    runtime: ToolRuntime[AgentContext],
) -> str
```

**Body walk.**

1. `gmail.get_message(message_id)` (`gmail_service.py:42`) — single-message GET, format=full.
2. `_format_full_email` (`gmail_tools.py:38`) produces:
   ```
   Subject: ...
   From: <name> <email>
   To: ...
   Date: ...
   Message ID: ...
   Thread ID: ...
   
   <body or snippet or '(empty body)'>
   ```
   The body fallback chain is `body → snippet → '(empty body)'` (`gmail_tools.py:48`).

**Side effects.** Read-only.

**Callers.** 1 in `mail_reader_agent.py`. No tests.

**Notes.**
- Note the asymmetric fallback vs. `_format_email_list`: for a list view, snippet is always shown; for a full view, body is preferred. The intent is the model can quote from a full message but should not invent content from a snippet.

---

### 3.6 `web_search` — `backend/app/agents/tools/search_tools.py:18`

**What it does.** Calls Tavily to retrieve web research for the LLM.

**Signature.**
```python
@tool
def web_search(query: str) -> dict[str, Any]
```

**Body walk.**

1. `get_tavily_client()` — `lru_cache`-decorated factory (`search_tools.py:12`). The `@lru_cache` is unbounded and process-wide, so the Tavily client is built once per process.
2. `.search(query=..., search_depth="advanced", topic="general", max_results=5, include_answer="advanced")` — these are the four Tavily options tuned for "I need a synthesized answer plus a few high-quality sources." `search_depth="advanced"` requests deeper content per result; `include_answer="advanced"` asks Tavily to synthesize an answer field in addition to source links.
3. The whole function is wrapped in `try/except`. On failure it returns `{"error": str(exc), "query": query}` rather than raising. This is intentional: a web-search failure should *not* kill the agent; the LLM should see "search failed" and fall back to its own knowledge. The system prompt of the `web_search_agent` (`backend/app/agents/web_search_agent.py:9-27`) instructs the model to handle that gracefully and still return a JSON object.

**Side effects.** Network call to Tavily. No DB writes, no Gmail calls.

**Callers.** 2 in `backend/app/agents/web_search_agent.py:33` (the agent factory binds it; per the blast-radius map, both call sites are in that module).

**Notes.**
- This is the *only* sync tool in the suite. It returns a `dict`, not a `str`, which is fine because LangChain's tool runtime JSON-serializes non-string return values into the `ToolMessage.content`. The web-search sub-agent is told to return JSON anyway (see `WEB_SEARCH_SYSTEM_PROMPT` at `web_search_agent.py:9-27`), so this is consistent.
- `get_tavily_client` reads `settings.TAVILY_API_KEY` from the central `app.config`. There is no fail-fast if the key is missing — the first call will fail at Tavily's HTTP layer and return the `{"error": ...}` dict.

---

### 3.7 `send_email` — `backend/app/agents/tools/draft_tools.py:67`

**What it does.** The HITL boundary. Sends a final email after human approval, records the result, and emits both a DB notification and an SSE event. The only tool in the project that performs a privileged side effect on behalf of the user.

**Signature.**
```python
@tool
async def send_email(
    to: str,
    subject: str,
    body: str,
    draft_type: str,
    in_reply_to: str | None,
    thread_id: str | None,
    runtime: ToolRuntime[AgentContext],
) -> str
```

> Note the return type annotation says `str` but in practice the function returns a `Command` (see below). The annotation is a benign lie — LangChain's tool runtime extracts the `ToolMessage` from the `Command` either way.

**Body walk.**

1. **Pre-normalization.** `tool_call_id = runtime.tool_call_id or "send_email"` — defensive default in case the runtime omits an ID. `_normalize_optional_identifier` (`draft_tools.py:14`) strips whitespace and treats `"null"`, `"none"`, `"nil"` (case-insensitive) as `None`. This catches the common LLM habit of emitting literal `null` strings instead of JSON null.
2. **Pending-draft lookup.** `_pending_draft(runtime)` (`draft_tools.py:23`) runs a SQL `SELECT ... WHERE user_id=? AND conversation_id=? AND status='pending_approval' ORDER BY created_at DESC LIMIT 1`. The point is: by the time `send_email` is called, `persist_hitl_interrupts` has already created the `pending_approval` row, so this query is a join-by-context lookup, not a "did the user approve?" check (the latter is enforced upstream by the HITL middleware).
3. **The send itself.** `await runtime.context.gmail_service.send_email(...)` (`gmail_service.py:66`). The service:
   - Builds an `email.message.EmailMessage`, sets To/Subject/In-Reply-To/References/threadId.
   - Base64-url encodes the bytes.
   - Calls `users().messages().send(userId="me", body={"raw": ...})`.
   - Returns the new Gmail message `id`.
   - All wrapped in `asyncio.to_thread` (`gmail_service.py:91`) so the blocking Google client call does not stall the event loop.
4. **Failure branch** (`draft_tools.py:92-126`). If Gmail raises:
   - `_mark_draft_send_failed(db, draft)` flips the draft row to `send_failed`.
   - A persisted `Notification` is created with `type="error"`, `title="Email Send Failed"`, the exception text, and a `metadata` dict linking the draft + conversation.
   - An SSE broadcast is fired on `notification_service.broadcast(user_id, {...})` for any connected dashboard.
   - A `Command(update={"messages": [ToolMessage(..., status="error")]})` is returned. **The graph state is not cleared** — `current_draft` stays set so the user can retry.
5. **Success branch** (`draft_tools.py:128-159`):
   - `_mark_draft_sent(db, draft, to, subject, body, gmail_id)` (`draft_tools.py:39`) sets `status="sent"`, `gmail_sent_id=gmail_id`, and crucially records *user edits* as `edited_to / edited_subject / edited_body` if the sent values differ from the LLM's original draft. Those columns are what `serialize_draft_for_frontend` (`backend/app/services/hitl_service.py:41`) returns to the UI so the conversation history shows both the LLM's draft and the human's edits.
   - A persistent `email_sent` notification is created.
   - An SSE broadcast is sent.
   - The `Command` clears `current_draft` and `draft_feedback` from graph state, plus a `ToolMessage` reporting the new Gmail message ID.
6. **Why two notifications.** The same `email_sent` event goes to *both* the DB (`create_notification`, used by the in-app notification list) and the in-memory broadcast queue (used by the live SSE stream). They are dual-path by design (see `backend/AGENTS.md` "Conventions").

**Side effects.**
- **Gmail:** `users().messages().send`. Non-idempotent.
- **DB:** an `UPDATE` on the `email_drafts` row (status flip + edit diffs).
- **DB:** a new `notifications` row.
- **SSE:** a `broadcast(...)` to the user's connected streams.

**Callers.** The coordinator's `send_email` tool binding. Per codegraph, 2 callers in `backend/app/routers/chat.py` and `backend/app/routers/approve.py` *via* `persist_hitl_interrupts` and the resume path. **Coverage:** `backend/tests/test_gmail_service.py` and `backend/tests/test_agent_tools.py` exist but no router-level integration tests.

**Notes / edge cases.**
- The "don't perform the Gmail send before the interrupt resumes" rule from `backend/AGENTS.md` is enforced by the `HumanInTheLoopMiddleware` configuration, not by this tool. The tool is a *passive* participant: when the middleware interrupts, the tool body never runs; when the middleware resumes, the tool body runs exactly once.
- `draft_type` is free-form text. The `HITL` service uses `args.get("draft_type") or "fresh"` as the default (`hitl_service.py:70`). Allowed values in practice are `"fresh"`, `"reply"` — set by the coordinator prompt, not validated here.
- The `Command` return shape differs between success and failure paths. On failure, only `messages` is updated (state preserved so retry works). On success, `current_draft` and `draft_feedback` are cleared and `messages` is updated. This is the *only* tool in the suite that uses `Command` for state mutation.

---

## 4. Tool runtime glue — `AgentContext` and DI

`backend/app/agents/context.py` (full file, 26 lines):

```python
@dataclass
class AgentContext:
    user_id: str
    conversation_id: str
    gmail_service: GmailService
    db_session: AsyncSession
    notification_service: NotificationService

    @property
    def user_uuid(self) -> UUID: ...
    @property
    def conversation_uuid(self) -> UUID: ...
```

This is the entire per-request context passed to every tool. A few design points worth calling out:

- **String IDs, not UUIDs, on the dataclass.** The tools that need UUIDs use the `.user_uuid` / `.conversation_uuid` properties (`draft_tools.py:30-31`). The string-typed fields exist because the dataclass is built once per request and the conversion is cheap.
- **No global state.** `gmail_service` carries the OAuth access token, `db_session` is the per-request `AsyncSession`, `notification_service` is the in-process broadcaster. None of the tools reach for module-level globals, which is what makes them safe to call concurrently.
- **Constructed at the edge.** Per `backend/AGENTS.md`, `AgentContext` is built at the chat-router boundary (the `/api/chat/message` route), then handed to the coordinator as it streams.

---

## 5. How the tools get bound to the LLM

`create_agent` (LangChain v1) is called with `tools=[...]` and a `context_schema=AgentContext` in each sub-agent factory:

- **Web-search agent** — `backend/app/agents/web_search_agent.py:33-46`. `tools=[web_search]`. `system_prompt=WEB_SEARCH_SYSTEM_PROMPT` instructs the model to return a strict JSON `{summary, sources}` object.
- **Mail-reader agent** — bound tools: `get_recent_emails`, `search_emails_by_sender`, `search_emails_by_topic`, `get_email_thread`, `get_full_email`. The factory lives in `backend/app/agents/mail_reader_agent.py` (not pulled into the explore above; blast radius from codegraph confirms 2 callers for `search_emails_by_sender`).
- **Coordinator** — bound tools include `send_email` plus the mail-reader agent as a sub-agent plus the web-search agent as a sub-agent. The exact wiring is in `backend/app/agents/coordinator.py` (referenced in the codegraph blast radius for `get_web_search_agent`).

Two more design points:

- **Memoized factories.** Both `get_web_search_agent` and the equivalent coordinator factory are module-level singletons keyed on `id(checkpointer)`. They rebuild only when the checkpointer identity changes (i.e. lifespan startup). The `global` keyword is used intentionally and the comment in `web_search_agent.py:30` is the canonical note.
- **Checkpointer identity.** Sub-agent threads are user-scoped (`mail_reader_{user_id}` per backend `AGENTS.md`); the coordinator thread is `conversation_id`. The user identity in the thread scope is what makes the per-user Postgres checkpointing safe across concurrent users.

---

## 6. Where tool calls enter and exit the system

A complete round-trip is useful to map the abstract tool call to a real request:

1. **Frontend → Backend.** `POST /api/chat/message` with the user's message and `conversation_id`. The route is in `backend/app/routers/chat.py` (called by both the route itself and the SSE stream code).
2. **Backend → LangGraph.** The route builds an `AgentContext` (gmail service + db session + notification broadcaster), then invokes the coordinator with `thread_id=conversation_id` and streams tokens/tool events.
3. **Coordinator → sub-agent or tool.** The LLM emits a `tool_calls` block. The runtime looks up the tool by name, deserializes the args, and calls the function with the injected `ToolRuntime`.
4. **Tool → side effect.** Each tool performs its work (Gmail read, Tavily search, or — at the HITL boundary — a *pause* via `HumanInTheLoopMiddleware`).
5. **Tool → `ToolMessage`.** The function's return value (or `Command.update["messages"][0]`) becomes a `ToolMessage` appended to the thread. The LLM sees it on the next iteration.
6. **Backend → Frontend.** The route streams the message delta to the user via SSE. On approval, `POST /api/approve` resumes the graph with `Command(resume=...)`.

---

## 7. Summary table

| Tool | File:line | Read/Write | Async | Returns | Sub-agent |
|---|---|---|---|---|---|
| `get_recent_emails` | `gmail_tools.py:54` | R | yes | `str` | mail-reader |
| `search_emails_by_sender` | `gmail_tools.py:62` | R | yes | `str` | mail-reader |
| `search_emails_by_topic` | `gmail_tools.py:71` | R | yes | `str` | mail-reader |
| `get_email_thread` | `gmail_tools.py:80` | R | yes | `str` | mail-reader |
| `get_full_email` | `gmail_tools.py:88` | R | yes | `str` | mail-reader |
| `web_search` | `search_tools.py:18` | R (network) | no | `dict` | web-search |
| `send_email` | `draft_tools.py:67` | **W (Gmail + DB + SSE)** | yes | `Command` | coordinator (HITL) |

---

## 8. Open questions / gaps surfaced by this walk

Worth raising for follow-up work (not requested, but visible from a clean read):

1. **No tests for any agent tool.** `codegraph` blast radius flagged `⚠️ no covering tests found` for `search_emails_by_sender`, `web_search`, `is_hitl_interrupt`, `persist_hitl_interrupts`, `get_web_search_agent`. `send_email` and `GmailService.send_email` have tests in `tests/test_gmail_service.py` and `tests/test_agent_tools.py`, but the route-layer integration is untested.
2. **`web_search` swallows all exceptions.** It returns `{"error": ...}` rather than raising. The web-search sub-agent is expected to recover, but the JSON contract is "return a structured object" — there's no enforcement that the model does so on error.
3. **`_build_query` is wider than the LLM can reach.** `days_back` is a `_build_query` parameter but no LLM-facing tool exposes it. Either the model is supposed to compose a raw `after:YYYY/MM/DD` clause via `search_emails_by_topic`'s `query` field (currently no — that field doesn't exist on the LLM-facing tool), or it's silently unavailable.
4. **No `try/except` on the read tools.** `get_email_thread` and `get_full_email` will surface Gmail API errors as raw exception text to the LLM. Not catastrophic, but inconsistent with `send_email` and `web_search` which both try/except.
5. **`AgentContext` is a `dataclass`, not a Pydantic model.** That's fine for runtime use, but if any tool ever needs validation (e.g. `to: EmailStr`), the conversion is ad-hoc.
