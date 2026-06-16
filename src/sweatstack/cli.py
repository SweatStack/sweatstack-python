import ast
from pathlib import Path

import httpx

from datamodel_code_generator import InputFileType, generate
from datamodel_code_generator import DataModelType


def _bind_sport_to_ost(path: Path) -> None:
    """Replace the codegen'd ``Sport`` enum with OpenSportTaxonomy's pydantic field.

    The API speaks OpenSportTaxonomy, so ``sport`` fields are consumed via OST's permissive
    ``SportField``: it validates inbound values to an ``open_sport_taxonomy.Sport`` and serialises
    back to the canonical wire string, tolerating sports newer than the bundled taxonomy. Anchored on
    the AST (not a text match) so it survives regeneration; the import is injected where the class was,
    safely past the module's ``from __future__`` header.
    """
    src = path.read_text()
    cls = next(
        node for node in ast.parse(src).body
        if isinstance(node, ast.ClassDef) and node.name == "Sport"  # the enum carries no decorators
    )
    lines = src.splitlines(keepends=True)
    lines[cls.lineno - 1:cls.end_lineno] = [
        "from open_sport_taxonomy.pydantic import SportField as Sport  # OST sport type (see schemas.py)\n",
    ]
    path.write_text("".join(lines))


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

    model = output.read_text()
    print(model)
