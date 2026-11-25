"""Minimal TCP fault-injection proxy (the Toxiproxy idea, stdlib only).

Put it between the backend and PostgreSQL or Redis, then `cut()` to drop every
connection and refuse new ones (an outage), and `restore()` to recover. No
external binary or service is needed, so it runs the same locally and in CI.
"""

from __future__ import annotations

import socket
import threading

from qa.core.sut import free_port


class TcpProxy:
    def __init__(self, upstream_host: str, upstream_port: int) -> None:
        self.upstream = (upstream_host, upstream_port)
        self.port = free_port()
        self._server: socket.socket | None = None
        self._conns: list[socket.socket] = []
        self._lock = threading.Lock()
        self._up = True
        self._stop = False

    def start(self) -> None:
        self._listen()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _listen(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.port))
        srv.listen(64)
        srv.settimeout(0.2)
        self._server = srv

    def _accept_loop(self) -> None:
        while not self._stop:
            try:
                client, _ = self._server.accept()  # type: ignore[union-attr]
            except (TimeoutError, OSError):
                continue
            if not self._up:
                client.close()
                continue
            try:
                upstream = socket.create_connection(self.upstream, timeout=5)
            except OSError:
                client.close()
                continue
            # The 5 s limit is for connecting only; an idle healthy link must stay open.
            upstream.settimeout(None)
            with self._lock:
                # cut()/stop() may have run while we were connecting: never register then.
                if not self._up or self._stop:
                    client.close()
                    upstream.close()
                    continue
                self._conns += [client, upstream]
            pair = {"open": 2, "lock": threading.Lock(), "socks": (client, upstream)}
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(a, b, pair), daemon=True).start()

    def _pipe(self, src: socket.socket, dst: socket.socket, pair: dict) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            # Close only after both directions have stopped reading. Closing a
            # socket another thread is blocked on lets the OS reuse its file
            # descriptor for an unrelated socket in this process (for example
            # the test's own HTTP connection), which the blocked recv would
            # then read from.
            with pair["lock"]:
                pair["open"] -= 1
                last = pair["open"] == 0
            if last:
                with self._lock:
                    for s in pair["socks"]:
                        if s in self._conns:
                            self._conns.remove(s)
                        s.close()

    def cut(self) -> None:
        with self._lock:
            self._up = False
            for s in list(self._conns):
                try:
                    s.shutdown(socket.SHUT_RDWR)  # wakes the pipe threads; they close
                except OSError:
                    pass

    def restore(self) -> None:
        self._up = True

    def stop(self) -> None:
        self._stop = True
        self.cut()
        if self._server:
            self._server.close()
