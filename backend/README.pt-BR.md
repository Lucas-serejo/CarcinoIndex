**Idioma:** [English](README.md) · Português
<!-- synced with README.md @ 55b1b37 -->

# Backend do CarcinoIndex

API experimental para segmentação com o SAM 2.1 Hiera Small guiada pelo
especialista e para composição manual do PCI. O SAM produz uma máscara a partir
de prompts de caixa ou de pontos; ele não classifica lesões. O LS clínico é
sempre fornecido pelo especialista. Ele pode ser nulo em Evaluations, inclusive
nas finalizadas, quando não determinado. A região PCI também pode ser nula quando
não determinada; nenhum dos dois campos é inferido pelo SAM. Novas finalizações
exigem `reviewed_attempt_id` e `segmentation_quality` (`adequate`,
`partially_adequate` ou `inadequate`), além de `clinical_ls` explícito (0–3 ou
null) e confiança opcional no LS (null se o LS for null). O repositório verifica
a quem pertence a tentativa; tentativas inexistentes ou de outra Evaluation
retornam erros HTTP 422 seguros. As respostas de Evaluation incluem os dois
campos de revisão. Aplique `python -m alembic upgrade head` para
`0003_optional_clinical_context`; registros finalizados legados mantêm os campos
de revisão nulos. O especialista fornece a região PCI, o LS e a revisão
qualitativa da saída do SAM. Isso não aceita nem valida uma máscara como ground
truth e não calcula o PCI completo.

## Configuração

Defina antes da execução:

```powershell
$env:SAM2_CHECKPOINT_PATH = "path\to\external\sam2.1_hiera_small.pt"
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

Persistência (necessária para as rotas persistidas):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/carcinoindex"
$env:STORAGE_ROOT = "storage"
```

`DATABASE_URL` precisa usar o driver `postgresql+psycopg`. `STORAGE_ROOT` é
opcional (padrão `storage`, resolvido a partir do diretório de execução). Sem
`DATABASE_URL`, a API sobe normalmente, mas as rotas persistidas respondem
`503` com o código `persistence_unavailable`; as rotas stateless continuam
disponíveis.

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

Rotas stateless (não exigem banco):

- `GET /health`;
- `POST /api/v1/segmentations`;
- `GET /api/v1/pci/regions`;
- `POST /api/v1/pci/calculate`.

Nessas rotas, JPEG e PNG estáticos são processados somente em memória. A
aplicação não persiste imagens, máscaras, prompts ou resultados nesses endpoints.

Rotas persistidas (exigem `DATABASE_URL`; veja o
[guia do ciclo de vida](../docs/experiment_lifecycle_api.pt-BR.md)):

- `POST /api/v1/cases`;
- `POST /api/v1/cases/{case_id}/images`;
- `GET /api/v1/images/{image_id}/content`;
- `POST /api/v1/images/{image_id}/evaluations`;
- `GET /api/v1/evaluations/{evaluation_id}`;
- `POST /api/v1/evaluations/{evaluation_id}/segmentations`;
- `POST /api/v1/evaluations/{evaluation_id}/finalize`.

O uso é experimental e não se destina a diagnóstico autônomo.

## Documentação da API

- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- Especificação OpenAPI: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

## Desenvolvimento no Windows

Com o ambiente Python e SAM/CUDA configurados como acima e o Docker Desktop
em execução, prepare `.env` com `Copy-Item .env.example .env` e ajuste os valores.
Defina `SAM2_CHECKPOINT_PATH` no `.env` com o caminho do checkpoint local,
mantido fora do repositório; o caminho fornecido é apenas um exemplo.
Para o desenvolvimento normal, execute na raiz do repositório:

```powershell
.\scripts\dev.ps1
```

O script recusa execução fora da raiz do repositório e exige o `.env`. Ele
carrega o `.env` no processo atual e, antes de iniciar o Docker, verifica que
`SAM2_CHECKPOINT_PATH` está definido e aponta para um arquivo existente. Depois,
usa `.venv\Scripts\python.exe` quando disponível (senão, `python` do PATH),
inicia somente PostgreSQL com `docker compose up -d --wait postgres` e aplica as
migrations existentes com `python -m alembic upgrade head`. Ele não cria
migrations novas. O carregamento aceita `NAME=value`, aspas externas simples ou
duplas, linhas vazias e comentários iniciados por `#`; não expande variáveis nem
interpreta comentários ao fim da linha.

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
continuam no ambiente Python local com CUDA. As dependências de persistência
(SQLAlchemy, Alembic e psycopg) já fazem parte de `backend/requirements.txt`;
instale-o conforme os [pré-requisitos do README principal](../README.pt-BR.md#pré-requisitos).

```powershell
Copy-Item .env.example .env
# Adjust the password in .env before starting.
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://carcinoindex:local-experiment-only@127.0.0.1:5432/carcinoindex"
$env:STORAGE_ROOT = Join-Path (Get-Location) "storage"
python -m alembic upgrade head
```

Use na URL a mesma senha configurada no `.env` (com escape URL quando
necessário). Compose lê `.env`; backend e Alembic leem somente variáveis
exportadas, sem carregar `.env` automaticamente (o `dev.ps1` as carrega do
`.env`). Os scripts locais `export_experiment_b.py` e `reset_experiment_data.py`
carregam o `.env` da raiz por conta própria; veja [Configuração dos scripts
locais](#configuração-dos-scripts-locais). O banco não é criado nem migrado pelo
startup da API. `STORAGE_ROOT` relativo é resolvido a partir do diretório de
execução; prefira caminho absoluto. A pasta padrão `storage/` é ignorada pelo
Git; qualquer pasta alternativa dentro do repositório também deve ser ignorada.

O Compose inicia somente PostgreSQL por padrão. O serviço antigo de backend
está no perfil `legacy-backend`; é legado e não foi validado com o código
atual. O caminho recomendado para SAM/CUDA segue sendo a execução local com um
worker descrita acima.

O modelo, decisões e exemplo de transação estão em
[persistência experimental](../docs/architecture/experiment_persistence.pt-BR.md).

```powershell
python -m pytest -q -ra
# Separate, pre-created test database; the user must be able to create schemas.
$env:TEST_DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/carcinoindex_test"
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

Crie ClinicalCase, Image e a Evaluation em rascunho pelos endpoints HTTP descritos
no [guia do ciclo de vida no Swagger](../docs/experiment_lifecycle_api.pt-BR.md).
A Evaluation fornece a imagem e a região PCI.

Os fluxos persistidos também oferecem `GET /api/v1/evaluations/{evaluation_id}`
para o estado da avaliação em rascunho ou finalizada e
`GET /api/v1/images/{image_id}/content` para os bytes originais validados da
imagem. O conteúdo da imagem usa o media type JPEG/PNG correto, com
`Cache-Control: no-store` e `X-Content-Type-Options: nosniff`. Os metadados da
resposta não expõem nomes de arquivo nem caminhos de armazenamento. Registros
inexistentes retornam `404`; conteúdo indisponível de uma imagem existente
retorna um `500 image_content_unavailable` seguro. Veja o guia do ciclo de vida
para os envelopes de erro.

A resposta `201` contém
`attempt_id`, `evaluation_id`, `sequence_number`, `region`, `metadata` e
`mask` (PNG Base64, largura e altura). Não há LS ou cálculo de PCI nessa rota.
Evaluation inexistente retorna `404`; finalized retorna `409`; prompt inválido
retorna `422`. Falhas internas retornam mensagem genérica, sem caminhos ou credenciais.

Com `DATABASE_URL`, o lifespan configura engine/session factory e LocalStorage;
a conexão é aberta ao usar o banco. O shutdown descarta a engine criada pela API.
Sem essa variável, a rota retorna `503`, e a API stateless continua disponível.
Não há criação de tabelas nem migrations automáticas. Para testes, `create_app`
aceita `session_factory` e `storage` juntos, além do serviço SAM fake.

A máscara é salva antes da transação de escrita. Falhas no registro ou commit
removem o novo PNG; arquivos anteriores permanecem intactos. Consulte as
limitações de interrupção e commit incerto no documento de persistência.

### Configuração dos scripts locais

`scripts/export_experiment_b.py` e `scripts/reset_experiment_data.py` tentam
carregar o `.env` da raiz do repositório antes de ler a configuração. Variáveis
já definidas no processo têm prioridade sobre o `.env`; sem `.env`, os scripts
usam apenas o ambiente atual (útil em CI). Para usar outro banco numa execução,
basta exportar a variável no terminal:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/other_database"
python scripts/reset_experiment_data.py
```

O formato aceito é o do `.env.example`: `NAME=value`, linhas vazias, comentários
iniciados por `#` e aspas externas opcionais, sem expansão de variáveis nem
comentários ao fim da linha. Uma linha inválida interrompe o script sem exibir
seu conteúdo. Valores do `.env` nunca são impressos. O `.env` continua ignorado
pelo Git; não versione credenciais. Backend e Alembic não carregam o `.env`
sozinhos.

### Exportação do Experimento B (CSV)

Exporta as avaliações finalizadas, destinadas ao Experimento B planejado, para
análise posterior, sem SQL manual. Cada linha do CSV é **uma Evaluation
finalizada**; drafts são excluídos. Os metadados de prompt e SAM pertencem
exclusivamente à tentativa indicada por `reviewed_attempt_id` (não à primeira, à
última ou à de maior score); `attempt_count` informa quantas tentativas a
Evaluation possui e `reviewed_attempt_sequence`, a sequência da tentativa
revisada. A ordem é `finalized_at` e, em empate, `evaluation_id`.

Execute na raiz do repositório. A configuração vem do `.env` local ou de
variáveis já exportadas, como descrito em [Configuração dos scripts
locais](#configuração-dos-scripts-locais) (SAM, CUDA e checkpoint não são
necessários):

```powershell
python scripts/export_experiment_b.py
# Optional: python scripts/export_experiment_b.py --output path\to\evaluations.csv
```

O padrão é `experiments/outputs/experiment_b/evaluations.csv` (diretórios são
criados automaticamente). Essa pasta é ignorada pelo Git: **não versione o CSV**.
Sem avaliações finalizadas, é gerado apenas o cabeçalho e o comando informa
0 avaliações exportadas. O terminal mostra uma contagem de conferência
operacional (qualidade, região PCI e LS determinados/não determinados), não
uma análise estatística.

O processo é somente leitura: usa uma transação PostgreSQL `READ ONLY`, não
abre imagens nem máscaras, não executa o SAM e não altera registros. Se uma
Evaluation finalizada não tiver `reviewed_attempt_id`, referenciar tentativa
inexistente ou de outra Evaluation, ou não tiver `segmentation_quality`, a
exportação é abortada com o `evaluation_id` problemático; nada é corrigido
automaticamente nem omitido em silêncio (Evaluations legadas finalizadas antes
de `0002_segmentation_review` se enquadram aqui).

Colunas: `evaluation_id`, `case_id`, `case_code`, `image_id`, `image_sha256`,
`image_width`, `image_height`, `annotator_code`, `pci_region_id`,
`segmentation_quality`, `clinical_ls`, `annotator_confidence`,
`reviewed_attempt_id`, `reviewed_attempt_sequence`, `attempt_count`,
`prompt_type`, `prompt_data_json`, `model_name`, `model_config`,
`checkpoint_name`, `selected_index`, `selected_score`, `mask_area_pixels`,
`mask_area_ratio`, `prediction_time_seconds`, `evaluation_created_at`,
`finalized_at`. Valores nulos (por exemplo, região ou LS não determináveis)
ficam como células vazias; datas são ISO 8601 em UTC.

Interpretação:

- `case_code` vem de `ClinicalCase.anonymous_patient_code` e é o código
  pseudonimizado do caso experimental; não representa necessariamente um
  paciente nem estabelece identidade entre casos.
- `selected_score` é o score técnico da máscara escolhida pelo SAM, não
  confiança clínica. A confiança da especialista é `annotator_confidence`,
  associada apenas ao LS.
- `mask_area_ratio` é a proporção de pixels da máscara em relação à imagem,
  não o tamanho físico da lesão.
- `prompt_data_json` é o `prompt_data` persistido (caixa delimitadora manual),
  serializado com chaves ordenadas.

O CSV não contém caminhos de armazenamento de imagens ou máscaras, nomes de
arquivo, bytes de imagem, máscaras, logits nem credenciais.

### Reset dos dados experimentais locais

Limpa **todos** os dados experimentais de desenvolvimento antes de uma nova
rodada de testes ou do início do Experimento B. Destina-se somente ao ambiente
local/de desenvolvimento. Execute na raiz do repositório; `DATABASE_URL` e
`STORAGE_ROOT` vêm do `.env` local ou do ambiente, como descrito em
[Configuração dos scripts locais](#configuração-dos-scripts-locais) (SAM e CUDA
não são necessários).

Sem argumentos, o comando é um **dry-run**: mostra as contagens do banco e dos
arquivos gerenciados e não altera nada.

```powershell
python scripts/reset_experiment_data.py
```

Para executar de fato, **pare o backend** (Ctrl+C no `dev.ps1`) e confirme com o
nome exato do banco da `DATABASE_URL`, mostrado no dry-run:

```powershell
python scripts/reset_experiment_data.py --execute --confirm carcinoindex
```

O comando aborta, sem alterar nada, se `--confirm` não coincidir ou se houver
qualquer resposta em `http://127.0.0.1:8000/health`. Só uma conexão recusada
(nenhum processo ouvindo) libera a execução; não há opção para ignorar essa
proteção.

O que é apagado:

- linhas de `segmentation_attempts`, `evaluations`, `images` e `clinical_cases`,
  com um único `TRUNCATE` (sem `CASCADE`) numa transação;
- somente depois de o banco ser confirmado vazio, os arquivos em
  `STORAGE_ROOT/images/` e `STORAGE_ROOT/masks/` cujo nome segue o contrato do
  `LocalStorage` (`<32 hex>.png|jpg|jpeg`).

O que é preservado: schema, `alembic_version` e migrations; qualquer outro
arquivo do storage (nomes fora do contrato, subpastas, arquivos fora de
`images/` e `masks/`); symlinks, que nunca são seguidos; `experiments/outputs`
e os dados do Experimento A. Se o `TRUNCATE` falhar, há rollback e o storage
não é tocado. Se algum arquivo gerenciado não puder ser apagado (por exemplo,
bloqueado pelo OneDrive), o comando retorna erro informando que restaram
arquivos órfãos; corrija a causa e execute de novo. Com tudo vazio, o comando
termina com sucesso e mantém os zeros.

**Não há backup automático.** Se algum dado precisar ser preservado, faça o
backup antes, por exemplo com `python scripts/export_experiment_b.py`, um
`pg_dump` do banco e uma cópia de `STORAGE_ROOT/images` e `STORAGE_ROOT/masks`
para fora do repositório.
