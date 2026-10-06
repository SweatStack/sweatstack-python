import ast
import re
from pathlib import Path

import httpx
from datamodel_code_generator import DataModelType, InputFileType, generate


def _bind_sport_to_ost(path: Path) -> None:
    """Type every ``sport`` / ``sports`` model field as OpenSportTaxonomy's permissive ``SportField``.

    The API exposes ``sport`` as a free-form OpenSportTaxonomy string, so datamodel-codegen types these
    fields as plain ``str``. We retype them to ``SportField``, which validates an inbound string to an
    ``open_sport_taxonomy.Sport`` and serialises back to the canonical wire string, tolerating sports
    newer than the bundled taxonomy. Any leftover generated ``Sport`` schema is dropped. Anchored on the
    AST (not a text match) and idempotent, so it survives regeneration.
    """
    src = path.read_text()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)

    drop: set[int] = set()  # 0-indexed lines to remove
    replace: dict[int, str] = {}  # 0-indexed line -> new text

    # Drop a leftover generated `Sport` schema (the server may still emit an unused one) ...
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Sport":
            drop.update(range(node.lineno - 1, node.end_lineno or node.lineno))
    # ... and any SportField import from a previous run (re-injected cleanly below).
    for i, line in enumerate(lines):
        if line.startswith("from open_sport_taxonomy.pydantic import SportField"):
            drop.add(i)

    # Retype every `sport` / `sports` field annotation: str -> SportField (str | None, list[str], ...).
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in ("sport", "sports")
        ):
            annotation = ast.get_source_segment(src, node.annotation)
            if annotation is None:
                continue
            retyped = re.sub(r"\bstr\b", "SportField", annotation)
            if retyped != annotation:
                i = node.lineno - 1
                replace[i] = lines[i].replace(annotation, retyped, 1)

    out: list[str] = []
    for i, line in enumerate(lines):
        if i in drop:
            continue
        out.append(replace.get(i, line))
        if line.startswith("from __future__ import annotations"):
            out.append(
                "from open_sport_taxonomy.pydantic import SportField  # OST sport type (see schemas.py)\n"
            )
    path.write_text("".join(out))


# Fields the server sends without a UTC offset, though the OpenAPI schema says date-time.
_NAIVE_OR_AWARE = {"registered_at", "backfill_loaded_until"}


def _restore_naive_local_datetimes(path: Path) -> None:
    """Type local timestamps as ``NaiveDatetime`` rather than ``AwareDatetime``.

    The API returns *local* timestamps without a timezone, but datamodel-codegen types every
    ``date-time`` field as ``AwareDatetime`` -- which rejects a naive value. Retype the local fields
    (those whose name ends in ``_local``) back to ``NaiveDatetime``, and let the fields the server
    sends without an offset (``registered_at``, ``backfill_loaded_until``) accept either. AST-anchored and idempotent, so it survives regeneration (and replaces the
    manual fixups this file has needed in the past).
    """
    src = path.read_text()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    replace: dict[int, str] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        name = node.target.id
        annotation = ast.get_source_segment(src, node.annotation)
        if annotation is None:
            continue
        if name.endswith("_local") and "AwareDatetime" in annotation:
            retyped = annotation.replace("AwareDatetime", "NaiveDatetime")
        elif name in _NAIVE_OR_AWARE and "NaiveDatetime" not in annotation:
            retyped = annotation.replace("AwareDatetime", "AwareDatetime | NaiveDatetime", 1)
        else:
            continue
        i = node.lineno - 1
        replace[i] = lines[i].replace(annotation, retyped, 1)

    if not replace:
        return  # already naive (idempotent re-run)

    src = "".join(replace.get(i, line) for i, line in enumerate(lines))
    if "    NaiveDatetime,\n" not in src:  # ensure the import exists
        src = src.replace("    AwareDatetime,\n", "    AwareDatetime,\n    NaiveDatetime,\n", 1)
    path.write_text(src)


def generate_response_models():
    response = httpx.get("http://localhost:8080/openapi.json")
    response.raise_for_status()
    output_directory = Path(__file__).parent
    output = Path(output_directory / "openapi_schemas.py")
    output.unlink(missing_ok=True)
    generate(
        response.text,
        input_file_type=InputFileType.OpenAPI,
        input_filename="openapi.json",
        output=output,
        # set up the output model types
        output_model_type=DataModelType.PydanticV2BaseModel,
    )
    _bind_sport_to_ost(output)
    _restore_naive_local_datetimes(output)

    model = output.read_text()
    print(model)
