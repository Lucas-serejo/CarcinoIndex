**Language:** English · [Português](sam2_windows_setup.pt-BR.md)

# M1 — SAM 2.1 Hiera Small on native Windows

> **Historical record (M1/M2).** This document preserves the validated
> environment and the decisions of milestones M1 and M2. The integration of
> SAM 2.1 into the API, described below as reserved for M3, has since been
> implemented; the current behavior is in the
> [SAM 2.1 inference contract](../architecture/sam2_inference_contract.md).

## Objective and scope

This milestone verifies only the technical feasibility of SAM 2.1 Hiera Small
on native Windows: isolated environment, CUDA, installation of the official
package, checkpoint loading and inference on a synthetic image.

SAM 2.1 was chosen to permanently replace the original SAM in CarcinoIndex. M2
implemented the definitive wrapper and updated the notebook, without integrating
the model into FastAPI; that integration remains reserved for M3.

No clinical image was used.

## Validated environment

- System: Windows x64, build 26200.
- Python: CPython 3.11.4.
- Virtual environment: `CarcinoIndex/.venv`.
- pip: 26.1.2.
- PyTorch: 2.6.0+cu124.
- torchvision: 0.21.0+cu124.
- CUDA bundled in the wheel: 12.4.
- NVIDIA driver: 596.49.
- CUDA reported by the driver: 13.2.
- GPU: NVIDIA GeForce RTX 3060 Laptop GPU.
- VRAM detected by PyTorch: 6,441,926,656 bytes.
- `torch.cuda.is_available()`: `True`.
- `torch.cuda.is_bf16_supported()`: `True`.

The CUDA version shown by `nvidia-smi` reflects the driver's capability. It is
not the version of the runtime bundled in the PyTorch wheel. No CUDA Toolkit,
NVCC or Visual Studio Build Tools were installed.

## SAM 2 installation

- Source: `https://github.com/facebookresearch/sam2.git`.
- Validated commit: `2b90b9f5ceec907a1c18123530e92e794ad901a4`.
- Installation: editable, from the external official clone.
- Installed package: `SAM-2==1.0`.
- Logical config path:
  `configs/sam2.1/sam2.1_hiera_s.yaml`.
- Optional CUDA extension: disabled with `SAM2_BUILD_CUDA=0`.
- Additional check: the `sam2._C` module is not present.
- Consequence: the optional post-processing of small holes and isolated
  components is not executed.

The SAM 2 source code and the checkpoint stay outside CarcinoIndex, in a sibling
directory. `backend/requirements.txt` provisionally does not declare SAM 2
because this milestone uses the editable installation of the official clone.

## Checkpoint

- Name: `sam2.1_hiera_small.pt`.
- Source:
  `https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt`.
- Location: `sam2/checkpoints/sam2.1_hiera_small.pt`, in the external clone.
- Size: 184,416,285 bytes.
- SHA-256:
  `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38`.

The hash was computed locally for reproducibility. The official documentation
consulted does not publish an expected checksum for comparison.

## Main commands executed

At the CarcinoIndex root:

```powershell
$basePython = (Get-Command python).Source
& $basePython --version
& $basePython -m venv .venv

$projectPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $projectPython -m pip install --upgrade pip setuptools wheel
& $projectPython -m pip install `
  torch==2.6.0 `
  torchvision==0.21.0 `
  --index-url https://download.pytorch.org/whl/cu124

& $projectPython -m pip check
& $projectPython -c "import torch, torchvision; assert torch.cuda.is_available(); x = torch.arange(16, device='cuda'); print(x.sum().item())"
```

In the parent directory of CarcinoIndex:

```powershell
git clone https://github.com/facebookresearch/sam2.git sam2
```

At the root of the official clone:

```powershell
$env:SAM2_BUILD_CUDA = "0"
& $projectPython -m pip install -e .
Remove-Item Env:SAM2_BUILD_CUDA

Invoke-WebRequest `
  -Uri "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt" `
  -OutFile ".\checkpoints\sam2.1_hiera_small.pt"

Get-FileHash `
  -LiteralPath ".\checkpoints\sam2.1_hiera_small.pt" `
  -Algorithm SHA256
```

Validation and inference, again at the CarcinoIndex root:

```powershell
& $projectPython .\scripts\check_sam2_environment.py `
  --sam2-repo ..\sam2 `
  --checkpoint ..\sam2\checkpoints\sam2.1_hiera_small.pt

& $projectPython .\scripts\run_sam2_feasibility.py `
  --sam2-repo ..\sam2 `
  --checkpoint ..\sam2\checkpoints\sam2.1_hiera_small.pt `
  --output .\experiments\outputs\sam2_feasibility `
  --device cuda `
  --image-size 512 `
  --dtype fp32
```

## FP32 inference result

- Status: success on the first inference run.
- Image: synthetic RGB 512 × 512.
- Prompt: XYXY bounding box
  `[141.2, 156.2, 390.8, 365.8]`.
- Dtype: FP32.
- `torch.inference_mode()`: enabled.
- `torch.compile`: disabled.
- Load time: 2.1297 s.
- `set_image` time: 0.9909 s.
- `predict` time: 0.4483 s.
- Selected mask score: 0.9841576.
- Selected mask index: 1 of three masks.
- Positive pixels: 32,264.
- Peak allocated VRAM: 653,696,512 bytes.
- Peak reserved VRAM: 887,095,296 bytes.

Local artifacts, deliberately ignored by Git:

- `experiments/outputs/sam2_feasibility/input.png`
- `experiments/outputs/sam2_feasibility/mask.png`
- `experiments/outputs/sam2_feasibility/overlay.png`
- `experiments/outputs/sam2_feasibility/metadata.json`

BF16 is supported by the GPU, but it was not needed to complete M1 and was not
tested in this run.

## Caveats and limitations

- The official project strongly recommends WSL/Ubuntu for Windows
  installations. This proof showed that the minimal image flow works on this
  machine's native Windows.
- The optional CUDA extension was intentionally disabled.
- The image is synthetic and geometrically simple.
- There was no clinical evaluation and no quality evaluation on laparoscopy.
- The result does not demonstrate performance on video, training or
  fine-tuning.
- Git required a per-command `safe.directory` because of a SID difference. No
  global Git configuration was modified.
- The first attempt to upgrade the pip tooling was blocked by the execution
  environment's network restriction. The same operation was repeated with
  authorized network access and completed.

## Wrapper adopted in M2

`backend/ai/segmentation/sam_segmenter.py` exposes `SAM2Segmenter` and
`SegmentationResult`. The lifecycle is explicit:

1. `load()` loads the external checkpoint;
2. `set_image()` computes the RGB embedding;
3. `segment_with_box()` or `segment_with_points()` runs the prompt;
4. `clear_image()` discards only the embedding;
5. `close()` releases the predictor and the model.

All masks and scores are returned, with the highest score selected by default.
This score estimates mask quality according to the model; it is not clinical
confidence. The automatic mask is not *ground truth*.

The checkpoint remains external to CarcinoIndex, and SAM 2 is still installed
from the official clone in editable mode. Clinical images, checkpoints and
inference outputs must not be versioned.
