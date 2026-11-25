"""System under test: the real backend, started as a separate process.

The QA framework never imports product code (`app.*`). It drives the backend
the way an operator and a client would: alembic and the operator CLI as
subprocesses, and the API over HTTP from a uvicorn process.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

from qa.config.settings import BACKEND_DIR, QaSettings


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def sync_db_url(url: str) -> str:
    """postgresql+asyncpg://... -> postgresql://... for psql-style tools."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(scheme="postgresql"))


def run_sql(database_url: str, sql: str) -> str:
    """Run SQL through psql (no product code involved)."""
    proc = subprocess.run(
        ["psql", sync_db_url(database_url), "-v", "ON_ERROR_STOP=1", "-qAtc", sql],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed: {proc.stderr.strip()[:500]}")
    return proc.stdout


@dataclass
class Backend:
    settings: QaSettings
    env_overrides: dict[str, str] = field(default_factory=dict)
    smtp_port: int | None = None
    smtp_username: str = ""
    smtp_password: str = ""
    log_path: Path | None = None
    port: int = field(default_factory=free_port)
    _proc: subprocess.Popen[bytes] | None = None
    _log_file: object = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def env(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
            "APP_ENV": "test",
            "LOG_FORMAT": "json",
            "LOG_LEVEL": "INFO",
            "DATABASE_URL": self.settings.database_url or "",
            "REDIS_URL": self.settings.redis_url or "",
            "ALLOWED_HOSTS": "127.0.0.1,localhost",
            # Synthetic per-run key. Never a real secret.
            "AUTH_SECRET_KEY": _RUN_SECRET,
            "PUBLIC_ORIGIN": "https://qa.tradeo.invalid",
            "OTP_PROVIDER": "disabled",
            "OTP_EMAIL_PROVIDER": "smtp" if self.smtp_port else "disabled",
            "SMTP_HOST": "127.0.0.1",
            "SMTP_PORT": str(self.smtp_port or 25),
            "SMTP_USERNAME": self.smtp_username,
            "SMTP_PASSWORD": self.smtp_password,
            "SMTP_FROM": "no-reply@qa.tradeo.invalid",
            "SMTP_STARTTLS": "false",
            "SMTP_TIMEOUT_SECONDS": "3",
            # Workers are not under test in the auth suite; keep the process quiet.
            "BACKTEST_WORKER_ENABLED": "false",
            "PAPER_WORKER_ENABLED": "false",
            "AGENT_WORKER_ENABLED": "false",
            "ALERT_WORKER_ENABLED": "false",
        }
        if not self.smtp_port:
            for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
                env.pop(key)
        env.update(self.env_overrides)
        return env

    def _python(self) -> str:
        return self.settings.backend_python

    def migrate(self) -> None:
        proc = subprocess.run(
            [self._python(), "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"alembic upgrade failed:\n{proc.stderr[-2000:]}")

    def admin(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Operator CLI (`python -m app.auth.admin ...`), exactly as documented in AUTH.md."""
        return subprocess.run(
            [self._python(), "-m", "app.auth.admin", *args],
            cwd=BACKEND_DIR,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def start(self, timeout: float = 40.0) -> None:
        assert self._proc is None, "already started"
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self.log_path.open("ab")
        self._proc = subprocess.Popen(
            [
                self._python(),
                "-m",
                "uvicorn",
                "app.asgi:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--no-access-log",
            ],
            cwd=BACKEND_DIR,
            env=self.env(),
            stdout=self._log_file or subprocess.DEVNULL,  # type: ignore[arg-type]
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"backend exited with {self._proc.returncode}; see {self.log_path}")
            try:
                r = httpx.get(f"{self.base_url}/health/live", timeout=1.0)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        self.stop()
        raise RuntimeError(f"backend did not become live within {timeout}s")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        if self._log_file:
            self._log_file.close()  # type: ignore[attr-defined]
            self._log_file = None

    def logs(self) -> str:
        if self.log_path and self.log_path.exists():
            return self.log_path.read_text(errors="replace")
        return ""


_RUN_SECRET = secrets.token_hex(32)


def reset_database(settings: QaSettings) -> None:
    """Drop and recreate the public schema of the disposable QA database."""
    settings.assert_disposable()
    run_sql(settings.database_url or "", "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")


def flush_redis(settings: QaSettings) -> None:
    settings.assert_disposable()
    import redis

    redis.Redis.from_url(settings.redis_url or "").flushdb()
