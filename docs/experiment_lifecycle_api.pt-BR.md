**Idioma:** [English](experiment_lifecycle_api.md) · Português
<!-- synced with experiment_lifecycle_api.md @ 55b1b37 -->

# Ciclo de vida do experimento no Swagger

Inicie a API configurada com PostgreSQL, migrations Alembic até
`0003_optional_clinical_context`, armazenamento local e SAM disponível, como
descrito no README do backend. Abra `/docs`. Todos os caminhos abaixo usam o
prefixo padrão `/api/v1`.

1. `POST /cases` com `{"anonymous_patient_code": "CASE-001"}`.
   Copie `case_id` da resposta `201`. Os códigos são identificadores
   pseudonimizados, sem espaços nas pontas, não vazios e limitados a 128
   caracteres. Duplicatas são permitidas. Não informe nomes, números de
   prontuário, CPF, e-mail ou outros dados pessoais. O nome legado do campo,
   `anonymous_patient_code`, permanece inalterado. Para o Experimento B
   planejado, ele é um identificador pseudonimizado de caso experimental e não
   estabelece identidade de paciente nem relação entre imagens. Cada fotografia
   pode ser um novo caso.
2. `POST /cases/{case_id}/images`: selecione um JPEG ou PNG no campo multipart
   `image`. Copie `image_id` da resposta `201`. A resposta inclui `case_id`,
   largura, altura, SHA-256 e data de criação, sem nomes de arquivo nem caminhos
   de armazenamento.
3. `POST /images/{image_id}/evaluations` com
   `{"pci_region_id": 6, "annotator_code": "MED01"}`. Copie `evaluation_id` da
   resposta `201`. Os IDs de região vão de 0 a 12; envie `pci_region_id: null`
   quando o especialista não puder determinar a região. O código do especialista
   é pseudonimizado, não vazio e limitado a 128 caracteres. A avaliação começa
   como `draft`, com LS, confiança, ID da tentativa revisada, qualidade da
   segmentação e data de finalização nulos.
   LS, confiança e outros campos JSON não suportados são rejeitados com `422`.
4. `POST /evaluations/{evaluation_id}/segmentations`: informe `prompt_type=box`
   e um array JSON em `box`, por exemplo `[2,2,25,20]` para uma imagem que
   contenha essas coordenadas. Alternativamente, use pontos e rótulos. Repita
   quantas vezes for necessário. Vendo a máscara, o especialista escolhe
   `adequate`, `partially_adequate` ou `inadequate`. Guarde o `attempt_id`
   desse resultado específico revisado.
5. `POST /evaluations/{evaluation_id}/finalize` com
   `{"clinical_ls": 2, "annotator_confidence": 0.9, "reviewed_attempt_id": "<attempt UUID>", "segmentation_quality": "adequate"}`.
   A chave `clinical_ls` é obrigatória: um inteiro de 0 a 3, ou null quando não
   determinado. A confiança deve ser null ou omitida quando o LS for null. Caso
   contrário, ela é opcional e é um número de 0 a 1 que representa a confiança
   do especialista no LS clínico. Os dois campos de revisão são obrigatórios e
   não nulos em toda nova finalização pela API. A qualidade aceita apenas os três
   valores exatos acima; campos extras continuam proibidos. A resposta `200`
   contém a avaliação finalizada e seu timestamp.
6. Novas tentativas de segmentação ou uma segunda finalização retornam `409`.
   O frontend oferece "Nova avaliação" após a finalização. Ela reinicia apenas o
   estado local do fluxo e mantém o código do anotador, o idioma e as regiões
   carregadas; nenhuma requisição HTTP ocorre até o próximo envio. Esse envio
   recomeça em `POST /cases`, com um novo upload de imagem e uma nova
   Evaluation. Os registros anteriores permanecem inalterados.

Todas as respostas de avaliação incluem `evaluation_id`, `image_id`,
`pci_region_id`, `annotator_code`, `status`, `clinical_ls`,
`annotator_confidence`, `reviewed_attempt_id`, `segmentation_quality`,
`created_at` e `finalized_at`. Registros pais inexistentes retornam `404`; campos
inválidos retornam `422`. Uma tentativa inexistente ou pertencente a outra
Evaluation retorna `422` com `{"error":{"code":"invalid_segmentation_review","message":"Reviewed attempt must belong to this evaluation."}}`.
A requisição que falha deixa o rascunho inalterado. Registros finalizados
existentes sem campos de revisão continuam legíveis, com os dois campos nulos.

### Respostas de erro

Todo erro usa o mesmo envelope JSON, `{"error":{"code":"<code>","message":"<message>"}}`,
sem stack traces, chaves de armazenamento ou caminhos do sistema de arquivos:

- `422 request_validation_error` ("The request fields are invalid or incomplete.")
  para qualquer requisição que falhe na validação do schema, incluindo campos
  JSON desconhecidos, valores fora do intervalo e confiança informada sem LS.
  Códigos `422` específicos de endpoint, como `invalid_prompt`,
  `invalid_segmentation_review` ou os códigos de validação de imagem, estão
  descritos nas etapas acima e abaixo.
- `503 persistence_unavailable` quando a API foi iniciada sem `DATABASE_URL`
  (nenhuma session factory ou armazenamento configurado). O endpoint de
  tentativas de segmentação também pode retornar `503 model_unavailable` ou
  `503 cuda_out_of_memory`.
- `500` com um código genérico específico do endpoint (`case_creation_failed`,
  `image_creation_failed`, `evaluation_creation_failed`, `finalization_failed`,
  `segmentation_failed` ou `image_content_unavailable`) para falhas inesperadas.

A finalização significa que o especialista concluiu a avaliação, decidiu
explicitamente se o LS é determinável e forneceu um julgamento qualitativo
vinculado a uma tentativa de segmentação específica. Esse julgamento não é
validação clínica, LS, confiança do SAM nem ground truth. Nenhuma máscara é
aceita, validada ou transformada em máscara de referência. O especialista fornece
a região PCI e o LS quando determináveis; nenhum deles é inferido pelo SAM. O
fluxo não calcula o PCI completo nem faz diagnóstico autônomo. O `selected_score`
do SAM mantém apenas seu significado interno de qualidade/ranqueamento: é um
metadado técnico do SAM retornado com cada tentativa de segmentação (e persistido
em seus metadados), não confiança clínica. A confiança do especialista é
`annotator_confidence`.

A interface começa sem resposta de região/LS e exige uma escolha numérica ou a
opção explícita "Não foi possível determinar". Somente esta última vira null na
requisição. O endpoint de segmentação persistida aceita região nula e retorna
`region: null`; o endpoint stateless continua exigindo `region_id`. A inferência
do SAM não muda.

## Recuperar recursos persistidos

`GET /evaluations/{evaluation_id}` retorna `200` com os campos de avaliação
listados acima, para uma avaliação em rascunho ou finalizada. Respostas
finalizadas incluem o LS clínico persistido, a confiança opcional, o ID da
tentativa revisada, a qualidade da segmentação e o timestamp de finalização.
Nenhum recurso aninhado ou tentativa de segmentação é incluído. Uma avaliação
inexistente retorna `404` com
`{"error":{"code":"evaluation_not_found","message":"Evaluation not found."}}`.

`GET /images/{image_id}/content` retorna `200` com os bytes JPEG ou PNG
originais validados, exatos, do fluxo experimental persistido. Não há
redimensionamento, recompressão, transcodificação nem conversão para base64. O
Content-Type é `image/png` para chaves de armazenamento `.png` e `image/jpeg`
para chaves `.jpg` ou `.jpeg`. São chaves internas, geradas pela aplicação; nomes
de arquivo, chaves de armazenamento e caminhos do sistema de arquivos não são
expostos nos metadados da resposta. Nenhum nome de arquivo em Content-Disposition
é definido. Respostas de imagem bem-sucedidas trazem `Cache-Control: no-store` e
`X-Content-Type-Options: nosniff`, restritos a este endpoint.

Um registro de imagem inexistente no banco retorna `404` com
`{"error":{"code":"image_not_found","message":"Image not found."}}`.
Se o registro existir, mas seu conteúdo estiver ausente, inacessível ou com uma
chave interna de armazenamento inválida, a resposta é `500` com
`{"error":{"code":"image_content_unavailable","message":"Stored image content is unavailable."}}`.
Erros de armazenamento não expõem chaves, caminhos nem detalhes de exceção. A
sessão do banco é fechada antes de `LocalStorage.read()` ler os bytes.

Aplique `python -m alembic upgrade head` antes de usar o contrato estendido da
Evaluation. As operações de recuperação permitem recuperar o estado persistido
sem manter o File original do navegador. A recuperação de tentativas de
segmentação e a retomada no frontend continuam fora desta iteração. Os bytes da
imagem são lidos para a memória; streaming, range requests, novas tentativas e
reparo do armazenamento não estão implementados.

## Armazenamento de imagens e transações

Os uploads reutilizam a validação do endpoint stateless de content type, quadro
estático, tamanho em bytes, dimensões, orientação e decodificação RGB. Uploads
inválidos retornam `413`, `415` ou `422` e não criam registro nem arquivo de
imagem. Os bytes originais são armazenados sem redimensionamento ou recompressão,
com chaves UUID e sufixos `.jpg` ou `.png`. O SHA-256 é calculado sobre esses
bytes exatos. Os nomes originais dos arquivos são descartados.

JPEG e PNG podem carregar metadados EXIF de orientação. O decodificador
compartilhado aceita orientação ausente ou Orientation normal `1` e rejeita
Orientation `2` a `8`, valores/tipos não suportados e metadados malformados que
não podem ser interpretados com segurança:

```json
{"error":{"code":"unsupported_image_orientation","message":"Image orientation metadata is unsupported or invalid. Normalize image orientation before upload."}}
```

A resposta é HTTP `422`. Normalize a orientação antes do upload; o backend nunca
rotaciona nem transpõe imagens e nunca cria uma cópia normalizada. Preservar os
bytes inalterados e rejeitar transformações de exibição mantém as coordenadas do
prompt no navegador alinhadas aos pixels do SAM. Isso vale para
`POST /cases/{case_id}/images` e para o `POST /segmentations` stateless.
`POST /evaluations/{evaluation_id}/segmentations` também revalida os bytes
armazenados antes da inferência. Arquivos armazenados anteriormente não são
regravados nem auditados por uma migration, e o endpoint de recuperação de
conteúdo continua devolvendo seus bytes originais.

A busca do caso termina antes da validação do upload. O armazenamento ocorre
antes da transação curta de escrita no banco. Se a persistência ou o commit
falharem, somente o novo arquivo é apagado. Os erros retornados pela API não
contêm detalhes internos de exceção. Assim como no armazenamento de máscaras,
interrupção do processo, falha do sistema de arquivos na limpeza ou resultado
incerto do commit não podem ser tornados atômicos entre o PostgreSQL e o sistema
de arquivos. Não há novas tentativas nem workers de limpeza em segundo plano.

## Testes

Configure `TEST_DATABASE_URL` com um banco PostgreSQL descartável usando o driver
`postgresql+psycopg` e execute:

```powershell
python -m pytest tests/app/api/test_experiment.py -q -ra
python -m pytest -q -ra
```

Cada teste com PostgreSQL usa o schema aleatório isolado do fixture existente e
um LocalStorage temporário real. O teste completo do ciclo HTTP usa um SAM fake e
não precisa de CUDA. Os testes com PostgreSQL são ignorados (skipped) quando
`TEST_DATABASE_URL` está ausente; com ela definida, falhas de conexão são erros.
O CI existente fornece o PostgreSQL.
