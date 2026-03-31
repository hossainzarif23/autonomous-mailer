from __future__ import annotations

import base64
import html
import re
from email.utils import parseaddr
from typing import Any


def _decode_base64url(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="replace")


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return html.unescape(cleaned).strip()


def _headers_to_dict(headers: list[dict[str, str]] | None) -> dict[str, str]:
    return {header.get("name", ""): header.get("value", "") for header in headers or []}


def _extract_body(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""

    mime_type = payload.get("mimeType")
    body_data = payload.get("body", {}).get("data")
    parts = payload.get("parts") or []

    if body_data and mime_type == "text/plain":
        return _decode_base64url(body_data).strip()

    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode_base64url(part["body"]["data"]).strip()

    if body_data and mime_type == "text/html":
        return _strip_html(_decode_base64url(body_data))

    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return _strip_html(_decode_base64url(part["body"]["data"]))

    for part in parts:
        nested = _extract_body(part)
        if nested:
            return nested

    return ""


def parse_gmail_message(raw_message: dict[str, Any]) -> dict[str, Any]:
    payload = raw_message.get("payload", {})
    headers = _headers_to_dict(payload.get("headers"))
    from_name, from_email = parseaddr(headers.get("From", ""))

    return {
        "message_id": raw_message.get("id", ""),
        "thread_id": raw_message.get("threadId", ""),
        "label_ids": raw_message.get("labelIds", []),
        "snippet": raw_message.get("snippet", ""),
        "subject": headers.get("Subject", ""),
        "from_name": from_name or from_email,
        "from_email": from_email,
        "to": headers.get("To", ""),
        "cc": headers.get("Cc", ""),
        "date": headers.get("Date", ""),
        "body": _extract_body(payload),
        "internal_date": raw_message.get("internalDate"),
        "gmail_message_header": headers.get("Message-ID", ""),
        "references": headers.get("References", ""),
        "in_reply_to": headers.get("In-Reply-To", ""),
    }


def parse_gmail_thread(raw_thread: dict[str, Any]) -> dict[str, Any]:
    messages = [parse_gmail_message(message) for message in raw_thread.get("messages", [])]
    messages.sort(key=lambda item: int(item["internal_date"] or 0))
    return {
        "thread_id": raw_thread.get("id", ""),
        "history_id": raw_thread.get("historyId"),
        "messages": messages,
    }
