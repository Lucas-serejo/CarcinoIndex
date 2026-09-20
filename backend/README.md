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
persiste imagens, máscaras, prompts ou resultados nesses endpoints. O uso é experimental e não
se destina a diagnóstico autônomo.

## Persistência experimental (uso explícito por Python)

Execute na raiz do repositório. PostgreSQL roda no Docker; backend e SAM
continuam no ambiente Python local com CUDA. Para acrescentar somente as
dependências desta etapa ao ambiente existente:

```powershell
python -m pip install "SQLAlchemy>=2.0,<2.1" "alembic>=1.13,<2" "psycopg[binary]>=3.1,<4"
Copy-Item .env.example .env
# Ajuste a senha no .env antes de iniciar.
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://carcinoindex:local-experiment-only@127.0.0.1:5432/carcinoindex"
$env:STORAGE_ROOT = Join-Path (Get-Location) "storage"
python -m alembic upgrade head
```

Use na URL a mesma senha configurada no `.env` (com escape URL quando
necessário). Compose lê `.env`; Python/Alembic leem variáveis exportadas,
sem carregar `.env` automaticamente. O banco não é criado nem migrado pelo
startup da API. `STORAGE_ROOT` relativo é resolvido a partir do diretório de
execução; prefira caminho absoluto. A pasta padrão `storage/` é ignorada pelo
Git; qualquer pasta alternativa dentro do repositório também deve ser ignorada.

O Compose inicia somente PostgreSQL por padrão. O serviço antigo de backend
está no perfil `legacy-backend`; o caminho recomendado para SAM/CUDA segue
sendo a execução local com um worker descrita acima.

O modelo, decisões e exemplo de transação estão em
[persistência experimental](../docs/architecture/experiment_persistence.md).

```powershell
python -m pytest -q -ra
# Banco de teste separado, previamente criado; o usuário precisa criar schemas.
$env:TEST_DATABASE_URL = "postgresql+psycopg://usuario:senha@127.0.0.1:5432/carcinoindex_test"
python -m pytest tests/app/persistence -q -ra
```

Sem `TEST_DATABASE_URL`, os testes PostgreSQL são marcados como skipped.
Com ela configurada, falhas de conexão são erros. Cada teste cria e remove
somente um schema aleatório próprio. Não há substituição por SQLite.
O backend usa `SAM2_CHECKPOINT_PATH` e CUDA. Os testes reais existentes leem
`SAM2_CHECKPOINT`; para executá-los com o mesmo checkpoint:

```powershell
$env:SAM2_CHECKPOINT = $env:SAM2_CHECKPOINT_PATH
python -m pytest -m "sam2_integration or sam2_api_integration" -q
```
