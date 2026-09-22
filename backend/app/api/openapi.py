"""Global OpenAPI metadata for the CarcinoIndex API."""

API_TITLE = "CarcinoIndex API"
API_VERSION = "0.3.0"
API_DESCRIPTION = (
    "CarcinoIndex is an experimental API for human-in-the-loop segmentation of "
    "peritoneal lesions using SAM 2.1, recording specialist-model interactions, "
    "and computational support for Peritoneal Cancer Index (PCI) assessment. "
    "Clinical LS assessments are provided by the user, not predicted by SAM.\n\n"
    "The system is not intended for autonomous diagnosis."
)
OPENAPI_TAGS = [
    {"name": "Health", "description": "API and segmentation model health information."},
    {"name": "PCI", "description": "PCI regions and manual PCI composition."},
    {
        "name": "Segmentation",
        "description": "Human-guided SAM 2.1 segmentation using bounding boxes or point prompts.",
    },
]
