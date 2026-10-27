import os
from dataclasses import dataclass


class MissingConfig(Exception):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingConfig(f"{name} is not set")
    return value


@dataclass(frozen=True)
class Settings:
    directus_url: str
    directus_token: str
    password: str
    session_secret: str
    cookie_secure: bool = True
    poll_minutes: int = 30
    poll_pages: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            directus_url=_required("DIRECTUS_URL").rstrip("/"),
            directus_token=_required("DIRECTUS_TOKEN"),
            password=_required("SWIPE_PASSWORD"),
            session_secret=_required("SWIPE_SESSION_SECRET"),
            cookie_secure=os.environ.get("SWIPE_COOKIE_SECURE", "true").lower() != "false",
            poll_minutes=int(os.environ.get("POLL_MINUTES", "30")),
            poll_pages=int(os.environ.get("POLL_PAGES", "3")),
        )
