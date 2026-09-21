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

## Desenvolvimento no Windows

Com o ambiente Python e SAM/CUDA configurados como acima e o Docker Desktop
em execução, prepare `.env` com `Copy-Item .env.example .env` e ajuste os valores.
Defina `SAM2_CHECKPOINT_PATH` no `.env` com o caminho do checkpoint local,
mantido fora do repositório; o caminho fornecido é apenas um exemplo.
Para o desenvolvimento normal, execute na raiz do repositório:

```powershell
.\scripts\dev.ps1
```

O script carrega `.env` no processo atual, usa `.venv\Scripts\python.exe`
quando disponível (senão, `python` do PATH), inicia somente PostgreSQL com
`docker compose up -d --wait postgres` e aplica as migrations existentes com
`python -m alembic upgrade head`. Ele não cria migrations novas. O carregamento
aceita `NOME=valor`, aspas externas simples ou duplas, linhas vazias e comentários
iniciados por `#`; não expande variáveis nem interpreta comentários ao fim da linha.

O Uvicorn roda no foreground, com logs visíveis; Ctrl+C encerra o backend.
O PostgreSQL continua disponível e pode ser encerrado posteriormente com:

```powershell
docker compose stop postgres
```

Docker Desktop continua podendo ser usado para visualizar o container e seus
logs, e PostgreSQL pode ser inspecionado normalmente pelo VS Code. A inicialização
manual descrita neste documento continua possível.

## Persistência experimental

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

### Segmentação de uma avaliação existente

`POST /api/v1/evaluations/{evaluation_id}/segmentations` recebe formulário
com `prompt_type`, `box` ou `points` + `labels` (arrays JSON em strings) e
`multimask_output` opcional, padrão `true`. Não aceita imagem, região ou LS;
campos extras são rejeitados. Exemplo:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/evaluations/UUID/segmentations" `
  -F 'prompt_type=box' -F 'box=[2,2,25,20]' -F 'multimask_output=false'
```

Prepare ClinicalCase, Image e Evaluation por Python, conforme o documento de
persistência. A região e a imagem vêm da Evaluation. A resposta `201` contém
`attempt_id`, `evaluation_id`, `sequence_number`, `region`, `metadata` e
`mask` (PNG Base64, largura e altura). Não há LS ou cálculo de PCI nessa rota.
Evaluation inexistente retorna `404`; finalized retorna `409`; prompt inválido
retorna `422`. Falhas internas retornam mensagem genérica, sem caminhos ou credenciais.

Com `DATABASE_URL`, o lifespan configura engine/session factory e LocalStorage;
a conexão é aberta ao usar o banco. O shutdown descarta a engine criada pela API.
Sem essa variável, a nova rota retorna `503`, e a API stateless continua disponível.
Não há criação de tabelas nem migrations automáticas. Para testes, `create_app`
aceita `session_factory` e `storage` juntos, além do serviço SAM fake.

A máscara é salva antes da transação de escrita. Falhas no registro ou commit
removem o novo PNG; arquivos anteriores permanecem intactos. Consulte as
limitações de interrupção e commit incerto no documento de persistência.
