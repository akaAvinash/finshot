"""A tiny local SMTP server for tests: STARTTLS required, AUTH refused before TLS,
self-signed certificate. Not for production."""

from __future__ import annotations

import base64
import datetime as dt
import socket
import ssl
import tempfile
import threading
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class FakeSmtpServer:
    def __init__(
        self,
        username: str = "mailbox",
        password: str = "s3cret-pw",  # noqa: S107
    ) -> None:
        self.username, self.password = username, password
        self.messages: list[str] = []
        self.auth_before_tls_attempts = 0
        self.fail_after_auth = False
        self._dir = tempfile.TemporaryDirectory()
        cert, key = _certificate(Path(self._dir.name))
        self._server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._server_ctx.load_cert_chain(cert, key)
        self.client_context = ssl.create_default_context(cafile=str(cert))
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port: int = self._sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> FakeSmtpServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop = True
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        except OSError:
            pass
        self._thread.join(timeout=5)
        self._sock.close()
        self._dir.cleanup()

    def _serve(self) -> None:
        while not self._stop:
            conn, _ = self._sock.accept()
            if self._stop:
                conn.close()
                return
            try:
                self._session(conn)
            except (OSError, ssl.SSLError, ValueError):
                pass
            finally:
                conn.close()

    def _session(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        io = conn.makefile("rwb", buffering=0)

        def say(line: str) -> None:
            io.write((line + "\r\n").encode())

        def read() -> str:
            return io.readline().decode(errors="replace").rstrip("\r\n")

        tls = False
        authed = False
        say("220 fake ESMTP")
        while True:
            line = read()
            if not line:
                return
            verb = line.split(" ", 1)[0].upper()
            if verb == "EHLO":
                say("250-fake")
                if tls:
                    say("250-AUTH PLAIN")
                else:
                    say("250-STARTTLS")
                say("250 OK")
            elif verb == "STARTTLS":
                say("220 go ahead")
                secure = self._server_ctx.wrap_socket(conn, server_side=True)
                io = secure.makefile("rwb", buffering=0)
                conn = secure
                tls = True
            elif verb == "AUTH":
                if not tls:
                    self.auth_before_tls_attempts += 1
                    say("530 Must issue a STARTTLS command first")
                    continue
                _, _, token = line.split(" ", 2)
                _, user, pw = base64.b64decode(token).decode().split("\0")
                ok = user == self.username and pw == self.password
                authed = ok
                say("235 ok" if ok else "535 bad credentials secret-server-text")
            elif verb in ("MAIL", "RCPT"):
                if not authed:
                    say("530 auth first")
                elif self.fail_after_auth:
                    say("554 rejected secret-server-text")
                else:
                    say("250 OK")
            elif verb == "DATA":
                say("354 end with .")
                data = []
                while (row := read()) != ".":
                    data.append(row)
                self.messages.append("\n".join(data))
                say("250 queued")
            elif verb == "QUIT":
                say("221 bye")
                return
            else:
                say("250 OK")
