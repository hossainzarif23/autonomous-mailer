from __future__ import annotations

import asyncio
import base64
from email.message import EmailMessage
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.utils.email_parser import parse_gmail_message, parse_gmail_thread


class GmailService:
    def __init__(self, access_token: str):
        credentials = Credentials(token=access_token)
        # cache_discovery=False avoids oauth-related file system noise in local dev
        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    async def list_messages(self, query: str = "", max_results: int = 10) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            response = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            items = response.get("messages", [])
            parsed: list[dict[str, Any]] = []
            for item in items:
                full_message = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=item["id"], format="full")
                    .execute()
                )
                parsed.append(parse_gmail_message(full_message))
            return parsed

        return await asyncio.to_thread(_list)

    async def get_message(self, message_id: str) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            response = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return parse_gmail_message(response)

        return await asyncio.to_thread(_get)

    async def get_thread(self, thread_id: str) -> dict[str, Any]:
        def _get_thread() -> dict[str, Any]:
            response = (
                self.service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
            return parse_gmail_thread(response)

        return await asyncio.to_thread(_get_thread)

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        def _send() -> str:
            message = EmailMessage()
            message["To"] = to
            message["Subject"] = subject
            if in_reply_to:
                message["In-Reply-To"] = in_reply_to
                message["References"] = in_reply_to
            message.set_content(body)

            encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
            payload: dict[str, Any] = {"raw": encoded}
            if thread_id:
                payload["threadId"] = thread_id

            response = self.service.users().messages().send(userId="me", body=payload).execute()
            return response["id"]

        return await asyncio.to_thread(_send)

    def _build_query(
        self,
        sender: str | None = None,
        topic: str | None = None,
        days_back: int | None = None,
        query: str | None = None,
    ) -> str:
        parts: list[str] = []
        if sender:
            parts.append(f"from:{sender}")
        if topic:
            parts.append(f"subject:({topic}) OR ({topic})")
        if days_back:
            from datetime import date, timedelta

            since = (date.today() - timedelta(days=days_back)).strftime("%Y/%m/%d")
            parts.append(f"after:{since}")
        if query:
            parts.append(query)
        return " ".join(part for part in parts if part)
