"""HTTP client that behaves like a browser for the auth cookies, and checks the contract.

`__Host-` cookies are `Secure`, so a plain HTTP client would drop them on the
http://127.0.0.1 test server. This client keeps its own cookie jar from the raw
`Set-Cookie` fields (which also lets tests assert each attribute), sends
`X-CSRF-Token` like the frontend does, validates every response against the
contract, and keeps a redacted exchange log as evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any

import httpx

from qa.core.contract import Violation, load_contract
from qa.core.redaction import redact

SESSION_COOKIE = "__Host-tradeo_session"
CSRF_COOKIE = "__Host-tradeo_csrf"
API = "/api/v1"


@dataclass
class SetCookie:
    name: str
    value: str
    attrs: dict[str, str]
    raw: str

    @property
    def cleared(self) -> bool:
        return self.attrs.get("max-age") == "0" or self.value == ""


def parse_set_cookie(raw: str) -> SetCookie:
    jar: SimpleCookie = SimpleCookie()
    jar.load(raw)
    ((name, morsel),) = jar.items()
    attrs = {k.lower(): str(v) for k, v in morsel.items() if v not in ("", False)}
    # SimpleCookie reports flags as True; normalise for assertions.
    for flag in ("secure", "httponly"):
        if morsel[flag]:
            attrs[flag] = "true"
    return SetCookie(name=name, value=morsel.value, attrs=attrs, raw=raw)


class ContractViolationError(AssertionError):
    pass


@dataclass
class Exchange:
    method: str
    path: str
    status: int
    request_body: str
    response_body: str


@dataclass
class ApiClient:
    base_url: str
    name: str = "client"
    strict_contract: bool = True
    forwarded_for: str | None = None
    cookies: dict[str, str] = field(default_factory=dict)
    csrf_token: str | None = None
    exchanges: list[Exchange] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    last_set_cookies: list[SetCookie] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._http = httpx.Client(base_url=self.base_url, timeout=15.0)

    def close(self) -> None:
        self._http.close()

    # -- transport -------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        content: bytes | None = None,
        csrf: bool | str = True,
        headers: dict[str, str] | None = None,
        check_contract: bool | None = None,
    ) -> httpx.Response:
        url = path if path.startswith("/health") or path.startswith(API) else API + path
        hdrs = {"Accept": "application/json"}
        if self.cookies:
            hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if csrf is True and self.csrf_token and method.upper() not in ("GET", "HEAD"):
            hdrs["X-CSRF-Token"] = self.csrf_token
        elif isinstance(csrf, str):
            hdrs["X-CSRF-Token"] = csrf
        if self.forwarded_for:
            hdrs["X-Forwarded-For"] = self.forwarded_for
        if headers:
            hdrs.update(headers)
        resp = self._http.request(method, url, json=json_body, content=content, headers=hdrs)
        self._absorb_cookies(resp)
        body = self._body(resp)
        self.exchanges.append(
            Exchange(
                method.upper(),
                url,
                resp.status_code,
                redact(json.dumps(json_body)) if json_body is not None else "",
                redact(resp.text[:2000]),
            )
        )
        strict = self.strict_contract if check_contract is None else check_contract
        if strict:
            found = load_contract().validate(method, url, resp.status_code, resp.headers.get("content-type"), body)
            if found:
                self.violations.extend(found)
                raise ContractViolationError("; ".join(map(str, found)))
        return resp

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, json_body: Any = None, **kw: Any) -> httpx.Response:
        return self.request("POST", path, json_body=json_body, **kw)

    def put(self, path: str, json_body: Any = None, **kw: Any) -> httpx.Response:
        return self.request("PUT", path, json_body=json_body, **kw)

    def delete(self, path: str, **kw: Any) -> httpx.Response:
        return self.request("DELETE", path, **kw)

    @staticmethod
    def _body(resp: httpx.Response) -> Any:
        if "application/json" in resp.headers.get("content-type", ""):
            try:
                return resp.json()
            except ValueError:
                return None
        return None

    def _absorb_cookies(self, resp: httpx.Response) -> None:
        self.last_set_cookies = [parse_set_cookie(raw) for raw in resp.headers.get_list("set-cookie")]
        for c in self.last_set_cookies:
            if c.cleared:
                self.cookies.pop(c.name, None)
            else:
                self.cookies[c.name] = c.value

    # -- auth helpers ------------------------------------------------------
    def fetch_csrf(self) -> dict[str, Any]:
        r = self.get("/auth/csrf")
        assert r.status_code == 200, r.text
        data = r.json()
        self.csrf_token = data["csrfToken"]
        return data

    def adopt_login(self, resp: httpx.Response) -> dict[str, Any]:
        data = resp.json()
        self.csrf_token = data["csrfToken"]
        return data

    def evidence(self) -> str:
        lines = [f"# exchanges for {self.name}"]
        for e in self.exchanges[-30:]:
            lines.append(f"{e.method} {e.path} -> {e.status}\n  req: {e.request_body}\n  res: {e.response_body}")
        return "\n".join(lines)
