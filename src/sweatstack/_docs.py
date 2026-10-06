"""Check Python snippets in docs against the installed SDK.

    python -m sweatstack._docs check README.md docs/ skills/

Finds the Python code in Markdown files (fenced ``python`` or ``py`` blocks, also indented
inside tabs), in ``.py`` files, and in docstrings, and reports every call into the SDK that
the installed version doesn't support: a method or attribute that doesn't exist (with the
replacement, for removed names), a keyword the method doesn't take, too many positional
arguments, or code that doesn't parse.

Calls are resolved statically, without running anything: from ``sweatstack`` (or what it was
imported as), from any name ending in ``client`` (``client``, ``auth.client``, ``athlete_client``),
and from names bound to a ``Client`` (``coach = Client()``, ``athlete = coach.delegated_client(u)``),
through the typed resource attributes (``client.activities.longitudinal.data``). Anything it
can't resolve, it leaves alone.

A block preceded by ``<!-- docs: skip -->`` is not checked. Stdlib only; not imported by
``sweatstack`` itself.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import re
import sys
import textwrap
import typing
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

SKIP_MARKER = "<!-- docs: skip -->"

_FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```(?:python|py)\b[^\n]*\n(?P<code>.*?)^(?P=indent)```",
    re.S | re.M,
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass
class Report:
    findings: list[Finding]
    blocks: int
    skipped: int


# ---------------------------------------------------------------------------
# Extracting code
# ---------------------------------------------------------------------------


def markdown_blocks(text: str) -> Iterator[tuple[int, str, bool]]:
    """``(first line, code, skipped)`` for each fenced Python block in Markdown."""
    for match in _FENCE.finditer(text):
        start = text[: match.start()].count("\n")
        before = text[: match.start()].rstrip().rsplit("\n", 1)[-1].strip()
        code = textwrap.dedent(match.group("code"))
        yield start + 2, code, before == SKIP_MARKER


def docstring_blocks(doc: str) -> Iterator[tuple[int, str]]:
    """``(first line, code)`` for each fenced Python block in a docstring."""
    for line, code, skipped in markdown_blocks(inspect.cleandoc(doc)):
        if not skipped:
            yield line, code


# ---------------------------------------------------------------------------
# Resolving names against the SDK
# ---------------------------------------------------------------------------


def _sdk():
    import sweatstack
    from sweatstack.client import Client

    return sweatstack, Client


def _instance_attributes(cls: type) -> set[str]:
    """Attributes ``__init__`` assigns, which are not visible on the class."""
    try:
        source = inspect.getsource(cls.__init__)
    except (OSError, TypeError):
        return set()
    return set(re.findall(r"self\.(\w+)\s*(?::[^=\n]+)?=", source))


def _return_class(function: Any) -> type | None:
    """The class a function or property returns, if it is a single class."""
    try:
        hint = typing.get_type_hints(function).get("return")
    except Exception:
        return None
    return hint if isinstance(hint, type) else None


class _Scope:
    """What the names in one snippet stand for, as far as the checker can tell."""

    def __init__(self) -> None:
        self.sweatstack, self.client_class = _sdk()
        self.modules: set[str] = set()  # names bound to the sweatstack module
        self.bound: dict[str, Any] = {}  # names bound to an SDK class, instance or function

    def resolve(self, node: ast.expr) -> Any:
        """What an expression refers to: a module, a class (for instances), a function, or None."""
        if isinstance(node, ast.Name):
            if node.id in self.modules:
                return self.sweatstack
            if node.id in self.bound:
                return self.bound[node.id]
            if node.id.endswith("client"):
                return self.client_class
            return None
        if isinstance(node, ast.Attribute):
            owner = self.resolve(node.value)
            owned = isinstance(owner, type) and _has_checked_attributes(owner)
            if node.attr.endswith("client") and not owned and owner is not self.sweatstack:
                # auth.client, user.client: the helpers' per-user clients. On the client itself,
                # names like delegated_client are methods and resolve below.
                return self.client_class
            return self.member(owner, node.attr)
        if isinstance(node, ast.Call):
            return self.returns(self.resolve(node.func))
        return None

    def member(self, owner: Any, name: str) -> Any:
        if owner is None:
            return None
        if owner is self.sweatstack:
            value = getattr(owner, name, None)
            return type(value) if _is_resource(value) else value
        if isinstance(owner, type) and _has_checked_attributes(owner):
            attribute = inspect.getattr_static(owner, name, None)
            if isinstance(attribute, cached_property):
                return _return_class(attribute.func)
            if isinstance(attribute, property):
                return None
            return attribute if inspect.isfunction(attribute) else None
        return None

    def returns(self, target: Any) -> Any:
        if isinstance(target, type) and _is_sdk_class(target):
            return target  # a constructor call returns an instance of the class
        if inspect.isfunction(target):
            returned = _return_class(target)
            return returned if returned is not None and _is_sdk_class(returned) else None
        return None


def _is_sdk_class(cls: type) -> bool:
    return cls.__module__.startswith("sweatstack.")


def _has_checked_attributes(cls: type) -> bool:
    """Classes whose attributes the checker verifies: the client and its resources.

    Response models are left alone: their fields are not class attributes, and checking field
    access is out of scope.
    """
    from sweatstack.client import Client
    from sweatstack.resources._base import Resource

    return issubclass(cls, (Client, Resource))


def _is_resource(value: Any) -> bool:
    from sweatstack.resources._base import Resource

    return isinstance(value, Resource)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


class _Checker(ast.NodeVisitor):
    def __init__(self, path: str, first_line: int) -> None:
        self.path = path
        self.offset = first_line - 1
        self.scope = _Scope()
        self.findings: list[Finding] = []

    def report(self, node: ast.AST, message: str) -> None:
        self.findings.append(Finding(self.path, self.offset + getattr(node, "lineno", 1), message))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "sweatstack":
                self.scope.modules.add(alias.asname or "sweatstack")
            elif alias.name.startswith("sweatstack."):
                self._import_module(node, alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module or node.module.split(".")[0] != "sweatstack":
            return
        module = self._import_module(node, node.module)
        if module is None:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            value = getattr(module, alias.name, None)
            if value is None and not _is_submodule(node.module, alias.name):
                self.report(node, self._missing(node.module, alias.name))
            elif value is not None and (inspect.isclass(value) or inspect.isfunction(value)):
                self.scope.bound[alias.asname or alias.name] = value

    def _import_module(self, node: ast.AST, name: str):
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as error:
            if error.name and (error.name == name or name.startswith(error.name + ".")):
                self.report(node, f"module {name!r} does not exist")
            return None  # an optional dependency of the module is missing: can't check it
        except ImportError:
            return None

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        value = self.scope.resolve(node.value) if isinstance(node.value, ast.Call) else None
        for target in node.targets:
            if isinstance(target, ast.Name):
                if isinstance(value, type) and _is_sdk_class(value):
                    self.scope.bound[target.id] = value
                else:
                    self.scope.bound.pop(target.id, None)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if isinstance(item.optional_vars, ast.Name) and isinstance(item.context_expr, ast.Call):
                value = self.scope.resolve(item.context_expr)
                if isinstance(value, type) and _is_sdk_class(value):
                    self.scope.bound[item.optional_vars.id] = value
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.generic_visit(node)
        owner = self.scope.resolve(node.value)
        if owner is None or not isinstance(node.ctx, ast.Load):
            return
        if owner is self.scope.sweatstack:
            if not hasattr(owner, node.attr) and not _is_submodule("sweatstack", node.attr):
                self.report(node, self._missing("sweatstack", node.attr))
        elif isinstance(owner, type) and _has_checked_attributes(owner):
            if not _has_attribute(owner, node.attr):
                self.report(node, self._missing(owner.__name__, node.attr))

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        target = self.scope.resolve(node.func)
        if isinstance(target, type) and _is_sdk_class(target):
            self._check_signature(node, target, f"{target.__name__}()", skip_self=False)
        elif inspect.isfunction(target) and target.__module__.startswith("sweatstack"):
            name = f"{target.__qualname__}()"
            self._check_signature(node, target, name, skip_self="." in target.__qualname__)

    def _check_signature(self, node: ast.Call, function: Any, name: str, *, skip_self: bool):
        try:
            parameters = list(inspect.signature(function).parameters.values())
        except (TypeError, ValueError):
            return
        if skip_self and parameters and parameters[0].name == "self":
            parameters = parameters[1:]
        kinds = {p.kind for p in parameters}
        names = {p.name for p in parameters if p.kind is not p.POSITIONAL_ONLY}
        if inspect.Parameter.VAR_KEYWORD not in kinds:
            for keyword in node.keywords:
                if keyword.arg is not None and keyword.arg not in names:
                    self.report(node, f"{name} has no keyword argument {keyword.arg!r}")
        elided = any(
            isinstance(arg, ast.Starred)
            or (isinstance(arg, ast.Constant) and arg.value is Ellipsis)
            for arg in node.args
        )
        if inspect.Parameter.VAR_POSITIONAL not in kinds and not elided:
            positional = [
                p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
            if len(node.args) > len(positional):
                self.report(
                    node,
                    f"{name} takes {len(positional)} positional argument(s), got {len(node.args)}",
                )

    def _missing(self, owner: str, name: str) -> str:
        from sweatstack._renames import REMOVED_IN

        message = f"{owner} has no attribute {name!r}"
        if name in REMOVED_IN:
            release, hint = REMOVED_IN[name]
            prefix = "sweatstack" if owner.startswith("sweatstack") else "client"
            message += f" (removed in {release}; use {hint.format(c=prefix)})"
        return message


def _has_attribute(cls: type, name: str) -> bool:
    return inspect.getattr_static(cls, name, None) is not None or name in _instance_attributes(cls)


def _is_submodule(package: str, name: str) -> bool:
    return importlib.util.find_spec(f"{package}.{name}") is not None


def check_code(code: str, path: str = "<code>", first_line: int = 1) -> list[Finding]:
    """Findings for one block of Python code."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [Finding(path, first_line - 1 + (error.lineno or 1), f"syntax error: {error.msg}")]
    checker = _Checker(path, first_line)
    checker.visit(tree)
    return checker.findings


def check_paths(paths: list[Path]) -> Report:
    """Check every Markdown and Python file under ``paths``."""
    report = Report(findings=[], blocks=0, skipped=0)
    for path in _files(paths):
        text = path.read_text()
        if path.suffix == ".py":
            report.blocks += 1
            report.findings += check_code(text, str(path))
            continue
        for line, code, skipped in markdown_blocks(text):
            if skipped:
                report.skipped += 1
                continue
            report.blocks += 1
            report.findings += check_code(code, str(path), line)
    return report


def _files(paths: list[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                hidden = any(part.startswith(".") for part in child.relative_to(path).parts)
                if child.suffix in (".md", ".py") and not hidden:
                    yield child
        elif path.suffix in (".md", ".py"):
            yield path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[0] != "check":
        print("usage: python -m sweatstack._docs check PATH [PATH ...]", file=sys.stderr)
        return 2
    report = check_paths([Path(arg) for arg in args[1:]])
    for finding in report.findings:
        print(finding)
    print(
        f"{report.blocks} block(s) checked, {report.skipped} skipped, "
        f"{len(report.findings)} finding(s)",
        file=sys.stderr,
    )
    return 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
