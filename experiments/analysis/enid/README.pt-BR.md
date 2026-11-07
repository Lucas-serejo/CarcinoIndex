**Idioma:** [English](README.md) · Português
<!-- synced with README.md @ 55b1b37 -->

# Análise quantitativa ENID

Este diretório reúne as ferramentas de análise e de figuras que rodam sobre os
outputs do Experimento A concluído (veja
[o README do benchmark](../../benchmarks/enid/README.pt-BR.md)). Elas calculam
resultados descritivos e exploratórios por anotação para o capítulo de
resultados do TCC.

| Comando | Lê | SAM / GPU |
| --- | --- | --- |
| `scripts/analyze_enid_results.py` ([execução](#execução)) | somente `results.csv` | Não |
| `scripts/analyze_enid_box_baseline.py` ([baseline](#baseline-de-caixa-preenchida-e-ics-por-bootstrap-agrupado)) | `results.csv` + COCO canônico/splits | Não |
| `scripts/analyze_enid_box_robustness.py` ([robustez](#análise-de-robustez-do-prompt-de-caixa)) | `results_long.csv` + `image_timing.csv` | Não |
| `scripts/render_enid_qualitative_cases.py` ([qualitativo](#inspeção-qualitativa-dos-extremos-selecionados)) | `results.csv`, `extreme_cases.csv`, COCO, frames, checkpoint | **Sim** |
| `scripts/localize_enid_qualitative.py` ([localização](#idioma-das-figuras-figuras-do-tcc)) | Uma execução qualitativa concluída, COCO, frames | Não |
| `scripts/render_enid_examples.py` ([exemplos](#figura-ilustrativa-de-exemplos-do-enid)) | COCO/splits e frames | Não |

`analyze_enid_results.py` roda somente em CPU e lê apenas o `results.csv` do
Experimento A concluído. Ele não carrega SAM, checkpoint, imagens, anotações COCO,
banco de dados, API ou frontend. Não reexecuta o benchmark nem gera sobreposições.
Usa apenas as dependências já existentes numpy, pandas e matplotlib. Os demais
comandos têm as entradas listadas acima e descritas em suas seções.

## Execução

A partir da raiz do repositório, no ambiente Python do projeto (PowerShell):

```powershell
python scripts/analyze_enid_results.py `
  --results experiments/outputs/enid-full-01/results.csv `
  --output experiments/outputs/enid-analysis-01
```

O diretório de saída é criado se não existir; um diretório existente e vazio
também é aceito. Um diretório não vazio é recusado, sem sobrescrever seu
conteúdo. Use um diretório novo a cada execução. Entradas inválidas são
recusadas antes de qualquer arquivo de saída ser gravado. Uma falha de gravação
pode deixar artefatos parciais; depois de corrigir a falha, escolha um novo
diretório.

Os outputs gerados são locais e ignorados pelo Git quando ficam em
`experiments/outputs/`. Um caminho de saída externo arbitrário não é coberto
automaticamente pelas regras de ignore deste repositório. Não versione
CSV/JSON/PNG gerados, datasets, resultados de benchmark, imagens clínicas ou
checkpoints.

## Contrato de entrada

Colunas obrigatórias:

```text
dataset split group_id image_id annotation_id file_name width height
reference_area_pixels predicted_area_pixels dice iou selected_index
selected_score prediction_time_seconds
```

É necessária pelo menos uma linha, com IDs de anotação únicos e inteiros e IDs
de imagem inteiros. O dataset deve ser `ENID`; o split deve ser `train`, `val`
ou `test`. Execuções de smoke e subconjuntos são aceitos; não há exigência de
358 linhas. Campos de texto não podem ser vazios; IDs de grupo permanecem
strings (inclusive com zeros à esquerda). Todos os campos numéricos obrigatórios
devem ser interpretáveis e finitos. Dice e IoU devem estar em [0, 1]; áreas de
referência e dimensões inteiras da imagem devem ser positivas; áreas previstas,
índices selecionados inteiros e tempos de predição devem ser não negativos. O
escore selecionado só precisa ser finito; ele não é restrito a [0, 1]. As razões
de área derivadas também devem ser finitas. Colunas opcionais da origem,
incluindo as de caixa delimitadora e de polígonos, são mantidas no CSV de
candidatos.

## Análises e artefatos

**Resultado principal:** concordância espacial entre as máscaras selecionadas
pelo SAM e as máscaras de referência do ENID, medida pelos valores de Dice e IoU
já existentes. Essas métricas são consumidas como fornecidas; não são
recalculadas nem alteradas.

**Resultados descritivos secundários:** distribuições e resumos pelos splits
oficiais. A análise por split é descritiva. O SAM estava congelado e não foi
treinado no split de treino do ENID neste experimento. Diferenças entre splits
não medem generalização no sentido tradicional de um modelo treinado.

**Análises exploratórias:** associações do escore selecionado pelo SAM e da área
da máscara de referência com o Dice. Pearson é a correlação linear sobre os
valores brutos. Spearman é o Pearson sobre ranks médios, incluindo empates, sem
SciPy. As correlações ficam `null` no JSON e aparecem como indefinidas nas
figuras quando há menos de duas linhas ou uma das variáveis é constante. Para
essas correlações exploratórias, não são produzidos p-valores, testes de
significância, intervalos de confiança, regressão nem interpretações causais. As
análises separadas de baseline de caixa preenchida e de robustez do prompt de
caixa, abaixo, reportam intervalos de confiança por bootstrap agrupado para suas
médias.

| Arquivo | Definição |
| --- | --- |
| `descriptive_summary.json` | Número de linhas, contagens de imagens/grupos únicos, contagens dos splits presentes; média, mediana, mínimo, Q1, Q3 e máximo de Dice, IoU, escore selecionado e área de referência; desvio padrão populacional (`ddof=0`) de Dice/IoU; Pearson e Spearman das duas associações exploratórias. |
| `descriptive_by_split.csv` | Contagem e média, mediana, Q1, Q3, mínimo e máximo de Dice e IoU. Os splits presentes aparecem na ordem train/val/test, seguidos de overall. |
| `dice_distribution.csv` | Contagens e percentuais de todas as anotações em [0, 0.5), [0.5, 0.7), [0.7, 0.8), [0.8, 0.9), [0.9, 1.0]. O último intervalo inclui 1.0. São faixas de visualização, não limiares clínicos nem metodológicos de sucesso. |
| `extreme_cases.csv` | Até cinco anotações por motivo de seleção: menor Dice, maior Dice, menor razão de área estritamente abaixo de 1, maior razão de área estritamente acima de 1. |
| `dice_distribution.png` | Histograma de Dice por anotação, 20 faixas iguais em [0, 1], mediana tracejada. |
| `iou_distribution.png` | Histograma correspondente de IoU por anotação. |
| `selected_score_vs_dice.png` | Dispersão com eixo linear de escore e anotações de Pearson/Spearman. |
| `reference_area_vs_dice.png` | Dispersão com eixo de área logarítmico e anotações de Pearson/Spearman. O Pearson é rotulado `Pearson (raw area)`; as correlações continuam usando valores/ranks da área bruta, não a área em log. |

`descriptive_summary.json` também registra `source.filename` (o nome do arquivo
de entrada, sem caminho absoluto) e `source.sha256` (SHA-256 dos bytes exatos do
CSV de entrada). O mesmo snapshot de bytes é usado para o hash e para a leitura.
Mudanças de fim de linha, de ordem das linhas ou de outros bytes da entrada
alteram o hash mesmo que as estatísticas não mudem.

Os quartis usam interpolação linear nas posições `(n - 1) * q` dos valores
ordenados. O desvio padrão descreve a população de anotações fornecida, portanto
é zero para uma linha. O JSON usa chaves ordenadas e rejeita a serialização de
NaN/Infinity. As linhas são ordenadas por ID de anotação antes do cálculo,
tornando as estatísticas invariantes à ordem das linhas da entrada; a proveniência
da origem continua refletindo os bytes exatos da entrada. As figuras usam o
canvas não interativo Agg, com tamanho e estilo fixos. Ambientes idênticos geram
artefatos reprodutíveis; detalhes de renderização e de ponto flutuante podem
variar entre versões de bibliotecas/fontes.

Os candidatos usam uma linha por motivo de seleção, com ranks começando em 1
dentro de cada motivo: `lowest_dice`, `highest_dice`,
`smallest_predicted_reference_area_ratio` (razões estritamente abaixo de 1) e
`largest_predicted_reference_area_ratio` (razões estritamente acima de 1).
Uma anotação pode, portanto, aparecer várias vezes. O ID numérico de anotação em
ordem crescente desempata todos os casos. As categorias podem ter menos de cinco
linhas, ou nenhuma no caso das razões de área. `area_ratio = predicted_area_pixels /
reference_area_pixels`; valores abaixo/acima de 1 indicam área prevista
menor/maior que a referência. Anotações com áreas iguais ficam fora dessas duas
categorias. A razão de área sozinha não estabelece correção da segmentação,
contenção espacial, subsegmentação ou supersegmentação. Todos os campos de
entrada obrigatórios, as colunas opcionais, a razão de área, o motivo de seleção
e o rank ficam disponíveis para inspeção posterior.

A lista de candidatos alimenta o renderizador qualitativo separado, abaixo;
nenhum caso é rotulado como clinicamente bom ou ruim.

## Baseline de caixa preenchida e ICs por bootstrap agrupado

Um comando separado, somente em CPU, mede quanto o SAM acrescenta além do seu
próprio prompt. A caixa delimitadora XYWH oráculo é rasterizada como o polígono
retangular `[x,y, x+w,y, x+w,y+h, x,y+h]`, com a mesma convenção do pycocotools
usada na referência (`frPyObjects -> merge -> decode`), e comparada com a máscara
de referência canônica usando o `overlap_metrics()` existente. Dice/IoU do SAM
são lidos de `results.csv`, nunca recalculados. Toda linha de resultados deve
corresponder a uma anotação canônica (`load_samples`) em identidade, caixa
delimitadora e área de referência; caso contrário, a execução é abortada antes
de gravar.

```powershell
python scripts/analyze_enid_box_baseline.py `
  --dataset-root datasets/raw/enid/ENID_v1.0_dataset `
  --split-root datasets/raw/enid_split/ENID_v1.0_dataset `
  --results experiments/outputs/enid-full-01/results.csv `
  --output experiments/outputs/enid-box-baseline `
  --language pt-BR `
  --expected-sha256 74c82a21a8205961f70b59305f51c1d5a48762fd1a3e2421b1bd74a22c604d81
```

| Arquivo | Definição |
| --- | --- |
| `box_baseline.csv` | Uma linha por anotação: identidade, caixa delimitadora, áreas da referência/da caixa, pixels da referência fora da caixa rasterizada, `fill_ratio = reference_area / box_area`, `dice`/`iou` do SAM, `box_dice`/`box_iou`, `dice_gain = dice - box_dice`, `iou_gain = iou - box_iou`. |
| `box_baseline_summary.json` | Médias/medianas, contagem e % com `dice_gain > 0`, % com `box_dice >= 0.80`, pixels da referência fora da caixa, tercis exploratórios da razão de preenchimento, ICs por bootstrap, SHA-256 dos resultados e dos JSONs COCO/splits, versões de pacotes junto com o caminho do módulo `pycocotools` no ambiente de execução, e convenções. |
| `dice_gain_vs_fill_ratio.png` | Dispersão exploratória do ganho de Dice versus razão de preenchimento, localizada com `localize_figure` mais textos pt-BR específicos da figura. |

`cluster_bootstrap()` fornece ICs percentis de 95% para a média de `dice`, `iou`,
`box_dice`, `box_iou`, `dice_gain` e `iou_gain`. Ele reamostra clusters inteiros
com reposição (tantos quantos observados), de modo que anotações do mesmo
cluster nunca são separadas; a média de cada réplica é ponderada por anotações.
Uma única matriz de sorteios de `numpy.random.default_rng(20261027)` é
compartilhada por todas as colunas; 10.000 reamostragens; quantis lineares.
`group_id` é o cluster principal e `image_id`, uma análise de sensibilidade.
Esses intervalos descrevem a variabilidade amostral das médias por anotação do
ENID sob reamostragem de clusters; não são validação clínica e não tornam
`group_id` um identificador de paciente. Os tercis usam faixas de mesma
frequência sobre os ranks da razão de preenchimento (empates por ID de anotação)
e são exploratórios. Os outputs seguem a mesma regra de diretório novo ou vazio.

## Análise de robustez do prompt de caixa

`robustness_analysis.py` consolida a execução de robustez
(`experiments/benchmarks/enid/README.md`) em CPU, lendo apenas
`results_long.csv` e `image_timing.csv`. As cinco condições devem cobrir o mesmo
conjunto de anotações. Ele reutiliza `cluster_bootstrap`, `SEED`, `N_RESAMPLES`,
`LEVEL` e os rótulos de tercis de `box_baseline.py`.

```powershell
python scripts/analyze_enid_box_robustness.py `
  --results experiments/outputs/enid-box-robustness/results_long.csv `
  --output experiments/outputs/enid-box-robustness-analysis `
  --language pt-BR `
  --expected-sha256 5fc5d15aab2f3eee4366ecfd654ec76b405b3ecba61c8c35e715984c56cefd81
```

`--timing` é opcional e aponta para `image_timing.csv`; por padrão, o arquivo é
lido do mesmo diretório de `--results`.

| Arquivo | Definição |
| --- | --- |
| `robustness_by_condition.csv` | Por condição: n, média/mediana de Dice, média de IoU, média do Dice da caixa do prompt, ganho (SAM − caixa), % SAM > caixa, caixas recortadas; ICs de 95% (group_id e image_id) para Dice, IoU, ganho, Dice da caixa do prompt e, exceto em ref, a diferença pareada de Dice em relação a ref. |
| `robustness_paired.csv` | Por condição diferente de ref: diferença pareada de Dice em relação a ref (calculada por anotação, unida por `annotation_id`, antes do bootstrap) com ICs; contagens de melhor/igual/pior; para jitter10/expand10/expand20, as perdas da caixa e do SAM em relação a ref e a fração absorvida descritiva `1 − ΔSAM/Δbox` sobre as médias (sem IC). |
| `normalized_gain_by_tercile.csv` | Exploratório, somente ref: `(dice − box) / (1 − box)` (indefinido quando o Dice da caixa é 1) por tercil da razão de preenchimento, com razão de preenchimento mediana, ganho bruto e normalizado, e % SAM > caixa. |
| `timing_summary.csv` | Mediana, P5 e P95 do tempo de embedding (por imagem) e do tempo de predição (por condição e geral). Os tempos só são comparáveis dentro da mesma execução. |
| `robustness_summary.json` | Tudo o que está acima, mais hashes das entradas, seed, reamostragens, convenções e versões de pacotes (incluindo o caminho do módulo `pycocotools` no ambiente de execução). |
| `robustness_dice_by_condition.png` | Dice médio do SAM e Dice médio da caixa preenchida do prompt para ref, jitter10, expand10 e expand20, com ICs de 95% por group_id; marcadores distintos para impressão em tons de cinza; ref_single excluída. |

Cada condição passa por bootstrap separadamente, com a mesma seed, sobre as
mesmas anotações e clusters, de modo que todas as condições compartilham uma
matriz de reamostragem por tipo de cluster. Os rótulos pt-BR dizem "caixa
delimitadora", nunca "bbox".

## Inspeção qualitativa dos extremos selecionados

O renderizador separado recria máscaras para **cada anotação única** fornecida
por `extreme_cases.csv`. São extremos quantitativos selecionados de propósito,
não amostras representativas de todo o ENID. Não há seleção interativa nem
filtragem visual. IDs de anotação duplicados geram uma única predição e uma
única figura; todos os pares motivo/rank verificados são mantidos. Antes de criar
os outputs, `extreme_cases.csv` é verificado contra a seleção recalculada a
partir do `results.csv` de referência, usando a função quantitativa existente
`extreme_cases()`. As tuplas exatas de ID de anotação/motivo/rank devem
coincidir, inclusive na multiplicidade de linhas: anotações substituídas,
motivos ou ranks alterados, linhas ausentes e linhas extras são rejeitados. A
ordem das linhas da entrada não afeta a verificação. Os pares são ordenados por
motivo e depois por rank numérico e armazenados como arrays JSON alinhados em
`selection_reasons` e `selection_ranks` no `cases.csv`.

```powershell
python scripts/render_enid_qualitative_cases.py `
  --dataset-root datasets/raw/enid/ENID_v1.0_dataset `
  --split-root datasets/raw/enid_split/ENID_v1.0_dataset `
  --results experiments/outputs/enid-full-01/results.csv `
  --cases experiments/outputs/enid-analysis-01/extreme_cases.csv `
  --checkpoint ../sam2/checkpoints/sam2.1_hiera_small.pt `
  --output experiments/outputs/enid-qualitative-01 `
  --device cuda `
  --dtype float32
```

`--model-config` tem default `DEFAULT_MODEL_CONFIG`. Use o mesmo checkpoint,
config, device e dtype da execução original. Nenhuma dependência é adicionada. Os
testes sintéticos rodam em CPU sem SAM, CUDA, ENID real ou checkpoint real; a
renderização real exige o mesmo ambiente SAM do benchmark.

O renderizador valida os resultados de referência com o validador de análise
existente, incluindo IDs de anotação únicos e métricas, áreas, índice selecionado
e escore selecionado finitos. Os casos exigem IDs de anotação/imagem, nome de
arquivo, split, ID de grupo, um dos quatro motivos documentados e um rank inteiro
positivo. Cada caso deve corresponder aos resultados e à identidade no COCO
canônico. Os dados canônicos e os splits oficiais são validados por
`load_samples(..., split="all")`.

As anotações únicas e as linhas de saída são ordenadas por ID de anotação. Para
reutilizar um embedding de `set_image()` por imagem, a inferência visita as
imagens na ordem da primeira ocorrência e prevê suas anotações selecionadas em
ordem crescente de ID. Os resultados selecionados de IDs posteriores ficam em
cache até a sua vez na ordem global de renderização. As imagens têm as dimensões
conferidas e são convertidas para RGB uint8 sem redimensionamento. Os polígonos
canônicos fornecem as máscaras de referência; `annots/*.png` nunca é usado. A
caixa delimitadora XYWH oráculo/de referência é convertida para XYXY;
`multimask_output=True` e exatamente `result.selected_mask` preservam a seleção
pelo maior escore do SAM. A sobreposição com a referência nunca escolhe um
candidato do SAM. Nenhum pós-processamento é aplicado.

A reexecução existe apenas para recriar máscaras para visualização. `results.csv`
continua sendo o registro numérico de referência e nunca é sobrescrito. O
`overlap_metrics()` existente calcula Dice/IoU da reexecução apenas para
proveniência. Diferenças absolutas de Dice ou IoU **maiores que 1e-6**, ou um
índice selecionado diferente, abortam a execução. Tanto a área de referência
canônica quanto a área da máscara prevista na reexecução devem coincidir
exatamente com o benchmark. O contrato de consistência, portanto, confere área de
referência, área prevista, Dice, IoU e índice selecionado. `cases.csv` registra
`benchmark_predicted_area_pixels`, `rerun_predicted_area_pixels` e o
`predicted_area_pixel_delta` absoluto (zero para execuções coincidentes). Os dois
escores e sua diferença absoluta são registrados sem exigir igualdade bit a bit;
pequenas diferenças de ponto flutuante no escore podem ocorrer. Isso não acrescenta
métrica de segmentação e não é um segundo experimento quantitativo.

Use um diretório novo dentro de `experiments/outputs/`, que é ignorado. Um
diretório ausente ou vazio é aceito; um diretório não vazio é recusado. Os
diretórios do dataset e dos splits são protegidos contra gravação de outputs.
Falhas de validação antes da criação dos outputs não deixam artefatos. Falhas
posteriores deixam um manifest `incomplete` e possivelmente imagens parciais:
estas não devem ser tratadas como uma execução concluída. Corrija o problema e
escolha um novo diretório de saída.

| Artefato | Contrato |
| --- | --- |
| `manifest.json` | Status de conclusão, timestamp UTC, contagens de linhas de seleção e de anotações renderizadas, IDs selecionados ordenados, modelo/config, nome do checkpoint, device/dtype, política de seleção, tolerância, versões de pacotes, SHA-256 dos snapshots exatos de bytes dos dois CSVs de entrada, do COCO canônico, de cada JSON de split oficial e do checkpoint. Sem caminhos absolutos nem texto de exceção. |
| `cases.csv` | Uma linha por anotação única: identidade, todos os motivos/ranks de seleção, caixa delimitadora XYWH canônica, áreas de referência/prevista do benchmark, Dice/IoU/índice/escore do benchmark e da reexecução, diferenças absolutas de métricas/escore e caminhos relativos dos artefatos. Gravado somente depois que todas as figuras passam nas verificações de consistência. |
| `cases/annotation_000001/comparison.png` | Quatro painéis com o quadro completo: original com a caixa delimitadora oficial, sobreposição da referência do ENID, sobreposição da máscara selecionada pelo SAM e pixels de ambos/só referência/só SAM com legenda. O ID usa pelo menos seis dígitos apenas para ordenar os arquivos. |
| `cases/annotation_000001/reference_mask.png` e `sam_mask.png` | Máscaras binárias de 8 bits nas dimensões originais: fundo 0, máscara 255. Nenhuma imagem original avulsa é copiada. |

As figuras usam o canvas não interativo Agg, uma paleta fixa pensada para
daltonismo (verde para a interseção, azul para só referência, vermelhão para só
SAM) e opacidade de sobreposição 0.5 em todas. A geometria e o contexto completos
da imagem são mantidos; não há recorte pela caixa delimitadora. Os títulos
reportam valores factuais do benchmark. A renderização dos gráficos pode variar
entre versões de bibliotecas/fontes; os pixels dos gráficos não são testados por
igualdade. Todas as imagens, máscaras e tabelas geradas são artefatos locais de
pesquisa, nunca entradas do repositório. Não versione esses artefatos nem
checkpoints.

Os limites científicos permanecem: o ENID retrata lesões de endometriose, **não
carcinomatose peritoneal**. A localização continua derivada do oráculo/da
referência, não é detecção autônoma. As imagens geradas não são validação
clínica. Extremos de razão de área, sozinhos, não provam subsegmentação nem
supersegmentação. A inspeção visual pode descrever padrões aparentes de erro, mas
não estabelece causalidade. O escore selecionado continua sendo uma estimativa
interna de ranqueamento/qualidade do SAM, não confiança clínica. Este protocolo
não tira conclusões sobre imagens reais e não prescreve uma interpretação na
monografia nem um subconjunto final de figuras.

## Idioma das figuras (figuras do TCC)

O comando quantitativo aceita `--language en` (padrão) ou `--language pt-BR` (os
comandos de baseline e de robustez acima aceitam a mesma opção). As figuras em
português se destinam à monografia. O idioma altera apenas o texto visível: os
artefatos numéricos vêm do mesmo `results.csv` de referência, com estatísticas,
correlações, faixas e seleção determinística inalteradas. Outputs originais nunca
são sobrescritos. Nenhum dado ou protocolo experimental é alterado.

```powershell
python scripts/analyze_enid_results.py `
  --results experiments/outputs/enid-full-01/results.csv `
  --output experiments/outputs/enid-analysis-ptbr `
  --language pt-BR
```

Isso produz `dice_distribution.png`, `iou_distribution.png`,
`selected_score_vs_dice.png` e `reference_area_vs_dice.png`, além dos resumos
CSV/JSON inalterados. O layout original em inglês é resolvido a 180 DPI antes da
tradução do texto, preservando a geometria dos eixos e o tamanho/estilo existentes
das figuras.

Para uma **execução qualitativa concluída**, use o comando separado, somente
leitura, abaixo. Ele não importa nem executa o SAM, não exige checkpoint e não
recria predições. O `render_cases()` original e a CLI experimental mantêm o
comportamento existente.

```powershell
python scripts/localize_enid_qualitative.py `
  --dataset-root datasets/raw/enid/ENID_v1.0_dataset `
  --split-root datasets/raw/enid_split/ENID_v1.0_dataset `
  --results experiments/outputs/enid-full-01/results.csv `
  --cases experiments/outputs/enid-analysis-01/extreme_cases.csv `
  --source experiments/outputs/enid-qualitative-01 `
  --output experiments/outputs/enid-qualitative-ptbr `
  --language pt-BR
```

`--language en` também é aceito; este comando separado tem `pt-BR` como padrão.
Seu diretório de saída não pode existir e deve ficar fora dos diretórios de
origem, do dataset e dos splits. Antes de criá-lo, o comando confere o manifest
da execução de origem concluída, o protocolo, os hashes de entrada registrados,
IDs/motivos/ranks determinísticos e a ordem dos casos; identidade/caixa
delimitadora canônicas; máscaras PNG binárias e suas dimensões; igualdade exata
da máscara de referência com o COCO; áreas e índice selecionado exatos; e
concordância de Dice/IoU dentro da tolerância existente de `1e-6`. Os valores de
escore/índice do benchmark devem coincidir com os casos registrados e nunca são
inferidos a partir das máscaras. Campos opcionais de caixa delimitadora no CSV
de resultados são comparados numericamente, sem alterar os dados de entrada. A
execução concluída de 358 anotações/160 imagens mantém exatamente seus 16 casos
únicos selecionados. Subconjuntos sintéticos continuam suportados, com a mesma
validação de seleção.

O renderizador usa snapshots em memória, já verificados, das imagens originais do
ENID e das máscaras salvas, a caixa delimitadora canônica, as métricas de
referência, as mesmas cores, ALPHA, layout 2x2, figura 12x8, 180 DPI e limites de
painel com o quadro completo. Ele grava apenas
`cases/annotation_XXXXXX/comparison.png` localizado e um **novo** manifest de
proveniência. Esse manifest registra o nome do diretório de origem (sem caminho
absoluto), o idioma, `mode: render-only`, `inference_executed: false`, os IDs
ordenados, os hashes SHA-256 de entradas/máscaras/imagens e o estado de
conclusão. Os hashes são o registro de proveniência. Nenhum CSV, JSON, máscara ou
comparação original da origem é modificado ou sobrescrito. Falhas de
renderização deixam um novo manifest incompleto. Os artefatos gerados continuam
ignorados em `experiments/outputs/`.

O manifest científico de origem não contém hashes de frames/máscaras. Esses
arquivos são conferidos contra a geometria canônica e o contrato de consistência
científica; a nova proveniência registra seus bytes atuais exatos para
verificação futura.

## Figura ilustrativa de exemplos do ENID

`scripts/render_enid_examples.py` desenha uma figura ilustrativa 2x2 das anotações
de referência do ENID, em CPU, sem SAM, checkpoint ou `results.csv`. Cada painel
mostra um frame com o contorno da segmentação de referência (rasterizada com
`reference_mask`, sem preenchimento) e a caixa delimitadora de referência de cada
anotação, uma cor por anotação. Os títulos dos painéis e a legenda estão em
português.

```powershell
python scripts/render_enid_examples.py `
  --dataset-root datasets/raw/enid/ENID_v1.0_dataset `
  --split-root datasets/raw/enid_split/ENID_v1.0_dataset `
  --output experiments/outputs/enid-examples-01
```

As imagens são escolhidas por uma regra determinística fixa, registrada no
manifest: duas imagens com exatamente uma anotação cuja área de referência é a
mais próxima da mediana; depois, duas imagens com três a cinco anotações cuja
área mediana é a mais próxima da mediana desses valores, com `group_id` distintos
entre os painéis e empates resolvidos pelo menor `image_id`. O comando aborta a
menos que a regra selecione exatamente os `image_id` 72, 136, 79 e 32 (painéis
A–D). O diretório de saída não pode existir; um diretório existente é recusado.
Ele grava `enid_examples.png` (200 DPI) e `manifest.json`, que registra a regra
de seleção e suas estatísticas, os painéis (IDs de imagem e de anotação,
`group_id`, split, áreas de referência, cores), o estilo e o SHA-256 do
`coco.json` e da figura. O manifest também guarda o caminho do `coco.json`
exatamente como informado em `--dataset-root`; por isso, use um caminho relativo.

## Limites de interpretação

- O ENID contém lesões de endometriose, não carcinomatose peritoneal.
- A caixa delimitadora é derivada da referência/oráculo: trata-se de segmentação
  com localização conhecida, não de detecção de lesões.
- O escore selecionado é uma estimativa interna de qualidade/ranqueamento do SAM,
  não confiança clínica.
- A anotação é a unidade de análise. Várias anotações podem pertencer a uma
  imagem, e várias imagens podem compartilhar um ID de grupo. A semântica clínica
  do ID de grupo não está estabelecida e ele não deve ser interpretado como ID de
  paciente.
- As 358 anotações da execução concluída não devem ser descritas como 358
  pacientes independentes. Esta ferramenta não assume independência entre
  anotações para inferência.
- As correlações são exploratórias e não estabelecem causalidade. Não se alega
  limiar clínico de adequação, predição de LS clínico, PCI automático nem
  validação clínica.

## Verificação sintética

```powershell
python -m pytest tests/experiments/test_enid_analysis.py -q
python -m pytest tests/experiments/test_enid_box_baseline.py -q
python -m pytest tests/experiments/test_enid_robustness_analysis.py -q
python -m pytest tests/experiments/test_enid_qualitative.py -q
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

Os testes usam arquivos CSV sintéticos temporários, fixtures COCO sintéticas e
figuras headless; nenhuma saída real do ENID ou do benchmark é necessária. O CI
deve rodar apenas testes sintéticos, nunca a renderização qualitativa real com
ENID/SAM.
