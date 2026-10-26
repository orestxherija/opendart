"""Resolve local OpenAPI references at either side of a complete Git push."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[3] / "api_reference"
METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


class Snapshot:
    """Read a reference from the working tree or an immutable Git commit."""

    def __init__(self, root=ROOT, revision=None):
        """Choose a local tree or a verified immutable Git revision."""
        self.root = Path(root)
        self.revision = revision
        self.cache = {}
        if revision is not None:
            if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
                raise ValueError("Expected a full Git commit SHA")
            subprocess.run(
                ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
                cwd=self.root.parent,
                check=True,
                capture_output=True,
            )

    def load(self, filename):
        """Read only documents within the reference directory."""
        filename = posixpath.normpath(filename)
        if filename.startswith(("../", "/")) or filename == "..":
            raise ValueError("Reference escapes api_reference")
        if filename not in self.cache:
            if self.revision:
                result = subprocess.run(
                    ["git", "show", f"{self.revision}:{self.root.name}/{filename}"],
                    cwd=self.root.parent,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                text = result.stdout
            else:
                path = (self.root / filename).resolve()
                if not path.is_relative_to(self.root.resolve()):
                    raise ValueError("Reference escapes api_reference")
                text = path.read_text(encoding="utf-8")
            self.cache[filename] = yaml.safe_load(text)
        return self.cache[filename]

    def resolve(self, value, filename="openapi.yaml", active=()):
        """Inline transitive references; fail explicitly on unsupported cycles."""
        if isinstance(value, list):
            return [self.resolve(child, filename, active) for child in value]
        if not isinstance(value, dict):
            return value
        siblings = {
            key: self.resolve(child, filename, active)
            for key, child in value.items()
            if key != "$ref"
        }
        if "$ref" not in value:
            return siblings
        location, _, pointer = value["$ref"].partition("#")
        location = unquote(location)
        if ":" in location or location.startswith("/"):
            raise ValueError("Only local references are supported")
        target_file = (
            posixpath.normpath(posixpath.join(posixpath.dirname(filename), location))
            if location
            else filename
        )
        identity = (target_file, pointer)
        if identity in active:
            raise ValueError("Circular reference requires explicit selector support")
        target = self.load(target_file)
        if pointer and not pointer.startswith("/"):
            raise ValueError("Expected a JSON Pointer fragment")
        for token in unquote(pointer)[1:].split("/") if pointer else []:
            token = token.replace("~1", "/").replace("~0", "~")
            target = target[int(token)] if isinstance(target, list) else target[token]
        resolved = self.resolve(target, target_file, (*active, identity))
        if siblings:
            if not isinstance(resolved, dict):
                raise ValueError("Reference siblings require an object target")
            return {**resolved, **siblings}
        return resolved

    def spec(self):
        """Return the complete resolved OpenAPI document."""
        return self.resolve(self.load("openapi.yaml"))


def operations(spec):
    """Include inherited parameters, servers, security, and used auth schemes."""
    result = {}
    for path, item in spec["paths"].items():
        for method in sorted(METHODS & item.keys()):
            operation = dict(item[method])
            # These globals change how every operation's schemas are interpreted.
            operation["openapi"] = spec["openapi"]
            operation["jsonSchemaDialect"] = spec.get("jsonSchemaDialect")
            operation["servers"] = operation.get(
                "servers", item.get("servers", spec.get("servers", []))
            )
            operation["security"] = operation.get("security", spec.get("security", []))
            parameters = {
                (p["in"], p["name"]): p
                for p in [*item.get("parameters", []), *operation.get("parameters", [])]
            }
            operation["parameters"] = [parameters[key] for key in sorted(parameters)]
            operation["securitySchemes"] = {
                name: spec["components"]["securitySchemes"][name]
                for requirement in operation["security"]
                for name in requirement
            }
            for key in ("summary", "description"):
                if key in item:
                    operation[f"path-{key}"] = item[key]
            result[f"{method.upper()} {path}"] = operation
    return result


def select(before, after):
    """Select added/modified operations; report deleted operations separately."""
    old = operations(before) if before else {}
    new = operations(after)
    return {
        "selected": sorted(key for key, value in new.items() if old.get(key) != value),
        "removed": sorted(old.keys() - new.keys()),
    }


def main():
    """Write a reviewable selection without credentials or API calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Full before SHA; omit for the initial full audit")
    parser.add_argument("--head", help="Full after SHA; default: working tree")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = None
    if args.base and set(args.base) != {"0"}:
        snapshot = Snapshot(revision=args.base)
        # A first commit introducing this reference has no prior entry point.
        exists = (
            subprocess.run(
                ["git", "cat-file", "-e", f"{args.base}:api_reference/openapi.yaml"],
                cwd=ROOT.parent,
                capture_output=True,
            ).returncode
            == 0
        )
        if exists:
            before = snapshot.spec()
    selection = select(before, Snapshot(revision=args.head).spec())
    selection.update(base=args.base, head=args.head)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    print(f"Selected {len(selection["selected"])}; removed {len(selection["removed"])}")


if __name__ == "__main__":
    main()
