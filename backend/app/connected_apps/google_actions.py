from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntegrationAccount, IntegrationProvider, IntegrationToken, UserIntegration
from app.token_crypto import decrypt_token

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SHEETS_API = "https://sheets.googleapis.com/v4"

MAX_GMAIL_RESULTS = 25
MAX_CALENDAR_RESULTS = 50
MAX_SHEET_ROWS = 100
MAX_SHEET_COLUMNS = 200
MAX_TEXT_BODY_CHARS = 20_000
MAX_SHEET_READ_CHARS = 50_000

EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_MISSING = object()

GOOGLE_AGENT_TOOLS = frozenset(
    {
        "search_gmail",
        "read_gmail_thread",
        "create_gmail_draft",
        "send_gmail",
        "reply_gmail",
        "list_calendar_events",
        "find_free_time",
        "create_calendar_event",
        "read_google_sheet",
        "append_google_sheet_row",
        "update_google_sheet_row",
    }
)
GOOGLE_WRITE_AGENT_TOOLS = frozenset(
    {
        "create_gmail_draft",
        "send_gmail",
        "reply_gmail",
        "create_calendar_event",
        "append_google_sheet_row",
        "update_google_sheet_row",
    }
)

GOOGLE_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "search_gmail": (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://mail.google.com/",
    ),
    "read_gmail_thread": (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://mail.google.com/",
    ),
    "create_gmail_draft": (
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://mail.google.com/",
    ),
    "send_gmail": (
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://mail.google.com/",
    ),
    "reply_gmail": (
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://mail.google.com/",
    ),
    "list_calendar_events": (
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar",
    ),
    "find_free_time": (
        "https://www.googleapis.com/auth/calendar.freebusy",
        "https://www.googleapis.com/auth/calendar.events.freebusy",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar",
    ),
    "create_calendar_event": (
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events.owned",
    ),
    "read_google_sheet": ("https://www.googleapis.com/auth/spreadsheets",),
    "append_google_sheet_row": ("https://www.googleapis.com/auth/spreadsheets",),
    "update_google_sheet_row": ("https://www.googleapis.com/auth/spreadsheets",),
}


@dataclass(frozen=True)
class GoogleCredentials:
    account_id: int
    access_token: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class GoogleToolExecution:
    account_id: int
    result: dict[str, Any]


def is_google_agent_tool(tool: str) -> bool:
    return tool in GOOGLE_AGENT_TOOLS


def _scope_values(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(part for part in value.replace(",", " ").split() if part)


def load_google_credentials(
    db: Session,
    *,
    user_id: int,
    account_id: int | None = None,
) -> GoogleCredentials:
    provider = db.scalar(select(IntegrationProvider).where(IntegrationProvider.key == "google"))
    if provider is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google is not connected")

    integration = db.scalar(
        select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider_id == provider.id,
        )
    )
    if integration is None or integration.status != "connected":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google connection needs to be reconnected",
        )

    account_query = select(IntegrationAccount).where(
        IntegrationAccount.user_integration_id == integration.id,
        IntegrationAccount.provider_id == provider.id,
    )
    if account_id is not None:
        account_query = account_query.where(IntegrationAccount.id == account_id)
    account = db.scalar(
        account_query.order_by(IntegrationAccount.is_default.desc(), IntegrationAccount.created_at.asc())
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Google account was not found")

    token = db.scalar(
        select(IntegrationToken)
        .where(
            IntegrationToken.user_integration_id == integration.id,
            IntegrationToken.integration_account_id == account.id,
        )
        .order_by(IntegrationToken.updated_at.desc(), IntegrationToken.id.desc())
    )
    if token is None or not token.encrypted_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authorization is missing. Reconnect Google and try again.",
        )
    return GoogleCredentials(
        account_id=account.id,
        access_token=decrypt_token(token.encrypted_access_token),
        scopes=_scope_values(token.scopes),
    )


def _optional_account_id(arguments: dict[str, Any]) -> int | None:
    value = arguments.get("account_id", arguments.get("accountId"))
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account_id must be a positive integer")
    try:
        account_id = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account_id must be a positive integer") from exc
    if account_id < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account_id must be a positive integer")
    return account_id


def _argument(arguments: dict[str, Any], *names: str, default: object = _MISSING) -> Any:
    for name in names:
        if name in arguments:
            return arguments[name]
    return default


def _required_text(arguments: dict[str, Any], *names: str, label: str, max_length: int) -> str:
    value = _argument(arguments, *names)
    if not isinstance(value, str):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is required")
    text = value.strip()
    if not text or len(text) > max_length:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is invalid")
    return text


def _optional_text(arguments: dict[str, Any], *names: str, label: str, max_length: int) -> str | None:
    value = _argument(arguments, *names, default=None)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is invalid")
    text = value.strip()
    if len(text) > max_length:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is invalid")
    return text or None


def _bounded_int(arguments: dict[str, Any], *names: str, default: int, minimum: int, maximum: int, label: str) -> int:
    value = _argument(arguments, *names, default=default)
    if isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} is invalid")
    return parsed


def _require_approved(arguments: dict[str, Any], tool: str) -> None:
    if arguments.get("approved") is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{tool} requires explicit approval before it can make an external change",
        )


def _require_scope(credentials: GoogleCredentials, tool: str) -> None:
    required_scopes = GOOGLE_TOOL_SCOPES[tool]
    if not credentials.scopes or not credentials.scopes.intersection(required_scopes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google connection is missing the required permission. Reconnect Google and grant the requested access.",
        )


async def google_api_request(
    access_token: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                params=params,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google request failed") from exc

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    if response.status_code >= 500:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google service is unavailable. Try again shortly.")
    if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google request was not authorized. Reconnect Google and verify the granted permissions.",
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google rejected this request. Check the selected account and fields.")
    return payload if isinstance(payload, dict) else {}


def _email_recipients(arguments: dict[str, Any]) -> list[str]:
    value = _argument(arguments, "to", "recipients")
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        raw_values = value
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="to must contain at least one email address")
    if any("\r" in item or "\n" in item for item in raw_values):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="to is invalid")
    recipients = [address.strip() for _name, address in getaddresses(raw_values) if address.strip()]
    if not recipients or len(recipients) > 50 or any(not EMAIL_RE.fullmatch(address) for address in recipients):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="to is invalid")
    return recipients


def _gmail_raw_message(arguments: dict[str, Any]) -> str:
    recipients = _email_recipients(arguments)
    subject = _required_text(arguments, "subject", label="subject", max_length=255)
    body = _required_text(arguments, "body", "text", label="body", max_length=MAX_TEXT_BODY_CHARS)
    if "\r" in subject or "\n" in subject:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="subject is invalid")
    message = EmailMessage()
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


def _gmail_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    wanted = {"from", "to", "subject", "date"}
    result: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "").strip()
        if name in wanted and value:
            result[name] = value[:1000]
    return result


def _decode_gmail_body(value: str) -> str:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return ""


def _gmail_text_part(payload: dict[str, Any]) -> str:
    mime_type = str(payload.get("mimeType") or "").lower()
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    data = body.get("data") if isinstance(body.get("data"), str) else ""
    if mime_type.startswith("text/plain") and data:
        return _decode_gmail_body(data)
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    for part in parts:
        if isinstance(part, dict):
            text = _gmail_text_part(part)
            if text:
                return text
    return ""


async def _search_gmail(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    query = _required_text(arguments, "query", "q", label="query", max_length=1000)
    max_results = _bounded_int(
        arguments,
        "max_results",
        "maxResults",
        default=10,
        minimum=1,
        maximum=MAX_GMAIL_RESULTS,
        label="max_results",
    )
    payload = await google_api_request(
        credentials.access_token,
        "GET",
        f"{GMAIL_API}/messages",
        params={"q": query, "maxResults": max_results},
    )
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    return {
        "messages": [
            {"id": item.get("id"), "threadId": item.get("threadId")}
            for item in messages
            if isinstance(item, dict)
        ],
        "resultSizeEstimate": payload.get("resultSizeEstimate", 0),
        "nextPageToken": payload.get("nextPageToken"),
    }


async def _read_gmail_thread(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    thread_id = _required_text(arguments, "thread_id", "threadId", label="thread_id", max_length=200)
    if not IDENTIFIER_RE.fullmatch(thread_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="thread_id is invalid")
    include_body = arguments.get("include_body", arguments.get("includeBody", False)) is True
    payload = await google_api_request(
        credentials.access_token,
        "GET",
        f"{GMAIL_API}/threads/{quote(thread_id, safe='')}",
        params={"format": "full" if include_body else "metadata"},
    )
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    result_messages = []
    remaining_body_chars = MAX_TEXT_BODY_CHARS
    for message in messages[:MAX_GMAIL_RESULTS]:
        if not isinstance(message, dict):
            continue
        gmail_payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        item: dict[str, Any] = {
            "id": message.get("id"),
            "threadId": message.get("threadId"),
            "snippet": str(message.get("snippet") or "")[:2000],
            "headers": _gmail_headers(gmail_payload),
        }
        if include_body:
            item["text"] = _gmail_text_part(gmail_payload)[:remaining_body_chars]
            remaining_body_chars -= len(item["text"])
        result_messages.append(item)
    return {"id": payload.get("id") or thread_id, "messages": result_messages}


async def _create_gmail_draft(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_approved(arguments, "create_gmail_draft")
    payload = await google_api_request(
        credentials.access_token,
        "POST",
        f"{GMAIL_API}/drafts",
        json_body={"message": {"raw": _gmail_raw_message(arguments)}},
    )
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    return {"draftId": payload.get("id"), "messageId": message.get("id"), "threadId": message.get("threadId")}


async def _send_gmail(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_approved(arguments, "send_gmail")
    payload = await google_api_request(
        credentials.access_token,
        "POST",
        f"{GMAIL_API}/messages/send",
        json_body={"raw": _gmail_raw_message(arguments)},
    )
    return {"messageId": payload.get("id"), "threadId": payload.get("threadId"), "labelIds": payload.get("labelIds", [])}


async def _reply_gmail(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_approved(arguments, "reply_gmail")
    thread_id = _required_text(arguments, "thread_id", "threadId", label="thread_id", max_length=200)
    if not IDENTIFIER_RE.fullmatch(thread_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="thread_id is invalid")
    payload = await google_api_request(
        credentials.access_token,
        "POST",
        f"{GMAIL_API}/messages/send",
        json_body={"raw": _gmail_raw_message(arguments), "threadId": thread_id},
    )
    return {"messageId": payload.get("id"), "threadId": payload.get("threadId") or thread_id, "labelIds": payload.get("labelIds", [])}


def _calendar_id(arguments: dict[str, Any]) -> str:
    calendar_id = _optional_text(arguments, "calendar_id", "calendarId", label="calendar_id", max_length=255) or "primary"
    if any(char in calendar_id for char in "\r\n"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="calendar_id is invalid")
    return calendar_id


def _rfc3339(arguments: dict[str, Any], *names: str, label: str) -> tuple[str, datetime]:
    value = _required_text(arguments, *names, label=label, max_length=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must be an RFC3339 datetime") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} must include a timezone")
    return value, parsed.astimezone(UTC)


def _calendar_bounds(arguments: dict[str, Any], *, default_window: bool = False) -> tuple[str, str]:
    start_value = _argument(arguments, "time_min", "timeMin", "start", "start_at", "startAt", default=None)
    end_value = _argument(arguments, "time_max", "timeMax", "end", "end_at", "endAt", default=None)
    if start_value is None and end_value is None and default_window:
        now = datetime.now(UTC).replace(microsecond=0)
        return now.isoformat().replace("+00:00", "Z"), (now + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    start_text, start = _rfc3339({"value": start_value}, "value", label="time_min")
    end_text, end = _rfc3339({"value": end_value}, "value", label="time_max")
    if end <= start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="time_max must be after time_min")
    return start_text, end_text


def _calendar_event(payload: dict[str, Any]) -> dict[str, Any]:
    description = str(payload.get("description") or "")[:10_000] or None
    summary = str(payload.get("summary") or "")[:1024] or None
    location = str(payload.get("location") or "")[:1024] or None
    return {
        "id": payload.get("id"),
        "status": payload.get("status"),
        "summary": summary,
        "description": description,
        "location": location,
        "start": payload.get("start"),
        "end": payload.get("end"),
        "htmlLink": payload.get("htmlLink"),
    }


async def _list_calendar_events(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    calendar_id = _calendar_id(arguments)
    time_min, time_max = _calendar_bounds(arguments, default_window=True)
    max_results = _bounded_int(
        arguments,
        "max_results",
        "maxResults",
        default=20,
        minimum=1,
        maximum=MAX_CALENDAR_RESULTS,
        label="max_results",
    )
    params: dict[str, Any] = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    query = _optional_text(arguments, "query", "q", label="query", max_length=1000)
    if query:
        params["q"] = query
    payload = await google_api_request(
        credentials.access_token,
        "GET",
        f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
        params=params,
    )
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        "calendarId": calendar_id,
        "events": [_calendar_event(item) for item in items if isinstance(item, dict)],
        "nextPageToken": payload.get("nextPageToken"),
    }


async def _find_free_time(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    calendar_id = _calendar_id(arguments)
    time_min, time_max = _calendar_bounds(arguments)
    payload = await google_api_request(
        credentials.access_token,
        "POST",
        f"{CALENDAR_API}/freeBusy",
        json_body={"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]},
    )
    calendars = payload.get("calendars") if isinstance(payload.get("calendars"), dict) else {}
    calendar = calendars.get(calendar_id) if isinstance(calendars.get(calendar_id), dict) else {}
    return {"calendarId": calendar_id, "timeMin": time_min, "timeMax": time_max, "busy": calendar.get("busy", [])}


async def _create_calendar_event(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_approved(arguments, "create_calendar_event")
    calendar_id = _calendar_id(arguments)
    summary = _required_text(arguments, "summary", "title", label="summary", max_length=1024)
    start_text, start = _rfc3339(arguments, "start", "start_at", "startAt", label="start")
    end_text, end = _rfc3339(arguments, "end", "end_at", "endAt", label="end")
    if end <= start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end must be after start")
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_text},
        "end": {"dateTime": end_text},
    }
    description = _optional_text(arguments, "description", label="description", max_length=10_000)
    location = _optional_text(arguments, "location", label="location", max_length=1024)
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    payload = await google_api_request(
        credentials.access_token,
        "POST",
        f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
        params={"sendUpdates": "none"},
        json_body=body,
    )
    return _calendar_event(payload)


def _sheet_reference(arguments: dict[str, Any]) -> tuple[str, str]:
    spreadsheet_id = _required_text(arguments, "spreadsheet_id", "spreadsheetId", label="spreadsheet_id", max_length=200)
    if not IDENTIFIER_RE.fullmatch(spreadsheet_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="spreadsheet_id is invalid")
    range_name = _required_text(arguments, "range", "sheet_range", "sheetRange", label="range", max_length=500)
    if any(char in range_name for char in "\r\n"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="range is invalid")
    return spreadsheet_id, range_name


def _sheet_rows(arguments: dict[str, Any], *, require_single_row: bool) -> list[list[str | int | float | bool | None]]:
    value = _argument(arguments, "values", "row")
    if not isinstance(value, list) or not value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="values must be a non-empty array")
    rows = value if isinstance(value[0], list) else [value]
    if not all(isinstance(row, list) and row for row in rows):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="values must contain non-empty rows")
    if (require_single_row and len(rows) != 1) or len(rows) > MAX_SHEET_ROWS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="values has too many rows")
    normalized: list[list[str | int | float | bool | None]] = []
    for row in rows:
        if len(row) > MAX_SHEET_COLUMNS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="values has too many columns")
        normalized_row: list[str | int | float | bool | None] = []
        for cell in row:
            if not isinstance(cell, (str, int, float, bool)) and cell is not None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="values contains an unsupported cell")
            if isinstance(cell, str) and len(cell) > 10_000:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="values contains an oversized cell")
            normalized_row.append(cell)
        normalized.append(normalized_row)
    return normalized


def _limited_sheet_values(value: object) -> tuple[list[list[str]], bool]:
    if not isinstance(value, list):
        return [], False
    rows: list[list[str]] = []
    remaining_chars = MAX_SHEET_READ_CHARS
    truncated = len(value) > MAX_SHEET_ROWS
    for raw_row in value[:MAX_SHEET_ROWS]:
        if not isinstance(raw_row, list):
            continue
        row: list[str] = []
        if len(raw_row) > MAX_SHEET_COLUMNS:
            truncated = True
        for cell in raw_row[:MAX_SHEET_COLUMNS]:
            text = str(cell)
            if len(text) > remaining_chars:
                text = text[:remaining_chars]
                truncated = True
            row.append(text)
            remaining_chars -= len(text)
            if remaining_chars <= 0:
                truncated = True
                break
        rows.append(row)
        if remaining_chars <= 0:
            break
    return rows, truncated


async def _read_google_sheet(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    spreadsheet_id, range_name = _sheet_reference(arguments)
    payload = await google_api_request(
        credentials.access_token,
        "GET",
        f"{SHEETS_API}/spreadsheets/{quote(spreadsheet_id, safe='')}/values/{quote(range_name, safe='')}",
    )
    values, truncated = _limited_sheet_values(payload.get("values"))
    return {
        "spreadsheetId": payload.get("spreadsheetId") or spreadsheet_id,
        "range": payload.get("range") or range_name,
        "majorDimension": payload.get("majorDimension"),
        "values": values,
        "truncated": truncated,
    }


async def _append_google_sheet_row(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_approved(arguments, "append_google_sheet_row")
    spreadsheet_id, range_name = _sheet_reference(arguments)
    payload = await google_api_request(
        credentials.access_token,
        "POST",
        f"{SHEETS_API}/spreadsheets/{quote(spreadsheet_id, safe='')}/values/{quote(range_name, safe='')}:append",
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json_body={"majorDimension": "ROWS", "values": _sheet_rows(arguments, require_single_row=True)},
    )
    updates = payload.get("updates") if isinstance(payload.get("updates"), dict) else {}
    return {
        "spreadsheetId": payload.get("spreadsheetId") or spreadsheet_id,
        "tableRange": payload.get("tableRange"),
        "updatedRange": updates.get("updatedRange"),
        "updatedRows": updates.get("updatedRows"),
        "updatedCells": updates.get("updatedCells"),
    }


async def _update_google_sheet_row(credentials: GoogleCredentials, arguments: dict[str, Any]) -> dict[str, Any]:
    _require_approved(arguments, "update_google_sheet_row")
    spreadsheet_id, range_name = _sheet_reference(arguments)
    payload = await google_api_request(
        credentials.access_token,
        "PUT",
        f"{SHEETS_API}/spreadsheets/{quote(spreadsheet_id, safe='')}/values/{quote(range_name, safe='')}",
        params={"valueInputOption": "USER_ENTERED"},
        json_body={"majorDimension": "ROWS", "values": _sheet_rows(arguments, require_single_row=False)},
    )
    return {
        "spreadsheetId": payload.get("spreadsheetId") or spreadsheet_id,
        "updatedRange": payload.get("updatedRange") or range_name,
        "updatedRows": payload.get("updatedRows"),
        "updatedColumns": payload.get("updatedColumns"),
        "updatedCells": payload.get("updatedCells"),
    }


async def execute_google_agent_tool(
    db: Session,
    *,
    user_id: int,
    tool: str,
    arguments: dict[str, Any],
) -> GoogleToolExecution:
    if not is_google_agent_tool(tool):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported Google tool: {tool}")
    credentials = load_google_credentials(db, user_id=user_id, account_id=_optional_account_id(arguments))
    _require_scope(credentials, tool)

    if tool == "search_gmail":
        result = await _search_gmail(credentials, arguments)
    elif tool == "read_gmail_thread":
        result = await _read_gmail_thread(credentials, arguments)
    elif tool == "create_gmail_draft":
        result = await _create_gmail_draft(credentials, arguments)
    elif tool == "send_gmail":
        result = await _send_gmail(credentials, arguments)
    elif tool == "reply_gmail":
        result = await _reply_gmail(credentials, arguments)
    elif tool == "list_calendar_events":
        result = await _list_calendar_events(credentials, arguments)
    elif tool == "find_free_time":
        result = await _find_free_time(credentials, arguments)
    elif tool == "create_calendar_event":
        result = await _create_calendar_event(credentials, arguments)
    elif tool == "read_google_sheet":
        result = await _read_google_sheet(credentials, arguments)
    elif tool == "append_google_sheet_row":
        result = await _append_google_sheet_row(credentials, arguments)
    else:
        result = await _update_google_sheet_row(credentials, arguments)
    return GoogleToolExecution(account_id=credentials.account_id, result=result)
