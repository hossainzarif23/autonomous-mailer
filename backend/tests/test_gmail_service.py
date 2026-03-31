from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase

from app.services.gmail_service import GmailService


class GmailServiceQueryTests(TestCase):
    def test_build_query_combines_supported_filters(self):
        service = GmailService.__new__(GmailService)
        query = service._build_query(sender="alerts@example.com", topic="invoice", query="label:inbox")
        self.assertIn("from:alerts@example.com", query)
        self.assertIn("subject:(invoice) OR (invoice)", query)
        self.assertIn("label:inbox", query)


class _FakeMessagesResource:
    def __init__(self):
        self.sent_payload = None

    def send(self, userId: str, body: dict):
        self.sent_payload = {"userId": userId, "body": body}
        return self

    def execute(self):
        return {"id": "gmail-message-123"}


class _FakeUsersResource:
    def __init__(self):
        self.messages_resource = _FakeMessagesResource()

    def messages(self):
        return self.messages_resource


class _FakeGmailApi:
    def __init__(self):
        self.users_resource = _FakeUsersResource()

    def users(self):
        return self.users_resource


class GmailServiceSendTests(IsolatedAsyncioTestCase):
    async def test_send_email_includes_threading_metadata(self):
        service = GmailService.__new__(GmailService)
        service.service = _FakeGmailApi()

        gmail_id = await service.send_email(
            to="ceo@example.com",
            subject="RE: Update",
            body="Thanks for the note.",
            in_reply_to="<message@example.com>",
            thread_id="thread-123",
        )

        sent = service.service.users().messages().sent_payload
        self.assertEqual(gmail_id, "gmail-message-123")
        self.assertEqual(sent["userId"], "me")
        self.assertEqual(sent["body"]["threadId"], "thread-123")
        self.assertIn("raw", sent["body"])

