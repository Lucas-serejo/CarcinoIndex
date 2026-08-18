# Backend CarcinoIndex — M3

API experimental para segmentação assistida com SAM 2.1 Hiera Small e
composição manual do PCI. O SAM produz uma máscara a partir de box ou pontos;
ele não classifica lesões. O LS é opcional e sempre informado pelo usuário.

## Configuração

Defina antes da execução:

```powershell
$env:SAM2_CHECKPOINT_PATH = "caminho\externo\sam2.1_hiera_small.pt"
$env:SAM2_MODEL_CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"
$env:SAM2_DEVICE = "cuda"
$env:SAM2_DTYPE = "float32"
```

Configurações opcionais:

```powershell
$env:MAX_UPLOAD_BYTES = "10485760"
$env:MAX_IMAGE_WIDTH = "4096"
$env:MAX_IMAGE_HEIGHT = "4096"
$env:MAX_IMAGE_PIXELS = "16000000"
$env:API_PREFIX = "/api/v1"
```

O caminho do checkpoint é obrigatório no startup real. Não há fallback para
CPU ou para outro modelo.

## Execução

Execute a partir da raiz do repositório:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app `
  --host 127.0.0.1 `
  --port 8000 `
  --workers 1
```

Nesta fase são obrigatórios um único worker e uma inferência por vez. O modelo
é carregado uma vez no lifespan e fechado no shutdown.

Rotas:

- `GET /health`;
- `POST /api/v1/segmentations`;
- `GET /api/v1/pci/regions`;
- `POST /api/v1/pci/calculate`.

JPEG e PNG estáticos são processados somente em memória. A aplicação não
persiste imagens, máscaras, prompts ou resultados. O uso é experimental e não
se destina a diagnóstico autônomo.
