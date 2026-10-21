#!/usr/bin/env python3
"""Build the modular OpenAPI reference offline from the reviewed public snapshot.

Requires PyYAML. Use --check to detect stale generated files without writing.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "api_reference"


class ReferenceDumper(yaml.SafeDumper):
    """Avoid anchors and YAML 1.1/1.2 disagreement about numeric identifiers."""

    def ignore_aliases(self, data):
        """Disable YAML anchors for every serialized value.

        Args:
            data (object): Value being considered for anchor reuse.

        Returns:
            bool: Always True, so every value is serialized inline.
        """
        return True


def represent_string(dumper, value):
    """Quote strings that YAML readers could interpret as numbers or booleans.

    Args:
        dumper (ReferenceDumper): YAML dumper receiving the scalar.
        value (str): String value to serialize.

    Returns:
        yaml.nodes.ScalarNode: String scalar with quotes where required.
    """
    style = "'" if re.fullmatch(r"[0-9]+|y|n|yes|no|on|off", value, re.IGNORECASE) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


ReferenceDumper.add_representer(str, represent_string)
GROUPS = {
    "DE001": ("disclosures", "Disclosure information"),
    "DE002": ("periodic-reports", "Key information from periodic reports"),
    "DE003": ("financial-statements", "Financial information from periodic reports"),
    "DE004": ("equity-disclosures", "Equity disclosure information"),
    "DE005": ("major-issues", "Reports on major issues"),
    "DE006": ("securities-registration", "Securities registration statements"),
}
STATUS = {
    "000": "Success.",
    "010": "Unregistered authentication key.",
    "011": "Suspended authentication key.",
    "012": "IP address is not permitted.",
    "013": "No matching data.",
    "014": "Requested file is unavailable.",
    "020": "Request quota exceeded; the threshold depends on the key configuration.",
    "021": "Too many companies; the documented maximum is 100 per request.",
    "100": "Missing or invalid parameter value (including a missing crtfc_key).",
    "101": "Access is not permitted.",
    "800": "Service unavailable for maintenance.",
    "900": "Unclassified upstream error.",
    "901": "Authentication key expired with the account's personal-data retention period.",
}
EXAMPLES = {
    "corp_code": "00126380",
    "rcept_no": "20190401004781",
    "bsns_year": "2025",
    "reprt_code": "11011",
    "bgn_de": "20250101",
    "end_de": "20250331",
    "last_reprt_at": "N",
    "pblntf_ty": "A",
    "pblntf_detail_ty": "A001",
    "corp_cls": "Y",
    "sort": "date",
    "sort_mth": "desc",
    "page_no": 1,
    "page_count": 10,
    "fs_div": "CFS",
    "idx_cl_code": "M210000",
    "sj_div": "BS1",
}
ENUMS = {
    "reprt_code": ["11013", "11012", "11014", "11011"],
    "fs_div": ["OFS", "CFS"],
    "idx_cl_code": ["M210000", "M220000", "M230000", "M240000"],
    "corp_cls": ["Y", "K", "N", "E"],
    "pblntf_ty": list("ABCDEFGHIJ"),
    "last_reprt_at": ["Y", "N"],
    "sort": ["date", "crp", "rpt"],
    "sort_mth": ["asc", "desc"],
}


def ref(path):
    """Build an OpenAPI reference object.

    Args:
        path (str): Relative reference URI with an optional fragment.

    Returns:
        dict[str, str]: Mapping with a single $ref entry.
    """
    return {"$ref": path}


def schema_name(service):
    """Derive a schema class prefix from a service's first endpoint.

    Args:
        service (dict): Catalog service with at least one endpoint.

    Returns:
        str: Endpoint stem with its first character capitalized.
    """
    stem = service["endpoints"][0]["path"].split(".")[0].lstrip("/")
    return stem[0].upper() + stem[1:]


def parameter(source, service):
    """Translate one documented query field into an OpenAPI parameter.

    Args:
        source (dict): Snapshot parameter with declared type, requiredness, and description.
        service (dict): Owning service, including examples and category code tables.

    Returns:
        dict: Query parameter schema with constraints, description, and example.

    Raises:
        ValueError: The documented query type is not a supported STRING declaration or a
            numeric example cannot be converted.
    """
    name = source["name"]
    description = source["description"]
    schema = {"type": "string"}
    length = re.fullmatch(r"STRING\((\d+)\)", source["declared_type"])
    if not length:
        raise ValueError(f"Unknown query type: {source}")
    schema["maxLength"] = int(length[1])
    if name in ENUMS:
        schema["enum"] = ENUMS[name]
    if name in ("corp_code", "rcept_no", "bsns_year", "bgn_de", "end_de"):
        count = {"corp_code": 8, "rcept_no": 14, "bsns_year": 4, "bgn_de": 8, "end_de": 8}[name]
        schema.update(minLength=count, maxLength=count, pattern=f"^[0-9]{{{count}}}$")
        if count != int(length[1]):
            description += (
                f" Documentation conflict: the type column says {source["declared_type"]}; "
                f"the field definition and public examples identify a {count}-digit value. "
                "This consumer specification follows that definition and those examples."
            )
    if name in ("page_no", "page_count"):
        schema = {"type": "integer", "minimum": 1, "default": 1 if name == "page_no" else 10}
        if name == "page_count":
            schema["maximum"] = 100
        description += " Serialized as decimal digits in the query string."
    elif name in ("sort", "sort_mth", "last_reprt_at"):
        schema["default"] = EXAMPLES[name]
    if name == "pblntf_detail_ty":
        table = service["code_tables"][0]
        schema["enum"] = [row[-2] for row in table[1:]]
        description = "Detailed disclosure category. " + "; ".join(
            f"{row[-2]}: {row[-1]}" for row in table[1:]
        )
    if name == "sj_div":
        table = service["code_tables"][0]
        schema["enum"] = [row[0] for row in table[1:]]
        description = "Taxonomy statement variant. " + "; ".join(
            ": ".join((row[0], ", ".join(part for part in row[1:] if part))) for row in table[1:]
        )
    example = source.get("example", EXAMPLES[name])
    result = dict(
        name=name,
        **{"in": "query"},
        required=source["required"],
        description=description,
        schema=schema,
        **{"x-upstream-type": source["declared_type"]},
    )
    if name == "corp_code" and service["id"] in ("AE00034", "AE00039"):
        result.update(style="form", explode=False)
        result["schema"] = {"type": "array", "minItems": 1, "maxItems": 100, "items": schema}
        result["description"] += (
            " Send 1–100 corporation codes as a single comma-separated value. "
            "The index description, public form example, and status 021 establish "
            "multi-company support despite STRING(8) in the type column."
        )
        example = example.split(",")
    elif name in ("page_no", "page_count"):
        example = int(example)
    if service["id"] in ("AE00038", "AE00039") and name in ("bsns_year", "corp_code"):
        # The guide's 2021 example predates its stated 2022 availability.
        # Preserve it, but use a successful 2023 live-audit request in Redoc.
        result["x-upstream-example"] = source.get("example", EXAMPLES[name])
        example = (
            "2023"
            if name == "bsns_year"
            else (["00126380"] if service["id"] == "AE00039" else "00126380")
        )
        result["description"] = (
            result["description"].rstrip(".")
            + ". The reference example was checked against a successful 2023 response."
        )
    result["example"] = example
    return result


def object_schema(description):
    """Create an extensible object schema with no properties yet.

    Args:
        description (str): Human-readable description of the object.

    Returns:
        dict: Object schema ready to receive properties.
    """
    return {
        "type": "object",
        "description": description,
        "additionalProperties": True,
        "properties": {},
    }


def leaf(field):
    """Translate one documented response leaf while preserving financial text.

    Args:
        field (dict): Snapshot field with name, title, and description.

    Returns:
        dict: String schema, integer pagination schema, or success status enum.
    """
    name = field["name"]
    description = field["title"] or name
    detail = field["description"]
    if detail and detail != description:
        description += ". " + detail
    if name == "status":
        return {"type": "string", "enum": ["000"], "description": "Successful application status."}
    if name in ("page_no", "page_count", "total_count", "total_page"):
        return {"type": "integer", "minimum": 0, "description": description}
    value = {"type": "string", "description": description}
    if detail == "9,999,999,999" or "amount" in name or name in ("idx_val", "ord"):
        value["description"] += (
            " Preserve the upstream text; do not coerce commas, blanks, or '-' to a number."
        )
    return value


def response_tree(service):
    """Build nested response schemas from the source table's indentation.

    Args:
        service (dict): Catalog service containing ordered response field records.

    Returns:
        dict: Extensible response schema with required status and message.

    Raises:
        ValueError: The root is absent, a container is empty, scalar names repeat, or some
            fields cannot be consumed.
    """
    fields = deepcopy(service["fields"])
    if service["id"] in ("AE00038", "AE00039"):
        # Both financial-index guides render list children at the root indent.
        # Keep the original snapshot and repair only this known presentation
        # defect, following the explicit list marker and related financial APIs.
        start = next(i for i, field in enumerate(fields) if field["name"] == "list")
        for field in fields[start + 1 :]:
            field["indent"] = 40
    if fields[0]["name"] != "result":
        raise ValueError(f"Missing documented root: {service["id"]}")

    def parse(index, indent):
        """Consume sibling fields and recursively build their nested containers.

        Args:
            index (int): Index of the first unconsumed field.
            indent (int): Indentation identifying siblings at this level.

        Returns:
            tuple[dict, int]: Object schema and index of the next unconsumed field.

        Raises:
            ValueError: A container is empty or a scalar name is repeated.
        """
        result = object_schema(
            "Documented fields; availability depends on the submitted disclosure."
        )
        variants = defaultdict(list)
        while index < len(fields) and fields[index]["indent"] == indent:
            field = fields[index]
            index += 1
            if field["container"]:
                if index == len(fields) or fields[index]["indent"] <= indent:
                    raise ValueError(f"Empty documented container: {service["id"]} {field}")
                child, index = parse(index, fields[index]["indent"])
                child["xml"] = {"name": field["name"]}
                value = {
                    "type": "array",
                    "description": f"Repeated {field["name"]} records.",
                    "items": child,
                    "xml": {"name": field["name"], "wrapped": False},
                }
            else:
                value = leaf(field)
            variants[field["name"]].append(value)
        for name, values in variants.items():
            if len(values) == 1:
                result["properties"][name] = values[0]
            elif all(value.get("type") == "array" for value in values):
                # A registration statement repeats group/title/list for each
                # section. Keep each section's record fields in its own branch.
                result["properties"][name] = {
                    "type": "array",
                    "description": "Sections with different sets of disclosed fields.",
                    "items": {"anyOf": [value["items"] for value in values]},
                    "xml": {"name": name, "wrapped": False},
                }
            else:
                raise ValueError(f"Repeated scalar in {service["id"]}: {name}")
        return result, index

    result, consumed = parse(1, fields[1]["indent"])
    if consumed != len(fields):
        raise ValueError(f"Unconsumed fields: {service["id"]} at {consumed}")
    result.update(required=["status", "message"], xml={"name": "result"})
    result["description"] = (
        service["title"] + ". Scalar report fields are modeled as strings; "
        "the guide does not specify scalar JSON types or guarantee field presence. "
        "Pagination counters are modeled as integers. Additional upstream fields are allowed."
    )
    return result


def example_for(schema, name=""):
    """Construct a synthetic successful value satisfying a generated schema.

    Args:
        schema (dict): Object, array, enum, integer, string, or anyOf schema.
        name (str): Field name used to select a representative scalar. Defaults to an empty
            string.

    Returns:
        dict | list | str | int: Synthetic value containing no captured filing data.
    """
    if "anyOf" in schema:
        return example_for(schema["anyOf"][0], name)
    if schema["type"] == "object":
        return {key: example_for(value, key) for key, value in schema["properties"].items()}
    if schema["type"] == "array":
        return [example_for(schema["items"], name)]
    if schema["type"] == "integer":
        return 10 if name == "page_count" else 1
    if "enum" in schema:
        return schema["enum"][0]
    if name == "message":
        return "Normal"
    if name == "title":
        return schema["description"].split(". ", 1)[-1]
    return {
        "corp_code": "00126380",
        "corp_name": "Example corporation",
        "stock_code": "005930",
        "corp_cls": "Y",
        "rcept_no": "20190401004781",
        "rcept_dt": "20190401",
        "bsns_year": "2025",
        "reprt_code": "11011",
        "fs_div": "CFS",
        "sj_div": "BS",
        "idx_val": "0.256",
        "stlm_dt": "2025.12.31",
    }.get(name, "")


def build(snapshot):
    """Build modular OpenAPI documents from the reviewed public catalog.

    Args:
        snapshot (dict): Catalog containing retrieval metadata and the six service groups.

    Returns:
        dict[str, dict]: Output-relative YAML filenames mapped to document mappings.

    Raises:
        ValueError: Documented types, response nesting, or examples are unsupported.
        KeyError: A required catalog field or category mapping is missing.
    """
    common = {
        "schemas": {
            "ApplicationError": {
                "type": "object",
                "description": "Non-success OpenDART application result; inspect status even on HTTP 200.",
                "additionalProperties": True,
                "required": ["status", "message"],
                "xml": {"name": "result"},
                "properties": {
                    "status": {
                        "type": "string",
                        "pattern": "^(?!000$)[0-9]{3}$",
                        "description": "Non-success application code. Unknown future three-digit codes are accepted.\n\n"
                        + "\n".join(
                            f"- `{code}`: {meaning}"
                            for code, meaning in STATUS.items()
                            if code != "000"
                        ),
                        "x-known-values": [code for code in STATUS if code != "000"],
                    },
                    "message": {
                        "type": "string",
                        "description": "Upstream diagnostic text; wording and language are not stable.",
                    },
                },
            },
            "ZipArchive": {
                "type": "string",
                "format": "binary",
                "description": "ZIP archive bytes, despite the .xml request suffix.",
            },
        },
        "responses": {
            "TransportFailure": {
                "description": "Unexpected HTTP-level failure from the upstream service or an intermediary. "
                "The official guide does not define its HTTP status mapping, content type, or body schema. "
                "No structured error body or retry header is guaranteed."
            }
        },
    }
    main = {
        "openapi": "3.2.1",
        # Pin the published OAS 3.2 dialect bundled by our offline validator.
        "jsonSchemaDialect": "https://spec.openapis.org/oas/3.2/dialect/2025-09-17",
        "info": {
            "title": "OpenDART English API — consumer-maintained reference",
            "version": "0.1.0",
            "description": "Unofficial reconstruction of the English OpenDART developer guides, maintained by API consumers. "
            "The Financial Supervisory Service (FSS) operates the upstream API; this repository neither owns nor controls it. "
            "This version identifies this reference, not an upstream release.\n\n"
            "Use the documented HTTPS /engapi server. The Korean /api service is a separate contract and is outside this reference. "
            "Every call requires the 40-character crtfc_key query credential; configure it through ApiKeyAuth. "
            "Select JSON or XML using the route suffix, not content negotiation.\n\n"
            "Application status 000 indicates success. Non-success status values, including 013 (no data) and 020 (quota), "
            "are response-body codes, not HTTP status codes. Always inspect status. The upstream guide mentions a usual "
            "20,000-request quota but explicitly allows different thresholds; no fixed rate, reset time, retry policy, "
            "or Retry-After header is promised.\n\n"
            "Identifiers and financial values retain their upstream string representation. Date query values use YYYYMMDD, "
            "not RFC 3339 dates. Unknown response properties are allowed, and report fields are optional because presence "
            "depends on disclosure content. Examples are synthetic illustrations, not captured or guaranteed filings.\n\n"
            "The guides do not fully specify scalar response types, XML serialization, HTTP error mappings, or media headers. "
            "These limits, live contract findings, and coverage gaps are recorded in README.md and CONTRACT_TESTING.md. "
            "Bounded Schemathesis audits check observed responses, not every possible filing. "
            "FSS cautions that extracted report data may be incomplete or later corrected.",
            "termsOfService": "https://engopendart.fss.or.kr/intro/terms.do",
        },
        "servers": [
            {
                "url": "https://engopendart.fss.or.kr/engapi",
                "description": "FSS-operated English OpenDART service",
            }
        ],
        "security": [{"ApiKeyAuth": []}],
        "tags": [
            {
                "name": slug,
                "description": title,
                "externalDocs": {"url": group["source"], "description": "Official service index"},
            }
            for group in snapshot["groups"]
            for slug, title in [GROUPS[group["code"]]]
        ],
        "externalDocs": {
            "url": snapshot["source"],
            "description": "Official English OpenDART introduction",
        },
        "x-source-retrieved-on": snapshot["retrieved_on"],
        "x-maintenance-role": "third-party-consumer",
        "paths": {},
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "query",
                    "name": "crtfc_key",
                    "description": "Required FSS-issued 40-character authentication key. "
                    "Keep it out of committed examples and redact it from request URLs in logs.",
                }
            }
        },
    }
    outputs = {
        "schemas/common.yaml": common,
        "examples.yaml": {
            "NoDataXml": {
                "summary": "Synthetic XML no-data result",
                "value": "<result><status>013</status><message>No data</message></result>",
            },
            "InvalidParametersXml": {
                "summary": "Synthetic missing or invalid parameter result (including a missing key)",
                "value": "<result><status>100</status><message>Missing or invalid parameter</message></result>",
            },
            "FileUnavailableXml": {
                "summary": "Synthetic XML application error",
                "value": "<result><status>014</status><message>File unavailable</message></result>",
            },
        },
    }
    parameters = {}
    for group in snapshot["groups"]:
        slug, _ = GROUPS[group["code"]]
        schemas, paths = {}, {}
        for service in group["services"]:
            name = schema_name(service)
            success = response_tree(service)
            if service["id"] == "AE00004":
                member = deepcopy(success)
                member.pop("required")
                member["properties"].pop("status")
                member["properties"].pop("message")
                member["description"] = (
                    "Corporation directory XML after ZIP decompression; not an HTTP response schema."
                )
                schemas[name + "ArchiveMember"] = member
            elif "binary" not in service["endpoints"][0]["output"].lower():
                schemas[name + "Success"] = success
                schemas[name + "Response"] = {
                    "description": "Success or an application-level error in the same HTTP response.",
                    "anyOf": [
                        ref(f"#/{name}Success"),
                        ref("./common.yaml#/schemas/ApplicationError"),
                    ],
                    "xml": {"name": "result"},
                }
            refs = []
            for source in service["parameters"]:
                if source["name"] == "crtfc_key":
                    continue
                value = parameter(source, service)
                # Identical parameters share components; descriptions, required
                # flags and availability notes remain specific when they differ.
                identity = json.dumps(value, sort_keys=True)
                key = next(
                    (
                        key
                        for key, old in parameters.items()
                        if json.dumps(old, sort_keys=True) == identity
                    ),
                    None,
                )
                if key is None:
                    key = name + "_" + source["name"]
                    parameters[key] = value
                refs.append(ref(f"../parameters.yaml#/{key}"))
            for endpoint in service["endpoints"]:
                path = endpoint["path"]
                extension = path.rsplit(".", 1)[1]
                binary = "binary" in endpoint["output"].lower()
                schema_ref = ref(f"../schemas/{slug}.yaml#/{name}Response")
                description = (
                    service["description"]
                    + " See the linked official guide for coverage and availability."
                )
                if service["id"] == "AE00001":
                    description += (
                        " Without corp_code the date interval is limited to three months. "
                        "bgn_de defaults to end_de; end_de defaults to the current date. "
                        "Pagination starts at 1, with 10 records by default and at most 100 per page."
                    )
                content = {}
                if binary:
                    description += (
                        " The .xml suffix returns a ZIP archive on success, not an XML document."
                    )
                    zip_media = ["application/zip", "application/octet-stream"]
                    if service["id"] in ("AE00003", "AE00004", "AE00035"):
                        zip_media.append("application/x-msdownload")
                        description += " Live responses use Content-Type application/x-msdownload for ZIP bytes."
                    for media in zip_media:
                        content[media] = {
                            "schema": ref("../schemas/common.yaml#/schemas/ZipArchive")
                        }
                    for media in ("application/xml", "text/xml"):
                        content[media] = {
                            "schema": ref("../schemas/common.yaml#/schemas/ApplicationError"),
                            "examples": {
                                "fileUnavailable": ref("../examples.yaml#/FileUnavailableXml"),
                                "invalidParameters": ref("../examples.yaml#/InvalidParametersXml"),
                            },
                        }
                    if service["id"] == "AE00004":
                        # This schema describes a member after decompression,
                        # never the ZIP bytes or an XML success HTTP body.
                        description += " After decompression, the member XML contains repeated corporation records."
                elif extension == "json":
                    content["application/json"] = {
                        "schema": schema_ref,
                        "examples": {
                            "success": {
                                "summary": "Synthetic shape illustration; not a captured response",
                                "value": example_for(success),
                            },
                            "noData": {
                                "summary": "Synthetic no-data result; list may be absent",
                                "value": {"status": "013", "message": "No data"},
                            },
                            "invalidParameters": {
                                "summary": "Synthetic missing or invalid parameter result (including a missing key)",
                                "value": {
                                    "status": "100",
                                    "message": "Missing or invalid parameter",
                                },
                            },
                            "quotaExceeded": {
                                "summary": "Synthetic quota result",
                                "value": {"status": "020", "message": "Quota exceeded"},
                            },
                        },
                    }
                else:
                    for media in ("application/xml", "text/xml"):
                        content[media] = {
                            "schema": schema_ref,
                            "examples": {
                                "noData": ref("../examples.yaml#/NoDataXml"),
                                "invalidParameters": ref("../examples.yaml#/InvalidParametersXml"),
                            },
                        }
                response = {
                    "description": "Upstream result. Inspect the application status; HTTP success alone does not indicate API success.",
                    "content": content,
                }
                if service["id"] == "AE00004":
                    response["x-archive-member-schema"] = ref(
                        f"../schemas/{slug}.yaml#/{name}ArchiveMember"
                    )
                paths[path] = {
                    "get": {
                        "tags": [slug],
                        "summary": service["title"]
                        + (" (ZIP)" if binary else f" ({extension.upper()})"),
                        "description": description,
                        "operationId": "get" + name + ("Archive" if binary else extension.title()),
                        "externalDocs": {
                            "url": service["source"],
                            "description": "Official endpoint guide",
                        },
                        "x-upstream-api-id": service["id"],
                        "parameters": refs,
                        "responses": {
                            "200": response,
                            "default": ref("../schemas/common.yaml#/responses/TransportFailure"),
                        },
                    }
                }
                if service["id"] == "AE00035":
                    paths[path]["get"]["responses"]["302"] = {
                        "description": "Observed redirect when rcept_no is omitted. This is not a successful ZIP download "
                        "or a structured OpenDART application-error envelope. Do not treat it as status 000.",
                        "headers": {
                            "Location": {
                                "description": "Redirect target supplied by the upstream service. Do not forward query credentials.",
                                "schema": {"type": "string", "format": "uri-reference"},
                            }
                        },
                    }
                pointer = path.replace("~", "~0").replace("/", "~1")
                main["paths"][path] = ref(f"./paths/{slug}.yaml#/{pointer}")
        outputs[f"paths/{slug}.yaml"] = paths
        outputs[f"schemas/{slug}.yaml"] = schemas
    outputs["parameters.yaml"] = parameters
    outputs["openapi.yaml"] = main
    return outputs


def main():
    """Write the generated reference or detect stale files with --check.

    Raises:
        SystemExit: CLI parsing exits or --check finds missing or stale files.
        OSError: A catalog or output file cannot be read or written.
        ValueError: The catalog is invalid JSON or contains unsupported documentation
            shapes.
        KeyError: A required catalog field or category mapping is missing.
        yaml.YAMLError: An output document cannot be serialized.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    snapshot = json.loads((ROOT / "sources/catalog.json").read_text(encoding="utf-8"))
    outputs = build(snapshot)
    mismatches = []
    for filename, value in outputs.items():
        text = "# Generated by scripts/api_reference/build.py from api_reference/sources/catalog.json; see api_reference/README.md.\n"
        text += yaml.dump(
            value, Dumper=ReferenceDumper, allow_unicode=True, sort_keys=False, width=110
        )
        path = ROOT / filename
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                mismatches.append(filename)
        else:
            path.write_text(text, encoding="utf-8")
    if mismatches:
        raise SystemExit("Stale generated files: " + ", ".join(mismatches))
    print(
        f"{"Checked" if args.check else "Built"} {len(outputs)} files, {len(outputs["openapi.yaml"]["paths"])} GET operations."
    )


if __name__ == "__main__":
    main()
