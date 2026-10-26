"""Offline regressions for operation selection, wire validation, and audit safety."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from io import BytesIO
from urllib.parse import parse_qs
from zipfile import ZipFile

import pytest
import requests
import schemathesis
import yaml
from openapi_spec_validator import OpenAPIV32SpecValidator
from urllib3.response import HTTPResponse

from scripts.api_reference.contracts.run import AuditSession, exercise, run_operation
from scripts.api_reference.contracts.selection import Snapshot, operations, select
from scripts.api_reference.contracts.validation import (
    ContractViolation,
    parse_xml,
    validate_body,
    validate_zip,
)


@pytest.fixture
def spec():
    """Provide the real reference, resolved offline."""
    return Snapshot().spec()


def test_openapi32_consumers(spec):
    """The published 3.2 reference validates and exposes every operation to the audit."""
    OpenAPIV32SpecValidator(spec).validate()
    schema = schemathesis.openapi.from_dict(spec)
    discovered = set()
    for result in schema.get_all_operations():
        operation = result.ok()
        discovered.add(f"{operation.method.upper()} {operation.path}")
    assert discovered == set(operations(spec))


@pytest.mark.parametrize(
    ("field", "previous"),
    [
        ("openapi", "3.1.0"),
        ("jsonSchemaDialect", "https://spec.openapis.org/oas/3.1/dialect/base"),
    ],
)
def test_openapi32_migration_selects_all_operations(spec, field, previous):
    """Either version or dialect migration schedules every published route for audit."""
    before = deepcopy(spec)
    before[field] = previous
    assert select(before, spec) == {"selected": sorted(operations(spec)), "removed": []}


def miniature():
    """Create two operations sharing one parameter and only one response schema."""
    return {
        "openapi.yaml": {
            "openapi": "3.2.1",
            "info": {"title": "Test", "version": "1"},
            "servers": [{"url": "https://example.test"}],
            "security": [{"Key": []}],
            "components": {
                "securitySchemes": {"Key": {"type": "apiKey", "in": "query", "name": "key"}}
            },
            "paths": {"/a": {"$ref": "paths.yaml#/~1a"}, "/b": {"$ref": "paths.yaml#/~1b"}},
        },
        "paths.yaml": {
            path: {
                "get": {
                    "parameters": [{"$ref": "shared.yaml#/parameter"}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "shared.yaml#/response"}
                                    if path == "/a"
                                    else {"type": "string"}
                                }
                            }
                        }
                    },
                }
            }
            for path in ("/a", "/b")
        },
        "shared.yaml": {
            "parameter": {"name": "page", "in": "query", "schema": {"type": "integer"}},
            "response": {"type": "object", "properties": {"value": {"type": "string"}}},
            "unused": {"type": "number"},
        },
    }


def write_documents(root, documents):
    """Write small modular specs into a temporary reference directory."""
    root.mkdir(exist_ok=True)
    for name, content in documents.items():
        (root / name).write_text(yaml.safe_dump(content))


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("response", ["GET /a"]),
        ("parameter", ["GET /a", "GET /b"]),
        ("unused", []),
    ],
)
def test_transitive_component_selection(tmp_path, section, expected):
    """A shared file change selects consumers of the changed fragment only."""
    documents = miniature()
    write_documents(tmp_path, documents)
    before = Snapshot(tmp_path).spec()
    documents["shared.yaml"][section]["description"] = "Changed"
    write_documents(tmp_path, documents)
    assert select(before, Snapshot(tmp_path).spec())["selected"] == expected


def test_global_inheritance_and_deletions(tmp_path):
    """Effective global auth/server edits propagate, while root metadata does not."""
    write_documents(tmp_path, miniature())
    original = Snapshot(tmp_path).spec()
    after = deepcopy(original)
    after["info"]["description"] = "Documentation only"
    assert select(original, after)["selected"] == []
    after["components"]["securitySchemes"]["Key"]["name"] = "new-key"
    assert select(original, after)["selected"] == ["GET /a", "GET /b"]
    after = deepcopy(original)
    after["servers"][0]["url"] = "https://changed.test"
    assert select(original, after)["selected"] == ["GET /a", "GET /b"]
    after = deepcopy(original)
    after["jsonSchemaDialect"] = "https://json-schema.org/draft/2020-12/schema"
    assert select(original, after)["selected"] == ["GET /a", "GET /b"]
    after = deepcopy(original)
    del after["paths"]["/a"]
    assert select(original, after) == {"selected": [], "removed": ["GET /a"]}
    assert select(None, after)["selected"] == ["GET /b"]


def test_override_inheritance(tmp_path):
    """Operation-level overrides shield operations from unrelated global edits."""
    write_documents(tmp_path, miniature())
    before = Snapshot(tmp_path).spec()
    before["paths"]["/a"]["get"]["security"] = []
    before["paths"]["/a"]["get"]["servers"] = [{"url": "https://fixed.test"}]
    after = deepcopy(before)
    after["servers"][0]["url"] = "https://changed.test"
    after["components"]["securitySchemes"]["Key"]["name"] = "new-key"
    assert select(before, after)["selected"] == ["GET /b"]


def test_git_full_push_and_bad_revision(tmp_path):
    """A multi-commit push compares its true before SHA, not HEAD's parent."""

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Contract test")
    git("config", "commit.gpgsign", "false")
    root = tmp_path / "api_reference"
    documents = miniature()
    write_documents(root, documents)
    git("add", ".")
    git("commit", "-qm", "Initial")
    base = git("rev-parse", "HEAD")
    documents["shared.yaml"]["response"]["description"] = "Changed in first pushed commit"
    write_documents(root, documents)
    git("add", ".")
    git("commit", "-qm", "Contract")
    (tmp_path / "README.md").write_text("Unrelated final commit")
    git("add", ".")
    git("commit", "-qm", "Docs")
    head = git("rev-parse", "HEAD")
    assert select(Snapshot(root, base).spec(), Snapshot(root, head).spec())["selected"] == [
        "GET /a"
    ]
    with pytest.raises(subprocess.CalledProcessError):
        Snapshot(root, "1" * 40)


@pytest.mark.parametrize("reference", ["https://example.test/spec", "../outside.yaml", "#/cycle"])
def test_unsafe_or_cyclic_reference_fails(tmp_path, reference):
    """An unsupported reference fails selection instead of silently skipping coverage."""
    write_documents(tmp_path, {"openapi.yaml": {"cycle": {"$ref": reference}}})
    with pytest.raises(ValueError):
        Snapshot(tmp_path).spec()


def test_json_and_xml_types_and_errors(spec):
    """XML strings and repeated records retain their types; malformed JSON fails."""
    definition = spec["paths"]["/list.xml"]["get"]["responses"]["200"]
    schema = definition["content"]["application/xml"]["schema"]
    body = b"<result><status>000</status><message/><page_no>1</page_no><list><corp_code>00126380</corp_code></list><list><corp_code>00000001</corp_code></list></result>"
    value = parse_xml(body, schema)
    assert value["page_no"] == 1
    assert value["list"][0]["corp_code"] == "00126380"
    assert len(value["list"]) == 2
    assert (
        validate_body(
            b"<result><status>013</status><message>No data</message></result>",
            "application/xml",
            definition,
        )
        == "013"
    )
    json_definition = spec["paths"]["/list.json"]["get"]["responses"]["200"]
    with pytest.raises(ContractViolation):
        validate_body(
            b'{"status":"000","message":"OK","page_no":"1"}', "application/json", json_definition
        )
    with pytest.raises(ContractViolation):
        validate_body(b"<html/>", "text/html", definition)
    with pytest.raises(ContractViolation):
        parse_xml(b"<wrong><status>013</status><message/></wrong>", schema)
    with pytest.raises(ContractViolation):
        parse_xml(b'<!DOCTYPE result [<!ENTITY x "expanded">]><result>&x;</result>', schema)


def test_zip_and_archive_member(spec):
    """ZIP routes need actual archives and corporation members must match the schema."""
    response = spec["paths"]["/corpCode.xml"]["get"]["responses"]["200"]
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr(
            "CORPCODE.xml", "<result><list><corp_code>00126380</corp_code></list></result>"
        )
    assert validate_body(data.getvalue(), "application/zip", response) == "ZIP"
    assert validate_body(data.getvalue(), "application/x-msdownload", response) == "ZIP"
    with pytest.raises(ContractViolation):
        validate_zip(b"<result><status>013</status></result>")


def response_for(payload, status=200, media="application/json"):
    """Construct a wire response without a network connection."""
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media
    response.raw = HTTPResponse(headers={"Content-Type": media})
    response._content = json.dumps(payload).encode()
    response._content_consumed = True
    response.request = requests.Request("GET", "https://example.test").prepare()
    from datetime import timedelta

    response.elapsed = timedelta(0)
    return response


@pytest.mark.parametrize(
    "name",
    [
        "GET /company.json",
        "GET /fnlttMultiAcnt.json",
        "GET /fnlttCmpnyIndx.json",
    ],
)
def test_real_schemathesis_generation_and_failure_redaction(spec, name):
    """Exercise actual strategies/checks without network or credential-bearing reports."""
    spec["security"] = []
    schema = schemathesis.openapi.from_dict(spec)
    definition = operations(spec)[name]
    required = [p["name"] for p in definition["parameters"] if p.get("required")]

    class Session(requests.Session):
        def request(self, method, url, **kwargs):
            query = kwargs["params"]
            if isinstance(query, str):
                query = parse_qs(query)
            if not query.get("crtfc_key") or any(not query.get(name) for name in required):
                return response_for({"status": "100", "message": "Missing parameter"})
            return response_for({"status": "000", "message": "OK"})

    with Session() as session:
        records = run_operation(schema, name, definition, session, "secret" * 6 + "1234", 2, 123)
    assert len(records) == 5
    assert not any("failure" in r for r in records), records
    assert "secret" not in json.dumps(records)

    class BrokenCase:
        query = {"crtfc_key": "secret", "corp_code": "00126380"}

        def call(self, **kwargs):
            raise requests.ConnectionError("URL contains crtfc_key=secret")

    record = exercise(BrokenCase(), definition, None, "secret", "example")
    assert "secret" not in json.dumps(record)
    assert "ConnectionError" in record["failure"]


def test_transport_failure_and_blocking_status(spec):
    """Default responses and quota envelopes must not make an unavailable audit pass."""
    definition = operations(spec)["GET /company.json"]

    class Case:
        query = {}

        def __init__(self, status, code):
            self.status, self.code = status, code

        def call(self, **kwargs):
            return schemathesis.Response.from_requests(
                response_for({"status": self.code, "message": "Diagnostic"}, self.status),
                verify=True,
            )

        def validate_response(self, *args, **kwargs):
            pass

    for status, code in [(503, "800"), (200, "020"), (200, "010")]:
        record = exercise(Case(status, code), definition, None, "secret", "example")
        assert "failure" in record

    redirect = Case(302, "100")
    xbrl = operations(spec)["GET /fnlttXbrl.xml"]
    record = exercise(redirect, xbrl, None, "secret", "missing-required")
    assert "failure" not in record
    assert record["http_status"] == 302
    # This observed redirect is specific to XBRL; default must not accept it elsewhere.
    assert "failure" in exercise(redirect, definition, None, "secret", "missing-required")


def test_request_budget_and_host_pinning(monkeypatch):
    """Bound requests even if a transport tries to retry or use a different server."""
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: response_for({}))
    with AuditSession(0, 1, 10) as session:
        with pytest.raises(ContractViolation):
            session.request("GET", "https://elsewhere.test/engapi/company.json")
        session.request("GET", "https://engopendart.fss.or.kr/engapi/company.json")
        with pytest.raises(ContractViolation):
            session.request("GET", "https://engopendart.fss.or.kr/engapi/company.json")
        assert session.calls == 1


def test_empty_selection_needs_no_credentials(tmp_path):
    """A removal-only or irrelevant diff succeeds without loading an API key."""
    selection = tmp_path / "selection.json"
    report = tmp_path / "report.json"
    selection.write_text(json.dumps({"selected": [], "removed": ["GET /deleted.json"]}))
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("OPENDART_API_KEY", "OPENDART_API__API_KEY")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.api_reference.contracts.run",
            "--selection",
            str(selection),
            "--report",
            str(report),
        ],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text())["complete"] is True
    assert json.loads(report.read_text())["operations"] == {}


def test_missing_key_fails_selected_audit(tmp_path):
    """Configured operations cannot silently skip when CI lacks its secret."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("OPENDART_API_KEY", "OPENDART_API__API_KEY")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.api_reference.contracts.run",
            "--operation",
            "GET /company.json",
            "--report",
            str(tmp_path / "report.json"),
        ],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Set a 40-character" in result.stderr
    assert json.loads((tmp_path / "report.json").read_text())["complete"] is False


def test_parameterless_archive_not_downloaded_twice(spec):
    """Input generation does not repeat an archive with no data parameters."""
    from unittest.mock import patch

    spec["security"] = []
    schema = schemathesis.openapi.from_dict(spec)
    with patch(
        "scripts.api_reference.contracts.run.exercise", return_value={"application_status": "ZIP"}
    ) as call:
        run_operation(
            schema,
            "GET /corpCode.xml",
            operations(spec)["GET /corpCode.xml"],
            None,
            "secret",
            2,
            123,
        )
    assert call.call_count == 2
