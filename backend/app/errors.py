"""Errors the PWA reacts to by more than showing the message.

Every error body is ``{"detail": "<sentence>"}``; these add a machine-readable
``"code"`` next to it (see the handlers in main.py)."""

API_KEY_REQUIRED = "api_key_required"
GROCY_UNREACHABLE = "grocy_unreachable"
GROCY_ACCOUNT_INVALID = "grocy_account_invalid"


class ApiError(Exception):
    def __init__(self, status: int, detail: str, code: str | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code

    def body(self) -> dict[str, str]:
        return {"detail": self.detail, **({"code": self.code} if self.code else {})}


def account_invalid() -> ApiError:
    """Grocy no longer accepts this person's key, so their app session is over."""
    return ApiError(
        401, "Your Grocy account is no longer valid. Sign in again.", GROCY_ACCOUNT_INVALID
    )
