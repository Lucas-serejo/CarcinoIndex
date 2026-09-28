# Experimento A — segmentação guiada ENID

Pergunta: dada uma lesão laparoscópica localizada por uma bounding box de
referência, quão semelhante é a máscara do SAM 2.1 Hiera Small à segmentação
especializada do ENID?

ENID é um proxy laparoscópico de lesões de **endometriose**, não carcinomatose
peritoneal. A bbox oficial é um **oracle/control prompt**: este experimento
mede segmentação com localização conhecida, não detecção. Não há treinamento,
fine-tuning, classificação LS, PCI ou alegação de validação clínica.

## Protocolo

- Unidade experimental: uma annotation. `coco.json` é a fonte canônica de bbox
  e segmentation; `annots/*.png` não participa do experimento.
- Os três JSONs oficiais determinam o split. IDs e grupos devem ser disjuntos e
  cobrir o COCO canônico. `group_id` é o prefixo `c_<n>` do filename; sua
  semântica clínica não está documentada, portanto não é chamado patient_id.
- A bbox COCO XYWH vira `[x, y, x + width, y + height]`, sem padding ou jitter.
- `pycocotools.mask.frPyObjects → merge → decode` rasteriza a união dos polygons
  na resolução original de cada imagem. Uma referência rasterizada vazia é erro.
- Reutiliza `SAM2Segmenter`, `DEFAULT_MODEL_CONFIG` e `SegmentationResult`.
  Imagens RGB uint8 são carregadas sem resize manual. Há um `set_image` por frame,
  prompts sequenciais e limpeza de estado ao terminar cada frame.
- `multimask_output=True`; usa exatamente `selected_mask`, selecionada pelo maior
  score previsto pelo SAM. Nunca escolhe a máscara pela sobreposição com a
  referência. `selected_score` **não é confiança clínica**.
- Ordena annotations por ID crescente, filtra o split e aplica `--limit N`.
  Depois agrupa as selecionadas por imagem para reutilizar embeddings. A ordem
  das linhas pode diferir da ordem global dos IDs quando estes se intercalam.
- Dice = `2 * intersection / (prediction_area + reference_area)`;
  IoU = `intersection / union`, sobre máscaras booleanas. Áreas são contagens de
  pixels, nunca o campo COCO `area`. Predição vazia contra referência não vazia
  produz zero. A função de métricas convenciona 1 para duas máscaras vazias,
  mas o runner rejeita referência vazia.

## Execução

Instale `backend/requirements.txt` e configure o SAM/checkpoint local conforme
[o guia existente](../../../../docs/methodology/sam2_windows_setup.md).
Da raiz do repositório (comando em uma linha, também compatível com PowerShell):

```text
python scripts/run_enid_benchmark.py --dataset-root datasets/raw/enid/ENID_v1.0_dataset --split-root datasets/raw/enid_split/ENID_v1.0_dataset --checkpoint ../sam2/checkpoints/sam2.1_hiera_small.pt --output experiments/outputs/enid-smoke --split all --device cuda --dtype float32 --limit 3
```

`--split` aceita `all` (default), `train`, `val`, `test`. Remover `--limit` executa
toda a seleção; o benchmark completo é uma etapa posterior à implementação.
`--config` tem default `DEFAULT_MODEL_CONFIG`; `--dtype` aceita `float32` (default)
e `bfloat16`. Não há fallback automático de CUDA para CPU.

Use um diretório de saída novo/vazio em cada execução. Diretórios dentro dos
inputs ou de `datasets/raw` são recusados. Datasets e outputs permanecem locais
e ignorados pelo Git.

- `results.csv`: uma linha por annotation, IDs, split, grupo, filename relativo,
  dimensões, bbox, quantidade de polygons, áreas, Dice/IoU e seleção/tempo do SAM.
  `prediction_time_seconds` é o tempo de predição medido pelo wrapper, sem o embedding.
- `summary.json`: status, UTC, contagens, seleção, hashes SHA-256 do COCO, splits e
  checkpoint, modelo/config/device/dtype, versões de pacotes, política de seleção,
  médias e medianas por annotation (overall e por split) e tempo total, incluindo
  validação, hashing, carregamento e inferência. Não é uma estimativa por paciente.
- Falhas encerram com código não zero, mensagem no stderr e resumo `incomplete`.
  Resultados parciais ficam em `results.incomplete.csv`; não são resultados de uma
  execução completa. `failure_count` conta o evento fatal (inclusive erro de
  configuração), `success_count` conta linhas concluídas. `images_processed`
  conta imagens com pelo menos uma annotation concluída. O resumo identifica
  etapa/IDs/tipo do erro sem persistir caminhos absolutos.

Os hashes e versões ajudam a reproduzir a execução; não há garantia de igualdade
bit a bit entre hardware, kernels e versões diferentes. Não são gerados PNGs,
figuras ou relatórios clínicos.

## Testes

```text
python -m pytest tests/experiments/test_enid_benchmark.py -q
python -m pytest -q -ra -m "not sam2_integration and not sam2_api_integration"
```

Fixtures sintéticas temporárias e um fake que retorna `SegmentationResult`
verificam COCO, splits, rasterização, métricas, seleção, ciclo de vida e falhas.
Esses testes não carregam `sam2`, checkpoint real, GPU ou ENID real.
