# Fundação de persistência experimental

Esta camada é independente do `SAM2Segmenter` e é usada pela rota de tentativas.
A rota stateless permanece independente do banco. Nenhuma
inferência ou gravação é disparada por importar os módulos. O contrato
[SAM 2.1](sam2_inference_contract.md) permanece válido para a API atual.

## Modelo de persistência

| Entidade | Conteúdo e relações |
| --- | --- |
| ClinicalCase | UUID, campo legado `anonymous_patient_code` e criação; suporta várias imagens. No Experimento B, o campo representa um código pseudonimizado do caso experimental, sem estabelecer identidade de paciente. Não exige unicidade. |
| Image | UUID, FK do caso, caminho relativo, largura/altura positivas, SHA-256 hexadecimal dos bytes originais e criação. Hash indexado, sem deduplicação automática entre casos. |
| Evaluation | UUID, FK da imagem, região PCI 0–12 ou NULL quando não determinada, código do anotador, LS clínico manual 0–3 ou NULL (não determinado em finalized), annotator_confidence opcional 0–1 (somente com LS), reviewed_attempt_id UUID e segmentation_quality string opcionais em draft, status e timestamps. Permite avaliações independentes da mesma imagem. |
| SegmentationAttempt | UUID, FK da avaliação, sequência positiva única nessa avaliação, prompt box/points, JSONB do prompt, caminho da máscara, JSONB dos metadados SAM e criação. |

IDs são gerados pela aplicação; timestamps de criação são gerados no banco
com fuso. FKs restringem exclusão de pais com dependentes. Não há blobs.
`annotator_confidence` é a confiança declarada pelo anotador, nunca `selected_score` do
SAM. Prompts e metadados devem ser objetos JSON serializáveis; o chamador
fornece prompt validado e `result.to_metadata_dict()`, incluindo a configuração
de `multimask_output` no prompt para reprodutibilidade. Não incluir arrays de
máscara ou logits no JSON.

O repositório cria avaliações em `draft`. Finalizar grava `finalized_at` e o
LS explicitamente informado, inteiro entre 0 e 3 ou NULL quando não determinado, além de
`reviewed_attempt_id` e `segmentation_quality`. Sob o mesmo bloqueio da avaliação,
o repositório verifica que a tentativa existe e pertence à avaliação. Os dois campos
são gravados na mesma transação curta, sem relação ORM circular ou nova tabela.
A pertença é garantida pelo repositório; o UUID não introduz uma FK circular.
Em `draft`, o LS pode ser `None`; em `finalized`, `None` significa não determinado.
O banco e a API rejeitam confiança preenchida sem LS.
Tentativas adicionais e nova finalização são recusadas pelo repositório.
Ele usa bloqueio da linha da avaliação até commit/rollback, em conjunto com
unicidade no banco, para serializar numeração e finalização. Essas regras
de imutabilidade são do repositório, não triggers contra SQL direto.
JSONB deve ser substituído integralmente em atualizações, não alterado in-place.

`finalized` registra o encerramento da avaliação; não indica automaticamente
uma máscara validada. A tentativa revisada fica vinculada ao julgamento humano
`adequate` / `partially_adequate` / `inadequate`, sem aceite ou transformação em
referência/ground truth. Região PCI e LS são fornecidos pelo especialista quando
determináveis; nenhum deles é inferido pelo SAM. O fluxo
não calcula PCI completo. Features e exportação de dataset não estão implementadas.

## Uso da fundação

Após `python -m alembic upgrade head`, um script pode persistir bytes e
metadados já validados. Exemplo com imagem sintética (nenhuma imagem clínica):

```python
from io import BytesIO
from PIL import Image as PILImage
from backend.app.persistence.database import (
    PersistenceSettings, create_database_engine, create_session_factory,
)
from backend.app.persistence.repository import ExperimentRepository
from backend.app.storage.local import LocalStorage

settings = PersistenceSettings.from_env()
engine = create_database_engine(settings)
sessions = create_session_factory(engine)
storage = LocalStorage(settings.storage_root)
buffer = BytesIO()
PILImage.new("RGB", (32, 24)).save(buffer, format="PNG")
stored = storage.save(buffer.getvalue(), category="images", suffix=".png")
try:
    with sessions.begin() as session:
        repo = ExperimentRepository(session)
        case = repo.create_case("synthetic-case")
        image = repo.add_image(
            case_id=case.id,
            storage_path=stored.path, width=32, height=24, sha256=stored.sha256,
        )
        evaluation = repo.create_evaluation(
            image_id=image.id, pci_region_id=0, annotator_code="expert-001",
        )
except Exception:
    storage.delete(stored.path)
    raise
finally:
    engine.dispose()
```

`add_attempt()` recebe o UUID da avaliação, tipo e dados do prompt, caminho
da máscara PNG previamente salva e metadados SAM. `list_attempts()` retorna
as tentativas na ordem; `get_evaluation()` recupera a avaliação e suas relações.
`finalize_evaluation()` registra o LS manual ou NULL e exige a revisão
qualitativa vinculada à tentativa. O repositório
faz flush, mas somente o chamador decide a transação completa.

Storage gera nomes UUID independentes do nome original e verifica caminhos
resolvidos dentro da raiz, recusando traversal, caminhos absolutos e extensões
inesperadas. Ele não valida nem transforma pixels; isso cabe ao chamador.
A raiz deve ser controlada pela aplicação, sem alterações concorrentes de
symlinks por outros usuários. Nomes originais não são persistidos, pois podem
conter informação identificável. Usar somente arquivos e códigos adequadamente
anonimizados no experimento.

Banco e filesystem não têm transação conjunta. Salvar antes do commit evita
publicar um registro antes de completar a gravação; em falhas conhecidas o
chamador deve remover arquivos recém-criados. Interrupção do processo pode
deixar órfãos; falha de conexão durante commit pode deixar resultado incerto,
que exige verificar o registro antes de remover arquivos. Não há coletor
automático de órfãos nesta etapa. Backups devem incluir banco e storage.

## Migrations e validação

`0001_experiment` cria as quatro tabelas, FKs, índices e checks e permanece inalterada.
`0002_segmentation_review` adiciona os dois campos nullable à Evaluation. Checks
restringem qualidade às três categorias e exigem ambos os campos nulos ou ambos
preenchidos. Avaliações antigas finalizadas sem revisão continuam válidas; somente
novas finalizações pela API exigem a revisão. O downgrade para `0001_experiment`
remove apenas os campos de revisão e seus checks, perdendo esses dados de revisão.
`0003_optional_clinical_context` torna a região nullable, remove o check de LS
obrigatório em finalized e adiciona o check de confiança somente com LS. Não faz
backfill nem cria sentinelas. Seu downgrade restaura o contrato anterior: registros
com região NULL ou finalizados com LS NULL precisam ser removidos explicitamente
antes da reversão; a migration não exclui dados nem inventa valores.
`python -m alembic downgrade base` remove essas tabelas e seus registros;
use apenas para reversão deliberada em banco descartável. Arquivos permanecem
no storage. Migrations não importam o modelo SAM nem exigem checkpoint/CUDA.

Os testes locais cobrem configuração, SQL offline e storage. Os testes com
PostgreSQL cobrem persistência real, JSONB, integridade, rollback, concorrência,
correspondência entre migration e modelos e ciclo upgrade/downgrade.

Referências técnicas: [transações SQLAlchemy 2.x](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
e [configuração Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## Integração HTTP de tentativas

`POST /api/v1/evaluations/{evaluation_id}/segmentations` busca uma avaliação
existente, exige `draft` e obtém região PCI e storage_path da imagem relacionada.
A transação de leitura termina antes da inferência. Os bytes do LocalStorage
passam pelo mesmo decoder JPEG/PNG dos uploads, produzindo RGB uint8 sem
redimensionamento ou transformação de orientação.

O parser de prompts é compartilhado com a API stateless. A tentativa guarda
`box_xyxy` ou `points_xy` + `labels`, sempre com `multimask_output`. Os metadados
são os produzidos pelo SAM, sem incorporar imagem, máscara ou logits no JSONB.
O PNG é salvo em `masks/`, e `add_attempt()` revalida draft com seu bloqueio
existente e atribui a próxima sequência. O commit ocorre antes da resposta 201.
Em falha da transação, a API tenta excluir somente o PNG recém-criado. Falha
nessa exclusão retorna erro genérico e pode deixar um órfão. Interrupção do
processo e confirmação de commit perdida continuam limitações: nessa última
situação, o cleanup pode remover um arquivo cujo registro foi confirmado;
é necessária reconciliação manual. Não há retries ou coordenação distribuída.

A resposta traz IDs, sequência, região (NULL quando não determinada), metadados e PNG Base64, sem caminhos
locais. A avaliação permanece draft e seus campos clínicos não são alterados.
Testes HTTP usam SAM fake; os testes PostgreSQL compartilham o fixture de
schema isolado em `tests/app/conftest.py` e são executados pelo workflow atual.
