# Contrato de inferência do SAM 2.1 para a M3

Este documento descreve o limite entre o módulo de IA validado até a M2.5 e
uma futura integração de aplicação. Ele não implementa FastAPI.

## Instância do modelo

O SAM 2.1 Hiera Small é caro para carregar. A aplicação deverá criar uma
única instância de `SAM2Segmenter` no lifespan, chamar `load()` uma vez no
startup e reutilizar o modelo entre inferências. No shutdown, deverá chamar
`close()`.

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

## Estratégia recomendada para M3

- Um serviço de aplicação mantém uma instância de `SAM2Segmenter`.
- O serviço, não o endpoint, é responsável pelo ciclo de vida do modelo.
- Um lock do serviço cobre a chamada completa a `infer()`.
- O modelo é carregado no startup/lifespan.
- `close()` é executado no shutdown.
- O endpoint nunca acessa diretamente o predictor oficial.
- O endpoint depende do serviço de aplicação e trata somente o contrato HTTP.

O tipo de lock, o comportamento com múltiplos workers e o limite de espera
devem ser decididos na M3; nenhum lock foi adicionado ao wrapper.

## Contrato futuro

O fluxo esperado é:

1. a camada HTTP valida formato, tamanho e limites do payload;
2. a imagem é decodificada e convertida explicitamente para `np.ndarray` RGB;
3. o prompt HTTP é convertido para `BoxPrompt` ou `PointsPrompt`;
4. o serviço adquire o lock e chama `SAM2Segmenter.infer()`;
5. `SegmentationResult.to_metadata_dict()` fornece metadados serializáveis;
6. a máscara booleana é tratada separadamente dos metadados.

`to_metadata_dict()` não inclui máscaras, logits, caminhos pessoais ou
conteúdo da imagem. A codificação futura da máscara ainda precisa ser
decidida.

## Fora de escopo atual

- fila de inferência;
- múltiplas GPUs;
- múltiplos workers;
- armazenamento permanente;
- RLE, PNG ou Base64 no contrato HTTP;
- autenticação;
- classificação LS;
- tracking em vídeo;
- fine-tuning.
