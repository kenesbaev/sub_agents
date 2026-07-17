from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YouTubeGrowthError(Exception):
    code: str
    message: str
    status_code: int = 400
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class YouTubeNotConfiguredError(YouTubeGrowthError):
    def __init__(self, message: str = "YouTube Data API is not configured and no connected YouTube account is available.") -> None:
        super().__init__("youtube_not_configured", message, 503, False)


class YouTubeNotConnectedError(YouTubeGrowthError):
    def __init__(self, message: str = "Connect YouTube before using private channel analytics.") -> None:
        super().__init__("youtube_not_connected", message, 409, False)


class YouTubePermissionError(YouTubeGrowthError):
    def __init__(self, message: str = "The connected YouTube account is missing the required permission.") -> None:
        super().__init__("insufficient_permissions", message, 403, False)


class YouTubeQuotaError(YouTubeGrowthError):
    def __init__(self, message: str = "YouTube API quota was exceeded. Try again after the quota resets.") -> None:
        super().__init__("quota_exceeded", message, 429, True)


class YouTubeRateLimitError(YouTubeGrowthError):
    def __init__(self, message: str = "YouTube API rate limit was reached. Try again shortly.") -> None:
        super().__init__("rate_limited", message, 429, True)


class YouTubeTimeoutError(YouTubeGrowthError):
    def __init__(self, message: str = "YouTube API timed out. Try again.") -> None:
        super().__init__("timeout", message, 504, True)


class YouTubeNotFoundError(YouTubeGrowthError):
    def __init__(self, message: str = "The requested YouTube resource was not found.") -> None:
        super().__init__("not_found", message, 404, False)


class CommentsDisabledError(YouTubeGrowthError):
    def __init__(self) -> None:
        super().__init__("comments_disabled", "Comments are disabled or unavailable for this video.", 409, False)


class CaptionsUnavailableError(YouTubeGrowthError):
    def __init__(self) -> None:
        super().__init__("captions_unavailable", "Captions are unavailable through the authorized YouTube API.", 409, False)


class AnalyticsUnavailableError(YouTubeGrowthError):
    def __init__(self, message: str = "YouTube Analytics is unavailable for this account or video.") -> None:
        super().__init__("analytics_unavailable", message, 409, False)


class ModelUnavailableError(YouTubeGrowthError):
    def __init__(self) -> None:
        super().__init__(
            "model_unavailable",
            "Content-plan generation requires YOUTUBE_LLM_API_URL, YOUTUBE_LLM_API_KEY, and YOUTUBE_LLM_MODEL.",
            503,
            False,
        )


class InvalidModelOutputError(YouTubeGrowthError):
    def __init__(self) -> None:
        super().__init__(
            "invalid_model_output",
            "The AI model did not return a valid content plan after two repair attempts.",
            502,
            True,
        )


class OperationInProgressError(YouTubeGrowthError):
    def __init__(self, message: str = "A request with this idempotency key is already in progress.") -> None:
        super().__init__("operation_in_progress", message, 409, True)


class IdempotencyConflictError(YouTubeGrowthError):
    def __init__(self) -> None:
        super().__init__(
            "idempotency_conflict",
            "This idempotency key was already used with different delegation input.",
            409,
            False,
        )


class YouTubeTeamUnavailableError(YouTubeGrowthError):
    def __init__(self, message: str = "The YouTube Growth team is not configured in this workspace.") -> None:
        super().__init__("youtube_team_unavailable", message, 409, False)


class YouTubeUpstreamError(YouTubeGrowthError):
    def __init__(self, message: str = "YouTube API is temporarily unavailable.", *, retryable: bool = True) -> None:
        super().__init__("youtube_upstream_error", message, 502, retryable)
