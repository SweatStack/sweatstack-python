import httpx
from pathlib import Path

from datamodel_code_generator import InputFileType, generate
from datamodel_code_generator import DataModelType


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

    model = output.read_text()
    print(model)