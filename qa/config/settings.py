"""QA run configuration, read from the environment only.

Nothing here has a default that points at a shared or production system. The
database and Redis must be disposable: the harness drops and recreates the
database schema and flushes the Redis database it is given.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
CONTRACT_PATH = REPO_ROOT / "contracts" / "openapi.yaml"


class UnsafeTargetError(RuntimeError):
    """Raised when a configured target does not look disposable."""


_TARGET_PARAMS = {"dbname", "host", "hostaddr", "service", "port", "database"}


@dataclass(frozen=True)
class QaSettings:
    database_url: str | None
    redis_url: str | None
    backend_python: str
    artifacts_dir: Path
    allow_destructive: bool
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def services_configured(self) -> bool:
        return bool(self.database_url and self.redis_url)

    def assert_disposable(self) -> None:
        """Refuse to run destructive setup against anything that is not clearly a QA target."""
        if not self.services_configured:
            raise UnsafeTargetError("QA_DATABASE_URL and QA_REDIS_URL must both be set")
        db = urlparse(self.database_url or "")
        db_name = db.path.lstrip("/")
        overrides = {k.lower() for k in parse_qs(db.query, keep_blank_values=True)} & _TARGET_PARAMS
        if overrides:
            # libpq lets these query parameters replace the host or database in the URL path.
            raise UnsafeTargetError(f"QA_DATABASE_URL must not override the target via {sorted(overrides)}")
        if not db_name.startswith("qa_") and not self.allow_destructive:
            raise UnsafeTargetError(f"database name {db_name!r} must start with 'qa_' (or set QA_ALLOW_DESTRUCTIVE=1)")
        if db.hostname not in ("localhost", "127.0.0.1", "postgres", "::1") and not self.allow_destructive:
            raise UnsafeTargetError("QA database must be local or a CI service container")
        rd = urlparse(self.redis_url or "")
        if rd.hostname not in ("localhost", "127.0.0.1", "redis", "::1") and not self.allow_destructive:
            raise UnsafeTargetError("QA Redis must be local or a CI service container")


def load() -> QaSettings:
    return QaSettings(
        database_url=os.environ.get("QA_DATABASE_URL"),
        redis_url=os.environ.get("QA_REDIS_URL"),
        backend_python=os.environ.get("QA_BACKEND_PYTHON", "python"),
        artifacts_dir=Path(os.environ.get("QA_ARTIFACTS_DIR", REPO_ROOT / "qa" / "artifacts")),
        allow_destructive=os.environ.get("QA_ALLOW_DESTRUCTIVE") == "1",
    )
