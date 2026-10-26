"""Validate JSON, OpenAPI XML serialization, and ZIP response bodies."""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from jsonschema import Draft202012Validator


class ContractViolation(Exception):
    """A safe diagnostic that contains no response values or request credentials."""


def validate_schema(value, schema):
    """Report schema locations and types without dumping upstream response bodies."""
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        leaves = []

        def collect(error):
            if error.context:
                for child in error.context:
                    collect(child)
            else:
                path = "/" + "/".join(map(str, error.absolute_path))
                leaves.append(
                    f"{path}: {error.validator} (received {type(error.instance).__name__})"
                )

        for error in errors:
            collect(error)
        raise ContractViolation("; ".join(leaves[:12]))


def xml_value(element, schema):
    """Decode unwrapped arrays and typed XML leaves without coercing report strings."""
    if "anyOf" in schema:
        # Decode each branch using its own XML serialization, then validate it.
        for branch in schema["anyOf"]:
            value = xml_value(element, branch)
            if Draft202012Validator(branch).is_valid(value):
                return value
        return xml_value(element, schema["anyOf"][0])
    if element.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in ("true", "1"):
        return None
    if schema.get("type") == "object" or len(element):
        children = defaultdict(list)
        for child in element:
            children[child.tag].append(child)
        properties = schema.get("properties", {})
        result = {}
        names = {
            definition.get("xml", {}).get("name", name): name
            for name, definition in properties.items()
        }
        for tag, elements in children.items():
            name = names.get(tag, tag)
            child_schema = properties.get(name, {})
            if child_schema.get("type") == "array":
                members = (
                    list(elements[0]) if child_schema.get("xml", {}).get("wrapped") else elements
                )
                result[name] = [xml_value(child, child_schema["items"]) for child in members]
            elif len(elements) == 1:
                result[name] = xml_value(elements[0], child_schema)
            else:
                result[name] = [xml_value(child, child_schema) for child in elements]
        return result
    text = element.text or ""
    if schema.get("type") == "integer":
        try:
            return int(text)
        except ValueError:
            return text
    return text


def parse_xml(body, schema):
    """Reject unsafe XML and enforce the documented root and response schema."""
    try:
        root = ElementTree.fromstring(body, forbid_dtd=True)
    except Exception as exc:
        raise ContractViolation(f"Invalid XML ({type(exc).__name__})") from None
    if root.tag != schema.get("xml", {}).get("name", "result"):
        raise ContractViolation("XML root differs from the documented root")
    value = xml_value(root, schema)
    validate_schema(value, schema)
    return value


def validate_zip(body, member_schema=None):
    """Check ZIP structure/CRC and the corporation XML member without extracting files."""
    try:
        with ZipFile(BytesIO(body)) as archive:
            members = archive.infolist()
            if not members or len(members) > 10000:
                raise ContractViolation("ZIP member count is empty or exceeds the audit limit")
            if sum(member.file_size for member in members) > 100 * 1024 * 1024:
                raise ContractViolation("ZIP expands beyond the 100 MiB audit limit")
            if archive.testzip() is not None:
                raise ContractViolation("ZIP member CRC mismatch")
            if member_schema is not None:
                xml_members = [
                    member for member in members if member.filename.lower().endswith(".xml")
                ]
                if len(xml_members) != 1:
                    raise ContractViolation("Expected one corporation-directory XML member")
                parse_xml(archive.read(xml_members[0]), member_schema)
    except BadZipFile, RuntimeError, NotImplementedError:
        raise ContractViolation("Invalid or unsupported ZIP archive") from None


def validate_body(body, media_type, response_definition):
    """Validate the actual media type; return an application status or ZIP success."""
    import json

    content = response_definition["content"]
    if media_type not in content:
        raise ContractViolation("Response Content-Type is not documented")
    schema = content[media_type]["schema"]
    if schema.get("format") == "binary":
        validate_zip(body, response_definition.get("x-archive-member-schema"))
        return "ZIP"
    if media_type in ("application/xml", "text/xml"):
        value = parse_xml(body, schema)
    elif media_type == "application/json":
        try:
            value = json.loads(body)
        except ValueError, UnicodeDecodeError:
            raise ContractViolation("Invalid JSON response") from None
        validate_schema(value, schema)
    else:
        raise ContractViolation("No validator implemented for documented media type")
    return value.get("status") if isinstance(value, dict) else None
