#!/usr/bin/env python3
"""Validate the reference offline, including documented coverage and examples."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from functools import cache
from pathlib import Path
from urllib.parse import unquote

import yaml
from defusedxml.ElementTree import fromstring
from jsonschema import Draft202012Validator
from openapi_spec_validator import OpenAPIV32SpecValidator, validate_url

ROOT = Path(__file__).resolve().parents[2] / "api_reference"


def require(condition, message):
    """Enforce a reference invariant with a useful failure message.

    Args:
        condition (object): Value whose truthiness indicates whether the invariant holds.
        message (str): Error message used if the invariant fails.

    Raises:
        ValueError: The condition is false.
    """
    if not condition:
        raise ValueError(message)


@cache
def load(path):
    """Load and cache one local YAML document.

    Args:
        path (Path): Filesystem path to the YAML document.

    Returns:
        object: Parsed YAML content.

    Raises:
        OSError: The file cannot be read.
        yaml.YAMLError: The file contains invalid YAML.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve(value, base):
    """Inline local references recursively for offline schema example checks.

    Args:
        value (object): YAML value whose nested references should be resolved.
        base (Path): Document path used to resolve relative references.

    Returns:
        object: Value with references expanded and sibling entries preserved.

    Raises:
        ValueError: A reference is remote or escapes the api_reference directory.
        KeyError: A reference pointer does not exist.
        OSError: A referenced file cannot be read.
        yaml.YAMLError: A referenced YAML document is invalid.
    """
    if isinstance(value, list):
        return [resolve(child, base) for child in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        filename, _, pointer = value["$ref"].partition("#")
        require(":" not in filename, f"Remote reference: {value["$ref"]}")
        path = (base.parent / unquote(filename)).resolve() if filename else base
        require(path.is_relative_to(ROOT), f"Reference outside api_reference: {path}")
        target = load(path)
        for token in pointer.lstrip("/").split("/") if pointer else []:
            target = target[token.replace("~1", "/").replace("~0", "~")]
        resolved = resolve(target, path)
        return {
            **resolved,
            **{key: resolve(child, base) for key, child in value.items() if key != "$ref"},
        }
    return {key: resolve(child, base) for key, child in value.items()}


def documented_leaves(service, archive_member=False):
    """Count documented leaf paths independently from source table indentation.

    Args:
        service (dict): Catalog service containing ordered response fields.
        archive_member (bool): Exclude application status and message for archive member
            schemas. Defaults to False.

    Returns:
        Counter[tuple[str, ...]]: Occurrences of each documented nested leaf path.
    """
    stack, leaves = [], Counter()
    in_index_list = False
    for field in service["fields"][1:]:
        indent = field["indent"]
        if service["id"] in ("AE00038", "AE00039") and in_index_list:
            indent = 40
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if field["container"]:
            stack.append((indent, field["name"]))
            in_index_list = field["name"] == "list"
        elif not (archive_member and field["name"] in ("status", "message")):
            leaves[tuple(name for _, name in stack) + (field["name"],)] += 1
    return leaves


def schema_leaves(schema, path=()):
    """Count leaf paths through generated objects, arrays, and union branches.

    Args:
        schema (dict): Generated response schema to traverse.
        path (tuple[str, ...]): Parent property path. Defaults to the root path, ().

    Returns:
        Counter[tuple[str, ...]]: Occurrences of each leaf property path across all branches.
    """
    leaves = Counter()
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            leaves.update(schema_leaves(branch, path))
    elif schema.get("type") == "object":
        for name, child in schema["properties"].items():
            leaves.update(schema_leaves(child, path + (name,)))
    elif schema.get("type") == "array":
        leaves.update(schema_leaves(schema["items"], path))
    else:
        leaves[path] += 1
    return leaves


def main():
    """Validate reference freshness, OpenAPI structure, coverage, and examples offline.

    Raises:
        subprocess.CalledProcessError: The reference freshness check fails.
        ValueError: A coverage or reference invariant fails, or the catalog is invalid JSON.
        openapi_spec_validator.validation.exceptions.OpenAPIValidationError: The reference
            violates the OpenAPI specification.
        jsonschema.ValidationError: A documented example violates its schema.
        xml.etree.ElementTree.ParseError: An XML example is malformed.
        KeyError: A required catalog or schema entry is missing.
        OSError: A reference or catalog file cannot be read.
        yaml.YAMLError: A reference document contains invalid YAML.
    """
    subprocess.run(
        [sys.executable, str(Path(__file__).with_name("build.py")), "--check"], check=True
    )
    validate_url((ROOT / "openapi.yaml").as_uri(), cls=OpenAPIV32SpecValidator)
    spec = resolve(load(ROOT / "openapi.yaml"), ROOT / "openapi.yaml")
    snapshot = json.loads((ROOT / "sources/catalog.json").read_text(encoding="utf-8"))
    services = [service for group in snapshot["groups"] for service in group["services"]]
    routes = {
        endpoint["path"]: (service, endpoint)
        for service in services
        for endpoint in service["endpoints"]
    }
    require(set(routes) == set(spec["paths"]), "Missing or invented routes")
    require(
        spec["servers"]
        == [
            {
                "url": "https://engopendart.fss.or.kr/engapi",
                "description": "FSS-operated English OpenDART service",
            }
        ],
        "Unexpected upstream server",
    )
    require(spec["security"] == [{"ApiKeyAuth": []}], "Authentication must be required globally")
    auth = spec["components"]["securitySchemes"]["ApiKeyAuth"]
    require(
        (auth["type"], auth["in"], auth["name"]) == ("apiKey", "query", "crtfc_key"),
        "Incorrect auth scheme",
    )
    ids, field_checks, example_checks = set(), set(), 0
    for path, (service, endpoint) in routes.items():
        item = spec["paths"][path]
        require(set(item) == {"get"}, f"Undocumented HTTP method: {path}")
        operation = item["get"]
        require("security" not in operation, f"Unexpected authentication override: {path}")
        require(operation["operationId"] not in ids, "Duplicate operationId")
        ids.add(operation["operationId"])
        require(
            operation["externalDocs"]["url"] == service["source"], f"Missing provenance: {path}"
        )
        expected = {p["name"]: p for p in service["parameters"] if p["name"] != "crtfc_key"}
        actual = {p["name"]: p for p in operation["parameters"]}
        require(set(expected) == set(actual), f"Parameter coverage mismatch: {path}")
        for name, parameter in actual.items():
            require(
                parameter["in"] == "query" and parameter["required"] == expected[name]["required"],
                f"Parameter location or requiredness mismatch: {path} {name}",
            )
            Draft202012Validator(parameter["schema"]).validate(parameter["example"])
            if name == "corp_code" and service["id"] in ("AE00034", "AE00039"):
                require(
                    parameter["style"] == "form" and parameter["explode"] is False,
                    "Company lists must serialize as one comma-separated query value",
                )
                require(parameter["schema"]["maxItems"] == 100, "Missing company limit")
        expected_statuses = (
            {"200", "default", "302"} if service["id"] == "AE00035" else {"200", "default"}
        )
        require(
            set(operation["responses"]) == expected_statuses, "Unexpected HTTP response mapping"
        )
        response = operation["responses"]["200"]
        binary = "binary" in endpoint["output"].lower()
        content = response["content"]
        if binary:
            expected_media = {
                "application/zip",
                "application/octet-stream",
                "application/xml",
                "text/xml",
            }
            if service["id"] in ("AE00003", "AE00004", "AE00035"):
                expected_media.add("application/x-msdownload")
            require(
                set(content) == expected_media,
                f"Missing binary or XML error representation: {path}",
            )
            require(content["application/zip"]["schema"]["format"] == "binary", "ZIP must be bytes")
            if service["id"] == "AE00004":
                member = response["x-archive-member-schema"]
                require(
                    documented_leaves(service, True) == schema_leaves(member),
                    "Archive member field loss",
                )
        else:
            primary = "application/json" if endpoint["output"] == "JSON" else "application/xml"
            representation = content[primary]
            require("application/zip" not in content, f"Invented ZIP format: {path}")
            success, error = representation["schema"]["anyOf"]
            if service["id"] not in field_checks:
                require(
                    documented_leaves(service) == schema_leaves(success),
                    f"Response field loss: {path}",
                )
                field_checks.add(service["id"])
            require(
                Draft202012Validator(success).is_valid({"status": "000", "message": "Normal"}),
                "Invalid success",
            )
            require(
                not Draft202012Validator(error).is_valid({"status": "000", "message": "Normal"}),
                "Error accepts success",
            )
            for code in (
                "010",
                "011",
                "012",
                "013",
                "014",
                "020",
                "021",
                "100",
                "101",
                "800",
                "900",
                "901",
                "999",
            ):
                sample = {"status": code, "message": "Example"}
                require(
                    Draft202012Validator(error).is_valid(sample),
                    f"Rejected application code: {code}",
                )
                require(
                    not Draft202012Validator(success).is_valid(sample), "Success accepts an error"
                )
            # Upstream additions and optional report values must remain usable.
            require(
                Draft202012Validator(success).is_valid(
                    {"status": "000", "message": "Normal", "future_field": "x"}
                ),
                "Response schema rejects upstream extensions",
            )
        for media, representation in content.items():
            for example in representation.get("examples", {}).values():
                value = example["value"]
                if media.endswith("xml"):
                    xml = fromstring(value)
                    require(xml.tag == "result", "Incorrect XML root")
                    value = {child.tag: child.text or "" for child in xml}
                Draft202012Validator(representation["schema"]).validate(value)
                example_checks += 1
    print(
        f"Validated OpenAPI {spec["openapi"]}, {len(services)} services, {len(routes)} routes, "
        f"{len(field_checks)} structured response schemas, archive fields, and {example_checks} examples (JSON and parsed XML)."
    )


if __name__ == "__main__":
    main()
