# Contrato de inferência do SAM 2.1 na API M3

Este documento descreve o limite implementado entre o módulo de IA validado
até a M2.5 e a API experimental da M3.

## Instância do modelo

O SAM 2.1 Hiera Small é caro para carregar. O lifespan cria uma única
instância de `SAM2Segmenter`, chama `load()` uma vez no startup e reutiliza o
modelo entre inferências. No shutdown, chama `close()`.

O checkpoint continua externo ao CarcinoIndex e a configuração permanece o
identificador lógico `configs/sam2.1/sam2.1_hiera_s.yaml`.

## Estado do predictor

O predictor oficial mantém o embedding e o shape da imagem atual.
Consequentemente:

- `set_image()` seguido de `segment_with_box()` ou `segment_with_points()` é
  adequado para notebooks e refinamento interativo;
- essas chamadas não são seguras para execução concorrente na mesma
  instância;
- `infer()` representa uma unidade lógica `set → predict → clear` e limpa o
  estado transitório em sucesso ou falha;
- `infer()` não implementa sincronização e também precisa de exclusão mútua
  quando a instância é compartilhada.

## Estratégia implementada na M3

- `SegmentationService` mantém uma instância de `SAM2Segmenter`.
- O serviço, não o endpoint, é responsável pelo ciclo de vida do modelo.
- Um lock do serviço cobre a chamada completa a `infer()`.
- O modelo é carregado no startup/lifespan.
- `close()` é executado no shutdown.
- O endpoint nunca acessa diretamente o predictor oficial.
- O endpoint depende do serviço de aplicação e trata somente o contrato HTTP.

O serviço usa um `asyncio.Lock` que cobre integralmente
`await asyncio.to_thread(segmenter.infer, image, prompt)`. O wrapper continua
sem lock. Nesta fase a aplicação deve executar com exatamente um worker e
aceita uma inferência por vez.

## Contrato HTTP atual

O fluxo esperado é:

1. a camada HTTP aceita somente JPEG ou PNG estático e valida bytes,
   dimensões e pixels;
2. a imagem é decodificada e convertida explicitamente para `np.ndarray` RGB;
3. o prompt HTTP é convertido para `BoxPrompt` ou `PointsPrompt`;
4. o serviço adquire o lock e chama `SAM2Segmenter.infer()`;
5. `SegmentationResult.to_metadata_dict()` fornece metadados serializáveis;
6. a máscara booleana é codificada em PNG Base64, separada dos metadados.

`to_metadata_dict()` não inclui máscaras, logits, caminhos pessoais ou
conteúdo da imagem. Na rota stateless, imagem, máscara e prompt não são persistidos.
A rota de tentativas reutiliza o serviço e lock e persiste máscaras e prompts;
veja [persistência experimental](experiment_persistence.md).
O campo `selected_score` permanece uma estimativa interna de qualidade da
máscara produzida pelo SAM 2 e não representa confiança clínica, diagnóstico
ou probabilidade de câncer.

## Fora de escopo atual

- fila de inferência;
- múltiplas GPUs;
- múltiplos workers;
- RLE;
- autenticação;
- classificação LS;
- tracking em vídeo;
- fine-tuning.
