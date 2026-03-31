from __future__ import annotations

from unittest import TestCase

from app.utils.email_parser import parse_gmail_message, parse_gmail_thread


class EmailParserTests(TestCase):
    def test_parse_gmail_message_prefers_text_plain_body(self):
        raw_message = {
            "id": "msg-1",
            "threadId": "thread-1",
            "labelIds": ["INBOX"],
            "snippet": "Hello there",
            "internalDate": "1000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice Example <alice@example.com>"},
                    {"name": "To", "value": "Bob <bob@example.com>"},
                    {"name": "Subject", "value": "Status Update"},
                    {"name": "Date", "value": "Mon, 31 Mar 2026 10:00:00 +0000"},
                    {"name": "Message-ID", "value": "<abc123@example.com>"},
                ],
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": "SGVsbG8gdGV4dCBib2R5"}},
                    {"mimeType": "text/html", "body": {"data": "PGRpdj5IZWxsbyA8Yj5IVE1MPC9iPjwvZGl2Pg"}},
                ],
            },
        }

        parsed = parse_gmail_message(raw_message)

        self.assertEqual(parsed["message_id"], "msg-1")
        self.assertEqual(parsed["thread_id"], "thread-1")
        self.assertEqual(parsed["from_name"], "Alice Example")
        self.assertEqual(parsed["from_email"], "alice@example.com")
        self.assertEqual(parsed["subject"], "Status Update")
        self.assertEqual(parsed["body"], "Hello text body")

    def test_parse_gmail_thread_sorts_messages_by_internal_date(self):
        raw_thread = {
            "id": "thread-1",
            "messages": [
                {
                    "id": "msg-2",
                    "threadId": "thread-1",
                    "snippet": "second",
                    "internalDate": "2000",
                    "payload": {"headers": [{"name": "From", "value": "B <b@example.com>"}], "body": {}},
                },
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "snippet": "first",
                    "internalDate": "1000",
                    "payload": {"headers": [{"name": "From", "value": "A <a@example.com>"}], "body": {}},
                },
            ],
        }

        parsed = parse_gmail_thread(raw_thread)

        self.assertEqual(parsed["thread_id"], "thread-1")
        self.assertEqual([message["message_id"] for message in parsed["messages"]], ["msg-1", "msg-2"])

