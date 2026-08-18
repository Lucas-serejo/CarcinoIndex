# M1 — SAM 2.1 Hiera Small em Windows nativo

## Objetivo e escopo

Esta milestone verifica exclusivamente a viabilidade técnica do SAM 2.1
Hiera Small no Windows nativo: ambiente isolado, CUDA, instalação do pacote
oficial, carregamento do checkpoint e inferência em uma imagem sintética.

O SAM 2.1 foi escolhido para substituir definitivamente o SAM original no
CarcinoIndex. A M2 implementou o wrapper definitivo e atualizou o notebook,
sem integrar o modelo ao FastAPI; essa integração permanece reservada à M3.

Nenhuma imagem clínica foi utilizada.

## Ambiente validado

- Sistema: Windows x64, build 26200.
- Python: CPython 3.11.4.
- Ambiente virtual: `CarcinoIndex/.venv`.
- pip: 26.1.2.
- PyTorch: 2.6.0+cu124.
- torchvision: 0.21.0+cu124.
- CUDA incluída na wheel: 12.4.
- Driver NVIDIA: 596.49.
- CUDA informada pelo driver: 13.2.
- GPU: NVIDIA GeForce RTX 3060 Laptop GPU.
- VRAM detectada pelo PyTorch: 6.441.926.656 bytes.
- `torch.cuda.is_available()`: `True`.
- `torch.cuda.is_bf16_supported()`: `True`.

A versão CUDA mostrada pelo `nvidia-smi` representa a capacidade do driver.
Ela não é a versão do runtime incluído na wheel do PyTorch. Não foi instalado
CUDA Toolkit, NVCC ou Visual Studio Build Tools.

## Instalação do SAM 2

- Origem: `https://github.com/facebookresearch/sam2.git`.
- Commit validado: `2b90b9f5ceec907a1c18123530e92e794ad901a4`.
- Instalação: editável, a partir do clone oficial externo.
- Pacote instalado: `SAM-2==1.0`.
- Caminho lógico da configuração:
  `configs/sam2.1/sam2.1_hiera_s.yaml`.
- Extensão CUDA opcional: desativada com `SAM2_BUILD_CUDA=0`.
- Verificação adicional: o módulo `sam2._C` não está presente.
- Consequência: o pós-processamento opcional de pequenos buracos e
  componentes isolados não é executado.

O código-fonte do SAM 2 e o checkpoint permanecem fora do CarcinoIndex, em um
diretório irmão. O `backend/requirements.txt` não declara provisoriamente o
SAM 2 porque esta milestone usa a instalação editável do clone oficial.

## Checkpoint

- Nome: `sam2.1_hiera_small.pt`.
- Origem:
  `https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt`.
- Local: `sam2/checkpoints/sam2.1_hiera_small.pt`, no clone externo.
- Tamanho: 184.416.285 bytes.
- SHA-256:
  `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38`.

O hash foi calculado localmente para reprodutibilidade. A documentação
oficial consultada não publica um checksum esperado para comparação.

## Comandos principais executados

Na raiz do CarcinoIndex:

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

No diretório-pai do CarcinoIndex:

```powershell
git clone https://github.com/facebookresearch/sam2.git sam2
```

Na raiz do clone oficial:

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

Validações e inferência, novamente na raiz do CarcinoIndex:

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

## Resultado da inferência FP32

- Status: sucesso na primeira execução de inferência.
- Imagem: RGB sintética 512 × 512.
- Prompt: bounding box XYXY
  `[141.2, 156.2, 390.8, 365.8]`.
- Dtype: FP32.
- `torch.inference_mode()`: habilitado.
- `torch.compile`: desabilitado.
- Tempo de carregamento: 2,1297 s.
- Tempo de `set_image`: 0,9909 s.
- Tempo de `predict`: 0,4483 s.
- Score da máscara selecionada: 0,9841576.
- Índice da máscara selecionada: 1 de três máscaras.
- Pixels positivos: 32.264.
- Pico de VRAM alocada: 653.696.512 bytes.
- Pico de VRAM reservada: 887.095.296 bytes.

Artefatos locais, deliberadamente ignorados pelo Git:

- `experiments/outputs/sam2_feasibility/input.png`
- `experiments/outputs/sam2_feasibility/mask.png`
- `experiments/outputs/sam2_feasibility/overlay.png`
- `experiments/outputs/sam2_feasibility/metadata.json`

O BF16 é suportado pela GPU, mas não foi necessário para concluir a M1 e não
foi testado nesta execução.

## Advertências e limitações

- O projeto oficial recomenda fortemente WSL/Ubuntu para instalações em
  Windows. Esta prova demonstrou que o fluxo mínimo de imagem funciona no
  Windows nativo desta máquina.
- A extensão CUDA opcional foi intencionalmente desativada.
- A imagem é sintética e geometricamente simples.
- Não houve avaliação clínica nem avaliação de qualidade em laparoscopia.
- O resultado não demonstra desempenho em vídeo, treinamento ou
  fine-tuning.
- O Git exigiu `safe.directory` por comando devido a uma diferença de SID.
  Nenhuma configuração global do Git foi modificada.
- A primeira tentativa de atualizar ferramentas do pip foi bloqueada pela
  restrição de rede do ambiente de execução. A mesma operação foi repetida
  com acesso de rede autorizado e concluída.

## Wrapper adotado na M2

`backend/ai/segmentation/sam_segmenter.py` expõe `SAM2Segmenter` e
`SegmentationResult`. O ciclo de vida é explícito:

1. `load()` carrega o checkpoint externo;
2. `set_image()` calcula o embedding RGB;
3. `segment_with_box()` ou `segment_with_points()` executa o prompt;
4. `clear_image()` descarta apenas o embedding;
5. `close()` libera predictor e modelo.

Todas as máscaras e scores são retornados, com seleção padrão do maior
score. Esse score estima a qualidade da máscara segundo o modelo; não é
confiança clínica. A máscara automática não é *ground truth*.

O checkpoint continua externo ao CarcinoIndex, e a instalação do SAM 2
continua sendo feita a partir do clone oficial em modo editável. Imagens
clínicas, checkpoints e outputs de inferência não devem ser versionados.
