**Idioma:** [English](README.md) · Português
<!-- synced with README.md @ d88deef -->

# CarcinoIndex

O CarcinoIndex é uma plataforma experimental com especialista no ciclo
(human-in-the-loop) para investigar a segmentação assistida de lesões
laparoscópicas no contexto da carcinomatose peritoneal. O foco atual é o SAM 2.1
Hiera Small com prompts fornecidos pelo especialista.

O sistema não descobre de forma autônoma onde está uma lesão. O especialista
indica o objeto clínico de interesse; o SAM transforma esse prompt em uma máscara
de segmentação para a pesquisa quantitativa subsequente. O escore de lesão
clínico (LS) é fornecido pelo especialista e nunca é inferido pelo SAM.

A documentação está disponível em inglês e português; a monografia é escrita em
português.

## Objetivo de pesquisa e limites

Avaliar em que medida o SAM 2.1, condicionado a uma localização conhecida da
lesão (uma caixa delimitadora), produz máscaras espacialmente concordantes com
segmentações de referência em imagens laparoscópicas. O benchmark atual usa o
ENID (endometriose) como proxy laparoscópico; ele não é validação clínica para
carcinomatose peritoneal. Este é um objetivo de pesquisa, não uma alegação de
validação clínica, desempenho diagnóstico ou desempenho de predição de LS.

O repositório usa dois rótulos de experimento:

- **Experimento A** (`Experiment A`): o benchmark técnico offline no ENID, com
  caixas delimitadoras de referência como prompts e as segmentações de referência
  do ENID como comparação. É o experimento avaliado no TCC.
- **Experimento B** (`Experiment B`): uma avaliação planejada no domínio-alvo,
  com imagens laparoscópicas de carcinomatose peritoneal e revisão, pelo
  especialista, da segmentação e do fluxo do CarcinoIndex. Ainda não foi
  realizada.

O tamanho físico da lesão em centímetros não pode ser recuperado diretamente dos
pixels de uma imagem monocular sem calibração, referência física ou informação de
profundidade. Área em pixels não é uma medida física, e o sistema atual não
implementa estimativa de tamanho físico nem de profundidade.

Atualmente não há máscaras aceitas, validadas, de referência ou ground truth no
fluxo do produto. A revisão visual e a finalização da Evaluation não transformam
uma máscara do SAM em máscara de referência nem estabelecem nenhum desses
estados. O `selected_score` do SAM é um escore interno previsto de
qualidade/ranqueamento, não confiança clínica.

Para o Experimento B planejado, as categorias qualitativas implementadas são
`adequate`, `partially_adequate` e `inadequate`; o protocolo mais amplo do estudo
continua pendente de validação. Correção manual de máscara ou criação de máscara
de referência não é exigida pelo protocolo mínimo atual do TCC.

A modelagem automática de LS baseada em features está fora do escopo atual do TCC
e não está implementada. Não existe classificador, e o fluxo clínico atual não
calcula nem persiste features.

## Fluxo implementado no MVP v1 (F1-F4)

O frontend Angular e o backend FastAPI oferecem:

1. Configuração do experimento (Experiment Setup): informar códigos
   pseudonimizados do caso e do anotador, escolher uma região PCI ou indicar
   explicitamente que ela não pôde ser determinada, e enviar uma imagem clínica.
   O backend persiste o caso, a imagem e a Evaluation em rascunho (draft).
2. Área de segmentação (Segmentation Workspace): recuperar a imagem persistida e
   desenhar uma caixa delimitadora ao redor da lesão indicada pelo especialista.
3. Inferência do SAM 2.1: gerar uma máscara a partir do prompt e persistir uma
   SegmentationAttempt. Várias tentativas podem ser criadas; o frontend exibe o
   resultado mais recente da sessão atual. Com a máscara visível, o especialista
   classifica sua qualidade visual/espacial como Adequada, Parcialmente adequada
   ou Inadequada. Nenhuma categoria vem pré-selecionada; preparar uma nova caixa
   ou executar de novo limpa a revisão.
4. Avaliação clínica (Clinical Assessment): revisar a qualidade de segmentação
   escolhida, informar manualmente o LS clínico (0-3) ou indicar explicitamente
   que ele não pôde ser determinado, e finalizar a Evaluation. A confiança
   opcional do anotador só fica disponível quando um LS clínico é informado.
5. Nova avaliação: após a finalização, voltar a uma configuração limpa sem
   recarregar a página. O código do anotador continua editável e pré-preenchido;
   o idioma e as regiões carregadas são preservados. O próximo envio cria um novo
   caso, uma nova imagem e uma nova Evaluation.

Para o Experimento B planejado, o código de caso visível identifica um caso
experimental, não um paciente. Cada fotografia pode ser tratada como um novo
caso; nenhuma relação de paciente é inferida entre imagens. O nome interno na
API/banco, `anonymous_patient_code`, permanece inalterado. Reiniciar o fluxo não
altera registros persistidos anteriormente.

O backend também aceita prompts de pontos, mas o frontend atual usa caixas
delimitadoras. Novas finalizações pela API exigem um valor explícito de
`clinical_ls` (0–3 ou null), `reviewed_attempt_id` e `segmentation_quality`. A
tentativa revisada deve pertencer àquela Evaluation. A qualidade é um julgamento
qualitativo humano da saída do SAM, não validação clínica, ground truth, LS ou
confiança do SAM. Região PCI e LS são fornecidos pelo especialista quando
determináveis; nenhum deles é inferido pelo SAM. Região nula e LS nulo em uma
avaliação finalizada significam não determinado. A confiança deve ser nula
quando o LS for nulo.

O PostgreSQL e o armazenamento local preservam o ClinicalCase pseudonimizado, os
bytes originais validados da imagem e seu SHA-256, a Evaluation, as tentativas de
segmentação, as máscaras do SAM, os dados do prompt, os metadados do SAM, o LS
clínico do especialista e a confiança opcional nessa avaliação de LS, além do ID
da tentativa revisada e da qualidade de segmentação humana. O modelo de dados é:

`ClinicalCase -> Image -> Evaluation -> SegmentationAttempt`

O endpoint de segmentação stateless continua disponível separadamente. A rotina
de composição de PCI do backend usa LS regional informado manualmente; o fluxo
experimental não calcula o PCI completo. Não há detecção autônoma de lesões,
classificação automática de LS clínico nem diagnóstico autônomo.

## Integridade das coordenadas da imagem

Uploads JPEG e PNG estáticos só são aceitos quando os metadados de orientação
estão ausentes ou a EXIF Orientation é normal (`1`). Orientações `2` a `8` e
metadados de orientação malformados ou não suportados são rejeitados com HTTP
`422` (`unsupported_image_orientation`). Normalize a orientação antes de enviar
uma imagem desse tipo.

O servidor nunca rotaciona, transpõe, redimensiona ou recomprime as imagens
enviadas. Os bytes armazenados são iguais aos bytes enviados e validados, e o
SHA-256 é calculado sobre esses bytes exatos. Rejeitar transformações de exibição
preserva a concordância entre as coordenadas do especialista no navegador e os
pixels fornecidos ao SAM. Veja o
[contrato de validação e armazenamento de imagens](docs/experiment_lifecycle_api.md#image-storage-and-transactions).

## Estrutura do repositório

```text
backend/       FastAPI, SAM wrapper, persistence
frontend/      Angular Experiment Setup, Segmentation, and Clinical Assessment
docs/          API lifecycle, architecture, and research methodology
notebooks/     Synthetic SAM wrapper validation
scripts/       Development launcher, SAM environment/feasibility checks, ENID benchmark,
               robustness, analysis and figure CLIs (including render_enid_examples.py),
               evaluation CSV export, and local experiment data reset
tests/         CPU-compatible tests and opt-in PostgreSQL/CUDA integration tests
datasets/      Research data organization; clinical images are not versioned
experiments/   Offline benchmarks and local outputs; checkpoints are not versioned
```

Em resumo: `backend/` contém FastAPI, o wrapper do SAM e a persistência;
`frontend/`, as telas Angular de configuração, segmentação e avaliação clínica;
`docs/`, o ciclo de vida da API, a arquitetura e a metodologia de pesquisa;
`notebooks/`, a validação sintética do wrapper do SAM; `scripts/`, o
inicializador de desenvolvimento, as verificações de ambiente/viabilidade do SAM,
as CLIs de benchmark, robustez, análise e figuras do ENID (incluindo
`render_enid_examples.py`), a exportação CSV das avaliações e o reset dos dados
experimentais locais; `tests/`, os testes compatíveis com CPU e os testes de
integração opcionais com PostgreSQL/CUDA; `datasets/`, a organização dos dados de
pesquisa (imagens clínicas não são versionadas); `experiments/`, os benchmarks
offline e os outputs locais (checkpoints não são versionados).

## Pré-requisitos

O ambiente validado está descrito passo a passo no
[guia de configuração do SAM 2.1 no Windows](docs/methodology/sam2_windows_setup.md).
Em resumo, a partir da raiz do repositório:

1. Python 3.11 (a versão usada no CI) em um ambiente virtual, como `.venv`.
2. Instale o PyTorch **antes** das dependências do projeto, porque
   `backend/requirements.txt` não fixa `torch`/`torchvision` e uma instalação
   simples pode resolver outro build (por exemplo, somente CPU):

   ```powershell
   python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
   python -m pip install -r backend/requirements.txt
   ```

3. Instale o [repositório oficial do SAM 2](https://github.com/facebookresearch/sam2)
   em modo editável, a partir de um clone fora deste repositório (`pip install -e .`
   no clone; o guia usa `SAM2_BUILD_CUDA=0`). O SAM 2 não consta em
   `backend/requirements.txt`.
4. Baixe o checkpoint externo `sam2.1_hiera_small.pt` e confira seu SHA-256
   (`Get-FileHash -Algorithm SHA256`); o valor validado é
   `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38`.
   A configuração do modelo é `configs/sam2.1/sam2.1_hiera_s.yaml`.

Nenhum checkpoint é baixado automaticamente. Imagens clínicas e checkpoints devem
ficar fora do controle de versão. O frontend exige ainda o Node.js 24 (veja o
[README do frontend](frontend/README.md)).

## Desenvolvimento e documentação técnica

Execute os comandos do backend a partir da raiz do repositório.

- [Configuração e execução do backend](backend/README.md): PostgreSQL, migrations
  Alembic existentes, armazenamento local, configurações SAM/CUDA e o script de
  desenvolvimento no Windows.
- [Configuração e fluxo do frontend](frontend/README.md): desenvolvimento Angular,
  testes, build de produção e comportamento F1-F4.
- [API do ciclo de vida do experimento](docs/experiment_lifecycle_api.md): criar e
  recuperar recursos, registrar tentativas de segmentação e finalizar uma Evaluation.
- [Exportação CSV do Experimento B](backend/README.md#exportação-do-experimento-b-csv):
  `python scripts/export_experiment_b.py`, somente leitura, uma linha por
  Evaluation finalizada.
- [Reset dos dados experimentais locais](backend/README.md#reset-dos-dados-experimentais-locais):
  dry-run por padrão; `--execute --confirm <database>` limpa as tabelas do
  experimento e o armazenamento gerenciado.
- [Arquitetura de persistência](docs/architecture/experiment_persistence.md):
  modelo de dados, limites de transação e limitações do armazenamento.
- [Contrato de inferência do SAM](docs/architecture/sam2_inference_contract.md):
  uma instância do modelo, um worker e inferência serializada.
- [Configuração do SAM 2.1 no Windows](docs/methodology/sam2_windows_setup.md):
  ambiente Python/PyTorch/CUDA validado, instalação do SAM 2, checkpoint e SHA-256.
- [Protocolo de LS pendente de validação](docs/methodology/pci_protocol_pending_validation.md):
  armazenamento manual do LS e os identificadores de protocolo usados até a
  validação dos critérios de tamanho.
- [Benchmark de segmentação ENID](experiments/benchmarks/enid/README.pt-BR.md):
  Experimento A offline, prompts de caixa de referência, máscaras de polígonos
  COCO e Dice/IoU.
- [Análise quantitativa ENID](experiments/analysis/enid/README.pt-BR.md): resumos
  descritivos reprodutíveis e figuras exploratórias a partir dos CSVs de
  benchmarks concluídos.

Testes do backend compatíveis com CPU:

```powershell
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

Os testes com PostgreSQL exigem um banco descartável configurado em
`TEST_DATABASE_URL`; sem ela, são ignorados (skipped). Os testes reais de
integração com o SAM exigem um checkpoint externo e CUDA.
`notebooks/sam_validation.ipynb` e `scripts/run_sam2_real_image.py` servem para
exploração sintética/não clínica.

Autenticação, edição/aceite de máscaras, exportação em lote de imagens/máscaras,
LS automático e um frontend completo de PCI estão fora do MVP implementado.
