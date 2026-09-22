from __future__ import annotations

import base64
import io
import json
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.ai.segmentation import (
    BoxPrompt,
    InvalidPromptError,
    PointsPrompt,
    SegmentationResult,
)
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services.segmentation_service import SegmentationService


def encoded_image(
    image_format: str,
    *,
    size: tuple[int, int] = (32, 24),
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (120, 80, 40)).save(output, format=image_format)
    return output.getvalue()


def animated_png() -> bytes:
    output = io.BytesIO()
    first = Image.new("RGB", (16, 16), (255, 0, 0))
    second = Image.new("RGB", (16, 16), (0, 255, 0))
    first.save(
        output,
        format="PNG",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    return output.getvalue()


class APIFakeSegmenter:
    is_loaded = True
    device = "cuda"
    dtype = "float32"

    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[np.ndarray, Any]] = []

    def infer(self, image: np.ndarray, prompt: Any) -> SegmentationResult:
        self.calls.append((image, prompt))
        if self.failure is not None:
            raise self.failure
        height, width, _ = image.shape
        if isinstance(prompt, BoxPrompt):
            x0, y0, x1, y1 = prompt.box
            if x0 < 0 or y0 < 0 or x0 >= x1 or y0 >= y1 or x1 > width or y1 > height:
                raise InvalidPromptError("box must stay within image bounds.")
            prompt_type = "box"
            prompt_data = {"box_xyxy": list(prompt.box)}
        elif isinstance(prompt, PointsPrompt):
            if any(
                x < 0 or y < 0 or x >= width or y >= height
                for x, y in prompt.points
            ):
                raise InvalidPromptError("points must stay within image bounds.")
            prompt_type = "points"
            prompt_data = {
                "points_xy": [list(point) for point in prompt.points],
                "labels": list(prompt.labels),
            }
        else:
            raise AssertionError("unexpected prompt")
        mask = np.zeros((height, width), dtype=bool)
        mask[4 : min(height, 18), 5 : min(width, 20)] = True
        return SegmentationResult(
            masks=np.stack([mask]),
            scores=np.asarray([0.88], dtype=np.float32),
            logits=None,
            selected_index=0,
            selected_mask=mask,
            selected_score=0.88,
            prompt_type=prompt_type,
            prompt_data=prompt_data,
            image_shape=image.shape,
            model_name="sam2.1_hiera_small",
            model_config="configs/sam2.1/sam2.1_hiera_s.yaml",
            checkpoint_name="sam2.1_hiera_small.pt",
            device="cuda",
            dtype="float32",
            load_time_seconds=1.0,
            embedding_time_seconds=0.2,
            prediction_time_seconds=0.1,
            peak_vram_bytes=1234,
        )

    def close(self) -> None:
        pass


@pytest.fixture
def fake_segmenter() -> APIFakeSegmenter:
    return APIFakeSegmenter()


@pytest.fixture
def client(fake_segmenter: APIFakeSegmenter) -> TestClient:
    settings = Settings(
        sam2_checkpoint_path=None,
        max_upload_bytes=1024 * 1024,
        max_image_width=64,
        max_image_height=64,
        max_image_pixels=4096,
    )
    service = SegmentationService(fake_segmenter)  # type: ignore[arg-type]
    with TestClient(create_app(settings=settings, segmentation_service=service)) as test_client:
        yield test_client


def segment(
    client: TestClient,
    *,
    image_format: str = "JPEG",
    content_type: str = "image/jpeg",
    data: dict[str, str] | None = None,
    content: bytes | None = None,
) -> Any:
    fields = {
        "region_id": "0",
        "prompt_type": "box",
        "box": json.dumps([2, 2, 25, 20]),
        "multimask_output": "true",
        "ls_source": "user",
    }
    if data:
        fields.update(data)
    payload = content if content is not None else encoded_image(image_format)
    return client.post(
        "/api/v1/segmentations",
        data=fields,
        files={"image": ("sample.jpg", payload, content_type)},
    )


def test_openapi_documents_existing_routes(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert [tag["name"] for tag in schema["tags"]] == ["Health", "PCI", "Segmentation"]
    expected = {
        "/health": ("get", "Health"),
        "/api/v1/pci/regions": ("get", "PCI"),
        "/api/v1/pci/calculate": ("post", "PCI"),
        "/api/v1/segmentations": ("post", "Segmentation"),
        "/api/v1/evaluations/{evaluation_id}/segmentations": ("post", "Segmentation"),
    }
    assert set(schema["paths"]) == set(expected)
    for path, (method, tag) in expected.items():
        operation = schema["paths"][path][method]
        assert operation["tags"] == [tag]
        assert operation["summary"]
        assert operation["description"]
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_health_reports_safe_model_status(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model": {
            "loaded": True,
            "name": "sam2.1_hiera_small",
            "device": "cuda",
            "dtype": "float32",
        },
    }


def test_regions_returns_centralized_catalog(client: TestClient) -> None:
    response = client.get("/api/v1/pci/regions")
    assert response.status_code == 200
    regions = response.json()["regions"]
    assert len(regions) == 13
    assert [region["region_id"] for region in regions] == list(range(13))
    assert regions[0]["code"] == "central"
    assert regions[-1]["code"] == "lower_ileum"


def test_box_segmentation_with_jpeg_and_manual_ls(
    client: TestClient,
    fake_segmenter: APIFakeSegmenter,
) -> None:
    response = segment(client, data={"ls_score": "2"})
    assert response.status_code == 200, response.text
    body = response.json()
    UUID(body["analysis_id"])
    assert body["region"] == {"region_id": 0, "region_name": "central"}
    assert body["ls_assessment"] == {"ls_score": 2, "source": "user"}
    assert body["metadata"]["selected_score"] == pytest.approx(0.88)
    assert isinstance(fake_segmenter.calls[0][1], BoxPrompt)
    assert fake_segmenter.calls[0][0].dtype == np.uint8
    assert fake_segmenter.calls[0][0].shape == (24, 32, 3)


def test_points_segmentation_with_png(client: TestClient) -> None:
    response = segment(
        client,
        image_format="PNG",
        content_type="image/png",
        data={
            "region_id": "6",
            "prompt_type": "points",
            "points": json.dumps([[10, 10], [2, 2]]),
            "labels": json.dumps([1, 0]),
            "box": None,  # type: ignore[dict-item]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["region"]["region_name"] == "pelvis"
    assert response.json()["metadata"]["prompt_type"] == "points"


def test_missing_ls_returns_null(client: TestClient) -> None:
    response = segment(client)
    assert response.status_code == 200
    assert response.json()["ls_assessment"] is None


def test_response_contains_decodable_png_with_dimensions(client: TestClient) -> None:
    response = segment(client)
    mask = response.json()["mask"]
    decoded = base64.b64decode(mask["data"], validate=True)
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.format == "PNG"
        assert image.size == (32, 24)
    assert mask["width"] == 32
    assert mask["height"] == 24


def test_response_contains_no_personal_paths(client: TestClient) -> None:
    serialized = segment(client).text
    assert "C:\\Users" not in serialized
    assert "lucas" not in serialized.lower()


def test_missing_upload_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/segmentations",
        data={"region_id": "0", "prompt_type": "box", "box": "[1,1,2,2]"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_invalid_region_is_422(client: TestClient) -> None:
    response = segment(client, data={"region_id": "13"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "box",
    ["[1, 2, 3]", '{"x": 1}', "[1, 1, true, 10]", "not-json"],
)
def test_invalid_box_is_422(client: TestClient, box: str) -> None:
    response = segment(client, data={"box": box})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_prompt"


def test_out_of_bounds_box_is_422(client: TestClient) -> None:
    response = segment(client, data={"box": "[0, 0, 100, 100]"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_prompt"


@pytest.mark.parametrize(
    ("points", "labels"),
    [
        ("[]", "[]"),
        ("[[1, 2]]", "[1, 0]"),
        ("[[1, 2, 3]]", "[1]"),
        ("[[1, 2]]", "[2]"),
    ],
)
def test_invalid_points_are_422(
    client: TestClient,
    points: str,
    labels: str,
) -> None:
    response = segment(
        client,
        data={
            "prompt_type": "points",
            "points": points,
            "labels": labels,
            "box": None,  # type: ignore[dict-item]
        },
    )
    assert response.status_code == 422


def test_unsupported_content_type_is_415(client: TestClient) -> None:
    response = segment(client, content_type="image/gif")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_declared_type_must_match_content(client: TestClient) -> None:
    response = segment(client, image_format="PNG", content_type="image/jpeg")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "media_type_mismatch"


def test_animated_png_is_rejected(client: TestClient) -> None:
    response = segment(
        client,
        image_format="PNG",
        content_type="image/png",
        content=animated_png(),
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "animated_image_unsupported"


def test_corrupted_image_is_422(client: TestClient) -> None:
    response = segment(client, content=b"not an image")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image"


def test_empty_image_is_422(client: TestClient) -> None:
    response = segment(client, content=b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_image"


def test_image_dimensions_over_limit_are_413(client: TestClient) -> None:
    response = segment(client, content=encoded_image("JPEG", size=(65, 10)))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_dimensions_exceeded"


def test_upload_over_byte_limit_is_413(fake_segmenter: APIFakeSegmenter) -> None:
    settings = Settings(max_upload_bytes=20)
    service = SegmentationService(fake_segmenter)  # type: ignore[arg-type]
    with TestClient(create_app(settings=settings, segmentation_service=service)) as client:
        response = segment(client)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"


def test_pixel_limit_is_413(fake_segmenter: APIFakeSegmenter) -> None:
    settings = Settings(
        max_image_width=100,
        max_image_height=100,
        max_image_pixels=100,
    )
    service = SegmentationService(fake_segmenter)  # type: ignore[arg-type]
    with TestClient(create_app(settings=settings, segmentation_service=service)) as client:
        response = segment(client, content=encoded_image("JPEG", size=(11, 10)))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_dimensions_exceeded"


def partial_pci_payload() -> dict[str, Any]:
    return {
        "protocol_id": "sugarbaker_pci",
        "protocol_version": "project-defined-v1",
        "observations": [
            {
                "observation_id": "obs-001",
                "region_id": 0,
                "ls_score": 1,
                "ls_source": "user",
            }
        ],
    }


def test_partial_pci_has_subtotal_but_no_total(client: TestClient) -> None:
    response = client.post("/api/v1/pci/calculate", json=partial_pci_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "incomplete"
    assert body["assessed_regions"] == [0]
    assert body["pending_regions"] == list(range(1, 13))
    assert body["subtotal"] == 1
    assert body["pci_total"] is None


@pytest.mark.parametrize("ls_score, expected", [(0, 0), (3, 39)])
def test_complete_pci_bounds(
    client: TestClient,
    ls_score: int,
    expected: int,
) -> None:
    payload = partial_pci_payload()
    payload["observations"] = [
        {
            "observation_id": f"obs-{region}",
            "region_id": region,
            "ls_score": ls_score,
            "ls_source": "user",
        }
        for region in range(13)
    ]
    response = client.post("/api/v1/pci/calculate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert response.json()["pci_total"] == expected


def test_multiple_observations_use_maximum(client: TestClient) -> None:
    payload = partial_pci_payload()
    payload["observations"].append(
        {
            "observation_id": "obs-002",
            "region_id": 0,
            "ls_score": 3,
            "ls_source": "user",
        }
    )
    response = client.post("/api/v1/pci/calculate", json=payload)
    regional = response.json()["regional_scores"][0]
    assert regional["ls_score"] == 3
    assert regional["source_observation_id"] == "obs-002"
    assert regional["observations_count"] == 2


def test_duplicate_observation_is_422(client: TestClient) -> None:
    payload = partial_pci_payload()
    payload["observations"].append(dict(payload["observations"][0]))
    response = client.post("/api/v1/pci/calculate", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_pci_observations"


def test_cuda_oom_is_mapped_to_503() -> None:
    segmenter = APIFakeSegmenter(RuntimeError("CUDA out of memory while predicting"))
    service = SegmentationService(segmenter)  # type: ignore[arg-type]
    with TestClient(create_app(settings=Settings(), segmentation_service=service)) as client:
        response = segment(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "cuda_out_of_memory"


def test_unavailable_service_is_mapped_to_503(
    fake_segmenter: APIFakeSegmenter,
) -> None:
    service = SegmentationService(fake_segmenter)  # type: ignore[arg-type]
    app = create_app(settings=Settings(), segmentation_service=service)
    with TestClient(app) as client:
        app.state.segmentation_service = None
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
