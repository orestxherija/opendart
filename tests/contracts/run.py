"""Run bounded Schemathesis cases against the English OpenDART GET operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

import requests
import schemathesis
from hypothesis import HealthCheck, Phase, given, seed, settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import content_type_conformance, status_code_conformance

from tests.contracts.selection import Snapshot, operations
from tests.contracts.validation import ContractViolation, validate_body

BASE_URL = "https://engopendart.fss.or.kr/engapi"
BLOCKING_STATUSES = {"010", "011", "012", "020", "800", "900", "901"}


class AuditSession(requests.Session):
    """Limit every actual request, including transport retries, and response sizes."""

    def __init__(self, interval, max_requests, max_seconds):
        """Set fixed request, pacing, and elapsed-time limits for one audit."""
        super().__init__()
        self.interval = interval
        self.max_requests = max_requests
        self.deadline = time.monotonic() + max_seconds
        self.calls = 0
        self.last_call = 0

    def request(self, method, url, **kwargs):
        """Never follow redirects or send credentials outside the documented host."""
        target = urlsplit(url)
        if (
            method.upper() != "GET"
            or target.scheme != "https"
            or target.netloc != "engopendart.fss.or.kr"
            or not target.path.startswith("/engapi/")
        ):
            raise ContractViolation("Audit target must be an English OpenDART GET operation")
        delay = max(0, self.last_call + self.interval - time.monotonic())
        if self.calls >= self.max_requests or time.monotonic() + delay >= self.deadline:
            raise ContractViolation("Audit request/time budget exhausted")
        time.sleep(delay)
        self.calls += 1
        self.last_call = time.monotonic()
        response_deadline = min(self.deadline, self.last_call + 300)
        kwargs.update(stream=True, allow_redirects=False)
        with super().request(method, url, **kwargs) as response:
            chunks, size = [], 0
            # read1 returns available bytes instead of waiting for a whole
            # chunk to fill, so a trickling download cannot evade the deadline.
            while chunk := response.raw.read1(64 * 1024, decode_content=True):
                size += len(chunk)
                if size > 25 * 1024 * 1024 or time.monotonic() >= response_deadline:
                    raise ContractViolation("Response exceeds audit size/time limit")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
            return response


def example_query(operation):
    """Use the reference's public parameter examples, including CSV arrays."""
    return {
        parameter["name"]: deepcopy(parameter.get("example", parameter["schema"].get("default")))
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "query"
        and ("example" in parameter or "default" in parameter["schema"])
    }


def exercise(case, definition, session, key, kind):
    """Record only public query inputs, status, types, hashes, and safe failures."""
    case.query = {name: value for name, value in (case.query or {}).items() if name != "crtfc_key"}
    # Schemathesis uses string subclasses for CSV parameters which cannot be
    # deep-copied; normalize only the report, preserving wire serialization.
    record = {"kind": kind, "query": json.loads(json.dumps(case.query))}
    try:
        response = case.call(
            base_url=BASE_URL,
            session=session,
            params={"crtfc_key": key} if kind != "missing-auth" else {},
            headers={"Accept-Encoding": "identity"},
            timeout=20,
        )
        media = response.headers.get("content-type", [""])[0].split(";", 1)[0].strip().lower()
        record.update(
            http_status=response.status_code,
            media_type=media,
            body_bytes=len(response.content),
            body_sha256=hashlib.sha256(response.content).hexdigest(),
        )
        # The default transport response must not turn an outage into a pass.
        # Explicitly observed errors such as the XBRL 302 remain testable.
        expected = definition["responses"].get(str(response.status_code))
        if response.status_code >= 500 or expected is None:
            raise ContractViolation("Unexpected HTTP status; no explicit non-server-error response")
        status = None
        if "content" in expected:
            status = validate_body(response.content, media, expected)
            record["application_status"] = status
        case.validate_response(
            response, checks=[not_a_server_error, status_code_conformance, content_type_conformance]
        )
        if kind == "missing-auth" and status in ("000", "ZIP"):
            raise ContractViolation("Operation succeeded without the required API key")
        if kind == "missing-required" and status in ("000", "ZIP"):
            raise ContractViolation("Operation succeeded without a required query parameter")
        if kind != "missing-auth" and status in BLOCKING_STATUSES:
            raise ContractViolation(
                "Credential, quota, or service failure prevents contract verification"
            )
    except ContractViolation as exc:
        record["failure"] = str(exc)
    except Exception as exc:
        # Schemathesis/requests exceptions may contain credential-bearing curl commands.
        record["failure"] = f"Request or Schemathesis validation failed ({type(exc).__name__})"
    return record


def run_operation(schema, name, definition, session, key, examples, random_seed):
    """Exercise examples, missing credentials/parameters, and generated valid shapes."""
    method, path = name.split(" ", 1)
    operation = schema[path][method]
    query = example_query(definition)
    records = []

    def run_case(case, kind):
        record = exercise(case, definition, session, key, kind)
        records.append(record)
        return record.get("application_status") not in BLOCKING_STATUSES

    if not run_case(operation.Case(query=deepcopy(query)), "example"):
        return records
    run_case(operation.Case(query=deepcopy(query)), "missing-auth")
    required = [
        p["name"]
        for p in definition.get("parameters", [])
        if p["in"] == "query" and p.get("required")
    ]
    if required:
        run_case(
            operation.Case(query={k: v for k, v in query.items() if k != required[0]}),
            "missing-required",
        )
    # The corporation archive has no data parameters: fuzzing would only
    # download the identical multi-megabyte file again.
    if examples and definition.get("parameters"):

        @seed(random_seed)
        @settings(
            max_examples=examples,
            database=None,
            deadline=None,
            phases=[Phase.generate],
            suppress_health_check=[HealthCheck.too_slow],
        )
        @given(operation.as_strategy())
        def generated(case):
            # Collect failures rather than shrinking/replaying against a third-party API.
            run_case(case, "generated")

        try:
            generated()
        except Exception as exc:
            records.append(
                {"kind": "generation", "failure": f"Generation failed ({type(exc).__name__})"}
            )
    return records


def write_report(path, report):
    """Persist progress after every operation so interrupted audits remain reviewable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    write_summary(path, report)


def write_summary(path, report):
    """Summarize coverage and safe failure locations for the Actions run."""
    failures = sum("failure" in r for records in report["operations"].values() for r in records)
    lines = [
        "# OpenDART contract findings",
        "",
        f"Operations checked: {len(report["operations"])}/{len(report["selected"])}. "
        f"Requests: {report.get("request_count", 0)}. "
        f"Failures: {failures}.",
        "",
    ]
    if not report["complete"]:
        lines.append(
            "**Incomplete audit.** Inspect the job log and report before drawing conclusions."
        )
    for name, records in report["operations"].items():
        for record in records:
            if "failure" in record:
                lines.append(f"- `{name}` ({record["kind"]}): {record["failure"]}")
    gaps = report.get("success_not_observed", [])
    if gaps:
        lines.extend(
            ["", "Success payload not observed (error responses alone do not verify it):", ""]
        )
        lines.extend(f"- `{name}`" for name in gaps)
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    """Audit all routes or an exact selection, failing on mismatches or blocked coverage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--operation", action="append", help='Exact name, e.g. "GET /company.json"')
    parser.add_argument("--report", type=Path, default=Path("contract-results/report.json"))
    parser.add_argument("--examples", type=int, default=2, choices=range(21))
    parser.add_argument("--seed", type=int, default=20261020)
    args = parser.parse_args()
    spec = Snapshot().spec()
    definitions = operations(spec)
    selected = (
        json.loads(args.selection.read_text())["selected"]
        if args.selection
        else sorted(definitions)
    )
    if args.operation:
        selected = args.operation
    if len(selected) != len(set(selected)) or set(selected) - definitions.keys():
        parser.error("Selection contains duplicate or unknown operations")
    if any(not name.startswith("GET ") for name in selected):
        parser.error("The live audit only supports GET operations")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "schemathesis": version("schemathesis"),
        "spec_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
        "seed": args.seed,
        "generated_examples_per_operation": args.examples,
        "selected": selected,
        "operations": {},
        "complete": not selected,
    }
    write_report(args.report, report)
    if not selected:
        print("No changed operations; no API calls needed.")
        return
    key = os.environ.get("OPENDART_API__API_KEY") or os.environ.get("OPENDART_API_KEY")
    if not key or len(key) != 40:
        parser.error("Set a 40-character OPENDART_API__API_KEY (or OPENDART_API_KEY)")
    if any(definitions[name]["servers"] != spec["servers"] for name in selected) or (
        len(spec["servers"]) != 1 or spec["servers"][0]["url"] != BASE_URL
    ):
        parser.error("The audit is restricted to the documented English OpenDART server")
    # Auth is injected at call time and kept out of Hypothesis examples/databases.
    test_spec = deepcopy(spec)
    test_spec["security"] = []
    for path_item in test_spec["paths"].values():
        for method in ("get",):
            if method in path_item:
                path_item[method]["security"] = []
    schema = schemathesis.openapi.from_dict(test_spec)
    with AuditSession(
        interval=0.5, max_requests=len(selected) * (args.examples + 3), max_seconds=1500
    ) as session:
        for name in selected:
            records = run_operation(
                schema, name, definitions[name], session, key, args.examples, args.seed
            )
            report["operations"][name] = records
            failures = sum("failure" in record for record in records)
            statuses = sorted(
                {
                    record.get(
                        "application_status",
                        f"HTTP {record["http_status"]}"
                        if "http_status" in record
                        else "no response",
                    )
                    for record in records
                }
            )
            print(
                f"{name}: {len(records)} cases, {failures} failures; statuses {",".join(statuses)}",
                flush=True,
            )
            report["request_count"] = session.calls
            write_report(args.report, report)
            blocked = any(
                record.get("application_status") in BLOCKING_STATUSES
                for record in records
                if record["kind"] != "missing-auth"
            )
            if (
                blocked
                or time.monotonic() >= session.deadline
                or session.calls >= session.max_requests
            ):
                break
    report["complete"] = len(report["operations"]) == len(selected)
    report["success_observed"] = [
        name
        for name, records in report["operations"].items()
        if any(r.get("application_status") in ("000", "ZIP") for r in records)
    ]
    report["success_not_observed"] = sorted(set(selected) - set(report["success_observed"]))
    failures = sum("failure" in r for records in report["operations"].values() for r in records)
    report["failure_count"] = failures
    report["finished_at"] = datetime.now(UTC).isoformat()
    write_report(args.report, report)
    print(
        f"{session.calls} requests; {failures} failures; success observed for "
        f"{len(report["success_observed"])}/{len(selected)} operations."
    )
    if failures or not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
