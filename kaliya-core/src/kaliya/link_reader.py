from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


@dataclass(frozen=True)
class LinkSummary:
    url: str
    final_url: str
    status_code: int | None
    content_type: str
    title: str
    description: str
    text: str
    error: str = ""


def extract_urls(text: str) -> list[str]:
    return [match.group(0).rstrip(".,!?)]}") for match in URL_RE.finditer(text)]


async def fetch_link_summaries(
    urls: list[str],
    *,
    timeout_seconds: int = 10,
    max_bytes: int = 512 * 1024,
    limit: int = 3,
) -> list[LinkSummary]:
    summaries: list[LinkSummary] = []
    for url in urls[:limit]:
        summaries.append(
            await fetch_link_summary(
                url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
        )
    return summaries


async def fetch_link_summary(
    url: str,
    *,
    timeout_seconds: int,
    max_bytes: int,
) -> LinkSummary:
    try:
        current_url = await _validated_url(url)
        timeout = httpx.Timeout(timeout_seconds)
        headers = {
            "accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.2",
            "user-agent": "N1NAgents/0.1",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for _ in range(5):
                async with client.stream("GET", current_url, headers=headers) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            break
                        current_url = await _validated_url(urljoin(str(response.url), location))
                        continue
                    content_type = response.headers.get("content-type", "").split(";")[0].strip()
                    body = await _read_limited(response, max_bytes=max_bytes)
                    return _summary_from_body(
                        original_url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                    )
    except Exception as exc:
        return LinkSummary(url, url, None, "", "", "", "", error=str(exc))

    return LinkSummary(url, current_url, None, "", "", "", "", error="Could not fetch link.")


def format_link_context(summaries: list[LinkSummary]) -> str:
    if not summaries:
        return ""
    blocks: list[str] = []
    for summary in summaries:
        if summary.error:
            blocks.append(f"URL: {summary.url}\nFetch error: {summary.error}")
            continue
        lines = [f"URL: {summary.final_url}"]
        if summary.title:
            lines.append(f"Title: {summary.title}")
        if summary.description:
            lines.append(f"Description: {summary.description}")
        if summary.text:
            lines.append(f"Text excerpt: {summary.text}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def _validated_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https links are supported.")
    if not parsed.hostname:
        raise ValueError("Link has no hostname.")

    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("Local links are blocked.")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError as exc:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, parsed.port or 443)
        addresses = {item[4][0] for item in infos}
        if not addresses:
            raise ValueError("Hostname did not resolve.") from exc
        for address in addresses:
            _validate_public_ip(ipaddress.ip_address(address))
    else:
        _validate_public_ip(ip)
    return url


def _validate_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not ip.is_global:
        raise ValueError("Private, local, or reserved links are blocked.")


async def _read_limited(response: httpx.Response, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            remaining = max(0, max_bytes - (total - len(chunk)))
            if remaining:
                chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _summary_from_body(
    *,
    original_url: str,
    final_url: str,
    status_code: int,
    content_type: str,
    body: bytes,
) -> LinkSummary:
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type or "<html" in text[:500].lower():
        parser = ReadableHtmlParser()
        parser.feed(text)
        return LinkSummary(
            url=original_url,
            final_url=final_url,
            status_code=status_code,
            content_type=content_type,
            title=_clean_text(parser.title, limit=240),
            description=_clean_text(parser.description, limit=500),
            text=_clean_text(" ".join(parser.text_parts), limit=1800),
        )
    return LinkSummary(
        url=original_url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        title="",
        description="",
        text=_clean_text(text, limit=1800),
    )


class ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.text_parts: list[str] = []
        self._tag_stack: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            data = {key.lower(): value or "" for key, value in attrs}
            name = data.get("name", "").lower()
            prop = data.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.description = self.description or data.get("content", "")
            if prop == "og:title":
                self.title = self.title or data.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if any(tag in {"script", "style", "noscript", "svg", "canvas"} for tag in self._tag_stack):
            return
        value = data.strip()
        if not value:
            return
        if self._in_title:
            self.title += f" {value}"
            return
        self.text_parts.append(value)


def _clean_text(value: str, *, limit: int) -> str:
    clean = html.unescape(" ".join(value.split()))
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."
