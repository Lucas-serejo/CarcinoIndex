from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

import pytest
import torch
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.app.core.config import Settings
from backend.app.main import create_app


CHECKPOINT = os.getenv("SAM2_CHECKPOINT")


@pytest.mark.sam2_api_integration
@pytest.mark.skipif(
    not CHECKPOINT or not torch.cuda.is_available(),
    reason="Set SAM2_CHECKPOINT and provide CUDA to run the API integration test.",
)
def test_real_cuda_api_segmentation_uses_synthetic_image() -> None:
    source = Image.new("RGB", (128, 128), (15, 15, 15))
    ImageDraw.Draw(source).rectangle((32, 32, 95, 95), fill=(210, 125, 75))
    content = io.BytesIO()
    source.save(content, format="PNG")

    app = create_app(
        settings=Settings(
            sam2_checkpoint_path=Path(CHECKPOINT),
            sam2_device="cuda",
            sam2_dtype="float32",
        )
    )
    with TestClient(app) as client:
        health = client.get("/health")
        response = client.post(
            "/api/v1/segmentations",
            data={
                "region_id": "0",
                "prompt_type": "box",
                "box": "[28, 28, 100, 100]",
                "multimask_output": "true",
                "ls_source": "user",
            },
            files={"image": ("synthetic.png", content.getvalue(), "image/png")},
        )
        partial = client.post(
            "/api/v1/pci/calculate",
            json={
                "protocol_id": "sugarbaker_pci",
                "protocol_version": "project-defined-v1",
                "observations": [
                    {
                        "observation_id": "real-api-0",
                        "region_id": 0,
                        "ls_score": 1,
                        "ls_source": "user",
                    }
                ],
            },
        )
        complete = client.post(
            "/api/v1/pci/calculate",
            json={
                "protocol_id": "sugarbaker_pci",
                "protocol_version": "project-defined-v1",
                "observations": [
                    {
                        "observation_id": f"real-api-{region}",
                        "region_id": region,
                        "ls_score": 1,
                        "ls_source": "user",
                    }
                    for region in range(13)
                ],
            },
        )

    assert health.status_code == 200
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["region"]["region_id"] == 0
    assert body["ls_assessment"] is None
    assert body["metadata"]["model_name"] == "sam2.1_hiera_small"
    png = base64.b64decode(body["mask"]["data"], validate=True)
    with Image.open(io.BytesIO(png)) as mask:
        assert mask.size == (128, 128)
    assert partial.status_code == 200
    assert partial.json()["subtotal"] == 1
    assert partial.json()["pci_total"] is None
    assert complete.status_code == 200
    assert complete.json()["pci_total"] == 13
    assert app.state.segmentation_service is None
    print(
        json.dumps(
            {
                "selected_score": body["metadata"]["selected_score"],
                "load_time_seconds": body["metadata"]["load_time_seconds"],
                "embedding_time_seconds": body["metadata"]["embedding_time_seconds"],
                "prediction_time_seconds": body["metadata"][
                    "prediction_time_seconds"
                ],
                "peak_vram_bytes": body["metadata"]["peak_vram_bytes"],
                "mask_png_bytes": len(png),
                "mask_dimensions": [
                    body["mask"]["width"],
                    body["mask"]["height"],
                ],
                "partial_subtotal": partial.json()["subtotal"],
                "complete_pci_total": complete.json()["pci_total"],
            },
            sort_keys=True,
        )
    )
