import ast
from pathlib import Path

import httpx

from datamodel_code_generator import InputFileType, generate
from datamodel_code_generator import DataModelType


def _replace_sport_enum(path: Path) -> None:
    """Swap the codegen'd ``class Sport(Enum)`` for the OST-backed legacy-tolerant field.

    The server advertises ``sport`` as a legacy enum; we discard that generated enum and bind the
    name ``Sport`` to ``LegacySportField`` so every generated ``sport`` field decodes legacy *and* OST
    values to an ``open_sport_taxonomy.Sport`` (see plans/005_ost_sport_bridge.md). Anchored on the
    AST so it survives regeneration; the import is injected where the class was, safely past the
    module's ``from __future__`` header.

    TEMPORARY (OST migration): at the contract release, change the injected import to
    ``from open_sport_taxonomy.pydantic import SportField as Sport`` and drop the bridge.
    """
    src = path.read_text()
    cls = next(
        node for node in ast.parse(src).body
        if isinstance(node, ast.ClassDef) and node.name == "Sport"  # the enum carries no decorators
    )
    lines = src.splitlines(keepends=True)
    lines[cls.lineno - 1:cls.end_lineno] = [
        "from ._sport_bridge import LegacySportField\n",
        "Sport = LegacySportField  # OST adoption -- see plans/005; injected by cli.py\n",
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
    _replace_sport_enum(output)

    model = output.read_text()
    print(model)
