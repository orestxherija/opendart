#!/usr/bin/env python3
"""Advisory, standard-library-only checks for explicit httpx2 mistakes.

This is a deliberately conservative syntax check, not a type checker. It follows
direct imports and local client assignments, not factories or intermodule flow.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
import tokenize
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

CHECKS = {
    "HTTP001": "Explicit verify=False disables TLS certificate verification.",
    "HTTP002": "Explicit timeout=None removes the HTTP timeout; check the deadline.",
    "HTTP003": "Client construction runs at import time; make ownership explicit.",
}
DEFAULT_EXCLUDES = (
    "tests/**",
    "**/tests/**",
    "test_*.py",
    "**/test_*.py",
    "*_test.py",
    "**/*_test.py",
    "conftest.py",
    "**/conftest.py",
    ".venv/**",
    "**/.venv/**",
    "build/**",
    "**/__pycache__/**",
)
CONSTRUCTORS = {"httpx2.Client", "httpx2.AsyncClient"}
REQUESTS = {"request", "get", "post", "put", "patch", "delete", "head", "options"}


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int
    column: int
    message: str


class Bindings(ast.NodeVisitor):
    """Collect function-local bindings without inspecting nested scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(a.asname or a.name.split(".")[0] for a in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(a.asname or a.name for a in node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass


class Checker(ast.NodeVisitor):
    def __init__(self, path: str, checks: Iterable[str]) -> None:
        self.path = path
        self.checks = set(checks)
        self.names: dict[str, str] = {}
        self.findings: list[Finding] = []
        self.deferred = 0

    def resolve(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self.names.get(node.id, "")
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            return f"{base}.{node.attr}" if base else ""
        return ""

    def bind(self, node: ast.AST, value: str = "") -> None:
        if isinstance(node, ast.Name):
            self.names[node.id] = value
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self.bind(element)

    def value_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Call) and self.resolve(node.func) in CONSTRUCTORS:
            return "httpx2-instance"
        return self.resolve(node)

    def add(self, code: str, node: ast.AST) -> None:
        if code in self.checks:
            self.findings.append(
                Finding(code, self.path, node.lineno, node.col_offset + 1, CHECKS[code])
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.names[name] = "httpx2" if alias.name == "httpx2" else ""

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.names[alias.asname or alias.name] = (
                f"httpx2.{alias.name}"
                if node.module == "httpx2" and node.level == 0
                else ""
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        value = self.value_type(node.value)
        for target in node.targets:
            self.bind(target, value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self.bind(node.target, self.value_type(node.value))

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.bind(node.target, self.value_type(node.value))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self.bind(node.target)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self.bind(target)

    def visit_Call(self, node: ast.Call) -> None:
        name = self.resolve(node.func)
        constructor = name in CONSTRUCTORS
        module_call = name in {f"httpx2.{method}" for method in REQUESTS | {"stream"}}
        client_call = name in {
            f"httpx2-instance.{method}" for method in REQUESTS | {"stream", "send"}
        }
        if constructor and self.deferred == 0:
            self.add("HTTP003", node)
        if constructor or module_call or client_call:
            for keyword in node.keywords:
                if not isinstance(keyword.value, ast.Constant):
                    continue
                if keyword.arg == "verify" and keyword.value.value is False:
                    self.add("HTTP001", keyword)
                if keyword.arg == "timeout" and keyword.value.value is None:
                    self.add("HTTP002", keyword)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Defaults/decorators execute when defining the function, unlike its body.
        for value in [
            *node.decorator_list,
            *node.args.defaults,
            *node.args.kw_defaults,
        ]:
            if value is not None:
                self.visit(value)
        self.names[node.name] = ""
        previous = self.names
        self.names = previous.copy()
        bindings = Bindings()
        for statement in node.body:
            bindings.visit(statement)
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg:
            args.append(node.args.vararg)
        if node.args.kwarg:
            args.append(node.args.kwarg)
        for name in bindings.names | {argument.arg for argument in args}:
            self.names[name] = ""
        self.deferred += 1
        for statement in node.body:
            self.visit(statement)
        self.deferred -= 1
        self.names = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Dynamic lambdas are outside this checker's supported binding analysis.
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for value in [*node.decorator_list, *node.bases]:
            self.visit(value)
        previous = self.names
        self.names = previous.copy()
        for statement in node.body:
            self.visit(statement)
        self.names = previous
        self.names[node.name] = ""

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self.bind(item.optional_vars, self.value_type(item.context_expr))
        for statement in node.body:
            self.visit(statement)

    visit_AsyncWith = visit_With

    def visit_If(self, node: ast.If) -> None:
        # Entry-point construction is intentional, rather than an import side effect.
        main_guard = (
            isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
        )
        self.visit(node.test)
        self.deferred += int(main_guard)
        for statement in node.body:
            self.visit(statement)
        self.deferred -= int(main_guard)
        for statement in node.orelse:
            self.visit(statement)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self.bind(node.target)
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type:
            self.visit(node.type)
        if node.name:
            self.names[node.name] = ""
        for statement in node.body:
            self.visit(statement)

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        # Comprehension targets have their own scope; their first iterable does not.
        self.visit(node.generators[0].iter)
        previous = self.names
        self.names = previous.copy()
        deferred = int(isinstance(node, ast.GeneratorExp))
        self.deferred += deferred
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self.bind(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.deferred -= deferred
        self.names = previous

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def excluded(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def scan_paths(
    paths: Iterable[Path],
    *,
    root: Path,
    excludes: Iterable[str] = DEFAULT_EXCLUDES,
    checks: Iterable[str] = CHECKS,
) -> tuple[list[Finding], list[dict[str, str]]]:
    findings: list[Finding] = []
    errors: list[dict[str, str]] = []
    seen: set[Path] = set()
    root = root.resolve()
    for supplied in paths:
        if not supplied.exists():
            errors.append({"path": str(supplied), "message": "Path does not exist"})
            continue
        try:
            candidates = (
                sorted(supplied.rglob("*.py")) if supplied.is_dir() else [supplied]
            )
        except OSError as exc:
            errors.append({"path": str(supplied), "message": str(exc)})
            continue
        for candidate in candidates:
            path = candidate.resolve()
            if path in seen:
                continue
            seen.add(path)
            if not path.is_relative_to(root):
                errors.append(
                    {"path": str(candidate), "message": "Outside project root"}
                )
                continue
            relative = path.relative_to(root).as_posix()
            if path.suffix != ".py" or excluded(relative, excludes):
                continue
            try:
                with tokenize.open(path) as source:
                    tree = ast.parse(source.read(), filename=relative)
                checker = Checker(relative, checks)
                checker.visit(tree)
                findings.extend(checker.findings)
            except (OSError, SyntaxError, UnicodeError) as exc:
                errors.append({"path": relative, "message": str(exc)})
            except RecursionError:
                errors.append(
                    {
                        "path": relative,
                        "message": "Python syntax exceeds checker nesting limit",
                    }
                )
    findings.sort(key=lambda finding: (finding.path, finding.line, finding.code))
    return findings, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path(".")])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--check", action="append", choices=list(CHECKS))
    parser.add_argument("--include-tests", action="store_true")
    args = parser.parse_args()
    patterns = (() if args.include_tests else DEFAULT_EXCLUDES) + tuple(args.exclude)
    findings, errors = scan_paths(
        args.paths, root=args.root, excludes=patterns, checks=args.check or CHECKS
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "version": 1,
                    "findings": [asdict(f) for f in findings],
                    "errors": errors,
                }
            )
        )
    else:
        for finding in findings:
            print(
                f"{finding.path}:{finding.line}:{finding.column}: "
                f"{finding.code} {finding.message}"
            )
        for error in errors:
            print(f"{error['path']}: {error['message']}", file=sys.stderr)
    return 2 if errors else int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
