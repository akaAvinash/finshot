"""Response validation against contracts/openapi.yaml (OpenAPI 3.1 = JSON Schema 2020-12).

The contract on main is the specification. Every response the QA client sees
is checked: the status code must be documented for that operation and a JSON
body must match the documented schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from qa.config.settings import CONTRACT_PATH

_DOC_URI = "urn:tradeo:contract"


@dataclass(frozen=True)
class Violation:
    operation: str
    status: int
    problem: str

    def __str__(self) -> str:
        return f"{self.operation} -> {self.status}: {self.problem}"


class Contract:
    def __init__(self, path: Path = CONTRACT_PATH) -> None:
        self.doc: dict[str, Any] = yaml.safe_load(path.read_text())
        self.version = str(self.doc.get("info", {}).get("version"))
        self._registry = Registry().with_resource(
            _DOC_URI, Resource.from_contents(self.doc, default_specification=DRAFT202012)
        )
        self._routes: list[tuple[re.Pattern[str], str, str]] = []
        for template, item in self.doc.get("paths", {}).items():
            regex = "^" + re.sub(r"\{[^/]+\}", r"[^/]+", template) + "$"
            for method in item:
                if method in {"get", "post", "put", "patch", "delete"}:
                    self._routes.append((re.compile(regex), method, template))

    def operation(self, method: str, path: str) -> tuple[str, dict[str, Any]] | None:
        path = path.split("?", 1)[0]
        for regex, m, template in self._routes:
            if m == method.lower() and regex.match(path):
                return template, self.doc["paths"][template][m]
        return None

    def operation_ids(self) -> dict[str, tuple[str, str]]:
        out = {}
        for template, item in self.doc.get("paths", {}).items():
            for method, op in item.items():
                if isinstance(op, dict) and "operationId" in op:
                    out[op["operationId"]] = (method.upper(), template)
        return out

    def _resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in node:
            ref = node["$ref"]
            assert ref.startswith("#/"), ref
            target: Any = self.doc
            for part in ref[2:].split("/"):
                target = target[part]
            node = target
        return node

    def validate(self, method: str, path: str, status: int, content_type: str | None, body: Any) -> list[Violation]:
        found = self.operation(method, path)
        if found is None:
            return [Violation(f"{method} {path}", status, "path/method is not in the contract")]
        template, op = found
        name = op.get("operationId", f"{method} {template}")
        responses = op.get("responses", {})
        spec = responses.get(str(status)) or responses.get("default")
        if spec is None:
            return [Violation(name, status, f"status {status} is not documented")]
        spec = self._resolve(spec)
        content = spec.get("content") or {}
        if not content:
            return []
        if not content_type or "application/json" not in content_type:
            if "application/json" in content:
                return [Violation(name, status, f"expected JSON, got {content_type!r}")]
            return []
        schema = content.get("application/json", {}).get("schema")
        if schema is None:
            return []
        validator = _validator(self, _schema_key(schema))
        return [
            Violation(name, status, f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}")
            for e in validator.iter_errors(body)
        ]


def _schema_key(schema: dict[str, Any]) -> str:
    return yaml.safe_dump(schema, sort_keys=True)


_VALIDATORS: dict[str, Draft202012Validator] = {}


def _validator(contract: Contract, key: str) -> Draft202012Validator:
    if key not in _VALIDATORS:
        schema = yaml.safe_load(key)
        rewritten = _rewrite_refs(schema)
        _VALIDATORS[key] = Draft202012Validator(rewritten, registry=contract._registry, format_checker=FormatChecker())
    return _VALIDATORS[key]


def _rewrite_refs(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: (_DOC_URI + v if k == "$ref" and isinstance(v, str) and v.startswith("#") else _rewrite_refs(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    return node


@lru_cache(maxsize=1)
def load_contract() -> Contract:
    return Contract()
