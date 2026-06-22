# Session-Scoped Remediation Checklist

Goal: keep each Codex session short, focused, and verifiable. One session should complete one scoped task, run the smallest relevant checks, and leave a clear handoff note.

## Session Rules

- [ ] Pick exactly one checklist section per Codex session.
- [ ] Create/use a dedicated branch for behavior or test changes.
- [ ] Keep the session objective narrow enough to finish with verification.
- [ ] Read the relevant `AGENTS.md` file before changing backend or frontend code.
- [ ] Run the smallest meaningful verification before ending the session.
- [ ] Record what changed, what was verified, and what remains.

## 1. Backend Test Suite Cleanup

- [ ] Remove or rewrite stale tests that reference deleted symbols:
  - `backend/tests/test_agent_factories.py`
  - `backend/tests/test_agent_tools.py`
- [ ] Update agent factory tests for current symbols:
  - `get_mailing_agent`
  - `get_mail_reader_agent`
  - `get_coordinator_agent`
  - `make_coordinator_tools`
- [ ] Add current tests for `send_email` behavior in `backend/app/agents/tools/draft_tools.py`.
- [ ] Verify: `cd backend; .\venv\Scripts\python.exe -m unittest discover -s tests`
- [ ] Verify: `cd backend; .\venv\Scripts\python.exe -m compileall app`

## 2. Backend Integration Test Harness

- [ ] Choose integration test approach: `unittest` + `httpx.AsyncClient` against FastAPI ASGI app.
- [ ] Add test DB configuration that does not touch dev/prod data.
- [ ] Add dependency overrides for auth user and DB session.
- [ ] Add lifecycle handling for FastAPI startup/shutdown or isolated app construction.
- [ ] Add fixture/helper for seeded users, conversations, drafts, and notifications.
- [ ] Verify harness with one minimal `/health` or authenticated route test.

## 3. Backend Auth And Router Integration Tests

- [ ] Test unauthenticated requests return `401` with uniform error shape.
- [ ] Test invalid JWT returns `401`.
- [ ] Test `/api/auth/me` returns current user from cookie auth.
- [ ] Test conversation create/list/history ownership boundaries.
- [ ] Test notification list/read ownership boundaries.
- [ ] Verify: backend integration test command from section 2.

## 4. Backend HITL And Send Flow Tests

- [ ] Test chat request with pending approval blocks before agent/Gmail setup.
- [ ] Test coordinator HITL config interrupts `send_email` before Gmail side effect.
- [ ] Test approve resumes send and updates draft status to `sent`.
- [ ] Test edit resumes send with edited fields persisted.
- [ ] Test reject marks draft `rejected` and does not call Gmail.
- [ ] Test send failure marks draft `send_failed` and emits error notification.
- [ ] Verify: backend integration test command from section 2.

## 5. Backend SSE Contract Tests

- [ ] Test `/api/chat/message` emits valid SSE frames.
- [ ] Test token events exclude raw tool JSON payloads.
- [ ] Test action events preserve stable `tool_call_id`.
- [ ] Test approval events include draft metadata and safe user-facing content.
- [ ] Test `/api/notifications/stream` emits notification events and pings.
- [ ] Verify: backend integration/contract tests.

## 6. Frontend Test Setup

- [ ] Add Vitest + React Testing Library + jsdom.
- [ ] Add `npm test` script.
- [ ] Add test setup file for DOM matchers and global mocks.
- [ ] Add MSW or lightweight API mocking strategy.
- [ ] Ensure tests work with `@/*` path alias.
- [ ] Verify: `cd frontend; npm test`
- [ ] Verify: `cd frontend; npm run build`

## 7. Frontend Unit Tests

- [ ] Test `getErrorMessage` and axios 401 redirect behavior.
- [ ] Test `authStore`, `chatStore`, and `approvalStore` state transitions.
- [ ] Test `MarkdownResponse` rendering for headings, lists, quotes, inline code, and emphasis.
- [ ] Test `InputBar` submit/disabled behavior.
- [ ] Test `ApprovalModal` approve/edit/reject calls and pending draft guard.
- [ ] Verify: `cd frontend; npm test`

## 8. Frontend Streaming And SSE Tests

- [ ] Test `useChat` parses SSE chunks across buffer boundaries.
- [ ] Test chat token/action/approval/error events update store correctly.
- [ ] Test failed chat request removes optimistic assistant message.
- [ ] Test `useSSE` handles approval, sent, rejected, and error notification events.
- [ ] Test reconnect cleanup on unmount.
- [ ] Verify: `cd frontend; npm test`

## 9. Frontend Lint Configuration

- [ ] Add non-interactive ESLint config for Next.js.
- [ ] Ensure `npm run lint` does not prompt.
- [ ] Fix or document lint findings.
- [ ] Verify: `cd frontend; npm run lint`
- [ ] Verify: `cd frontend; npm run build`

## 10. End-To-End Smoke Tests

- [ ] Add Playwright config.
- [ ] Add mocked backend or test backend strategy.
- [ ] Test unauthenticated dashboard redirects to login.
- [ ] Test authenticated dashboard renders core layout.
- [ ] Test chat send displays streaming assistant response.
- [ ] Test approval modal opens from notification event and submits approval.
- [ ] Verify: frontend E2E command.

## 11. CI And Documentation

- [ ] Add documented backend verification commands.
- [ ] Add documented frontend verification commands.
- [ ] Add CI job for backend compile + tests.
- [ ] Add CI job for frontend lint + build + tests.
- [ ] Document local test DB setup.
- [ ] Update `README.md`, `backend/AGENTS.md`, and `frontend/AGENTS.md` after tooling changes.

## Suggested Order

1. Backend Test Suite Cleanup
2. Backend Integration Test Harness
3. Backend Auth And Router Integration Tests
4. Backend HITL And Send Flow Tests
5. Backend SSE Contract Tests
6. Frontend Test Setup
7. Frontend Unit Tests
8. Frontend Streaming And SSE Tests
9. Frontend Lint Configuration
10. End-To-End Smoke Tests
11. CI And Documentation
