**Idioma:** [English](README.md) · Português
<!-- synced with README.md @ 6edd3d5 -->

# Frontend do CarcinoIndex

Shell de aplicação standalone em Angular 21 para o protótipo de pesquisa acadêmica.
Plataforma experimental de segmentação assistida de lesões em imagens
laparoscópicas; o contexto de região PCI e a avaliação clínica são fornecidos pelo
especialista. A configuração do experimento está implementada junto com o status
do sistema e o contexto do projeto. "Iniciar avaliação" fica disponível após um
health check bem-sucedido com o modelo carregado. A área de segmentação (F3)
oferece caixas delimitadoras guiadas pelo especialista e tentativas de
segmentação salvas. A avaliação clínica (F4) registra o LS fornecido pelo
especialista por meio de uma revisão em linha e da finalização persistida da
Evaluation.

## Apresentação e idioma

A interface inicia em **pt-BR**. Botões nativos PT-BR / EN no cabeçalho trocam o
idioma em memória, sem recarregar a página, sem rotas e sem armazenamento no
navegador. Os arquivos compartilhados `src/app/i18n/language.service.ts` e
`translations.ts` localizam o texto renderizado, estados, rótulos, validações,
erros e textos de acessibilidade, e atualizam o idioma, o título e a descrição do
documento. A formatação de percentuais segue a localidade escolhida. Mensagens de
erro conhecidas do backend são localizadas na exibição; mensagens não reconhecidas
usam um fallback seguro em português, enquanto o inglês mantém a mensagem do
servidor.

Identificadores digitados pelo usuário e dados da API permanecem intactos. Os
valores do enum de qualidade, o LS manual, a conversão da confiança, os IDs das
tentativas revisadas, as etapas de nova tentativa e as travas de exibição da
máscara/revisão mantêm seus contratos existentes. Trocar o idioma não recria o
fluxo nem a imagem da máscara. Os testes cobrem a troca durante a configuração, a
revisão da segmentação e a revisão da finalização, incluindo o payload exato
enviado.

Tipografia do sistema, uma paleta verde discreta, foco visível, cards de rádio
nativos, campos de configuração agrupados e painéis responsivos compõem a
apresentação acadêmica. O canvas preserva o mapeamento de coordenadas para a
imagem original e sua proporção. Nenhuma dependência de runtime, fonte remota,
telemetria ou armazenamento é adicionada.

## Configuração do experimento (Experiment Setup)

O App raiz alterna localmente entre a visão geral e o fluxo, sem router. Um único
`ExperimentWorkflowComponent` é dono do Reactive Form tipado, do carregamento das
regiões PCI, da pré-visualização local, das respostas do servidor, do progresso,
dos erros e da conclusão.

Informe os códigos pseudonimizados do caso experimental e do anotador
(obrigatórios, sem espaços nas pontas, até 128 caracteres), selecione um JPEG ou
PNG e escolha uma região PCI ou "Não foi possível determinar". Nenhuma opção vem
pré-selecionada; a escolha explícita de não determinado envia
`pci_region_id: null`. Os rótulos das regiões vêm de `GET /api/v1/pci/regions`;
respostas com falha ou vazias oferecem nova tentativa e bloqueiam o envio. O
backend continua sendo a autoridade sobre formato da imagem e limites de bytes e
dimensões.

O envio executa Case -> Image -> Evaluation usando os endpoints existentes do
backend:

1. `POST /api/v1/cases` cria o caso clínico.
2. `POST /api/v1/cases/{case_id}/images` envia o File selecionado como `image` multipart.
3. `POST /api/v1/images/{image_id}/evaluations` cria um rascunho com região e anotador.

As respostas bem-sucedidas ficam na memória do componente. A nova tentativa pula
as etapas concluídas: uma falha no upload reutiliza o caso; uma falha na avaliação
reutiliza o caso e a imagem. O código do caso é travado após a criação do caso, a
seleção da imagem é travada após o upload, e região/anotador continuam editáveis
até a criação da avaliação. Todos os campos e o envio duplicado ficam bloqueados
enquanto as requisições rodam. A conclusão exibe um resumo seguro e uma ação
habilitada "Área de segmentação", que passa localmente para a F3.

O campo visível "Código pseudonimizado do caso" usa o campo inalterado da API
`anonymous_patient_code`. Para o Experimento B planejado, ele identifica um caso
experimental, não um paciente; cada fotografia pode ser um novo caso, e nenhuma
relação de paciente é inferida entre imagens. Não informe nomes, números de
prontuário ou outros identificadores pessoais. Os códigos são digitados
manualmente e não precisam ser únicos.

Após a finalização clínica, o componente pai exibe "Nova avaliação".
`startNewEvaluation()` volta localmente à configuração, preservando o código do
anotador do registro finalizado como valor padrão editável, o idioma atual e as
regiões PCI carregadas. Ele limpa o código do caso, a seleção de região, o
arquivo/pré-visualização (revogando sua object URL), o caso/imagem/avaliação/revisão
atuais, o progresso e os erros, e reinicia/habilita o formulário. Sair da fase
clínica destrói o componente filho e seu estado de LS/confiança. A área de
segmentação anterior já havia sido destruída ao entrar nessa fase. A saúde do
modelo no app fica fora desse reset. Nenhuma requisição HTTP, recarga de regiões,
recarga da página ou armazenamento no navegador está envolvida. Os registros
persistidos anteriores permanecem inalterados. O próximo envio cria um novo
ClinicalCase, envia uma nova Image e cria uma nova Evaluation; nenhum ID de
recurso ou estado de tentativa anterior é reutilizado.

A pré-visualização local usa uma object URL, nunca base64. Os nomes originais dos
arquivos não são exibidos. Substituir uma imagem revoga a URL anterior. O File
selecionado e a URL ativa ficam em memória até a entrada na F3, quando o File é
liberado e a URL da pré-visualização é revogada. A URL também é revogada quando o
componente é destruído. A F3 não depende do File nem da pré-visualização da
configuração.

## Área de segmentação (F3)

`SegmentationWorkspaceComponent` recebe apenas o `evaluation_id` persistido. Ele
recupera `GET /api/v1/evaluations/{evaluation_id}`, confere se a Evaluation está
em rascunho e então recupera `GET /api/v1/images/{image_id}/content` usando o ID
de imagem persistido. Avaliações finalizadas bloqueiam a segmentação. A
recuperação da imagem usa um Blob, valida o content type JPEG/PNG e cria uma
object URL pertencente à área de segmentação. Substituição e destruição revogam
essa URL; requisições pendentes são canceladas na destruição. O carregamento da
Evaluation e o da imagem têm mensagens de status separadas. A nova tentativa
reutiliza uma Evaluation já recuperada quando só a recuperação da imagem falhou.

O serviço de API também decodifica envelopes de erro JSON recebidos como Blob, de
modo que as mensagens seguras do backend continuam disponíveis. Erros malformados
usam um fallback seguro; corpos binários brutos e detalhes de exceção nunca são
exibidos.

`SegmentationCanvasComponent` é dono da imagem, da interação com o ponteiro, da
geometria e das sobreposições, sem chamadas HTTP. A imagem mantém sua proporção
natural; a camada SVG de interação e a máscara ocupam exatamente o retângulo
renderizado. As coordenadas do ponteiro são convertidas com
`(clientX - rect.left) * naturalWidth / rect.width` e a fórmula equivalente em Y.
Os limites são medidos a cada interação, de modo que o redimensionamento
responsivo preserva as coordenadas armazenadas na imagem original. Arrastos
invertidos são normalizados, as coordenadas são limitadas às bordas da imagem e
caixas com largura ou altura menor que quatro pixels exibidos são rejeitadas. A
captura do ponteiro permite arrastar além da imagem; o cancelamento limpa um
prompt não concluído. "Limpar caixa delimitadora" remove o prompt.

Desenhar a caixa atualmente exige um dispositivo apontador (mouse, caneta ou
toque); não há equivalente por teclado. As ações ao redor são botões nativos com
foco visível, instruções em texto, anúncios de status e erros acessíveis.

"Executar segmentação" envia um FormData multipart para
`POST /api/v1/evaluations/{evaluation_id}/segmentations` com exatamente:

- `prompt_type`: `box`
- `box`: JSON `[xMin, yMin, xMax, yMax]` em pixels da imagem original
- `multimask_output`: `true`

Nenhuma imagem, região, ponto, rótulo ou campo clínico é enviado. O navegador
fornece o boundary do multipart. A inferência não tem timeout curto; o desenho e
o envio duplicado ficam bloqueados enquanto o SAM processa o prompt. Uma falha
preserva a caixa para nova tentativa. Os números das tentativas vêm da resposta
persistida do POST.

A máscara PNG mais recente é sobreposta à imagem original com transparência e
blending screen: o fundo preto deixa a imagem visível, enquanto os pixels brancos
da máscara destacam o objeto indicado. As dimensões declaradas da máscara devem
coincidir com as dimensões naturais da imagem; divergências exibem um erro em vez
de uma sobreposição alinhada. Falhas de decodificação da imagem também são
reportadas. Iniciar outro prompt limpa o resultado antigo visível. Várias
tentativas podem ser criadas durante a sessão atual da área de segmentação; só o
resultado mais recente é exibido. As tentativas anteriores continuam persistidas
no backend. Os scores do SAM não são exibidos como confiança clínica.

Não há prompts de pontos, zoom/pan, recuperação de histórico, comparações,
edição de máscara nem semântica de aceite/referência/ground truth de máscara.
Após uma tentativa persistida bem-sucedida, aparecem exatamente três opções de
rádio nativas: Adequada, Parcialmente adequada e Inadequada, sem padrão. Elas
classificam apenas a qualidade visual/espacial da segmentação, não o LS, o
diagnóstico nem a confiança do SAM. Continuar exige uma categoria selecionada,
uma tentativa atual bem-sucedida e nenhuma inferência ativa. A ação emite
`reviewed_attempt_id` e `segmentation_quality` do resultado exibido. Preparar uma
nova caixa ou executar a segmentação de novo limpa o resultado e a qualidade,
inclusive quando uma nova tentativa falha. Sair da F3 destrói a área de
segmentação e libera a object URL da imagem persistida. Não há router, retomada
por URL, persistência no navegador nem nova dependência de runtime.

Recarregar ou sair da página perde o estado do fluxo. Nenhuma persistência no
navegador é usada. Os registros já criados no servidor permanecem no backend. A
nova tentativa só evita repetir etapas cujas respostas bem-sucedidas foram
recebidas; uma resposta perdida após um commit no servidor não pode ser
deduplicada sem idempotência no backend, o que está fora desta iteração.

## Avaliação clínica (F4)

`ExperimentWorkflowComponent` é dono das fases locais `setup`, `segmentation` e
`clinical` e mantém a revisão da segmentação em memória.
`ClinicalAssessmentComponent` recebe essa revisão e o ID da Evaluation persistida
e então relê `GET /api/v1/evaluations/{evaluation_id}`. O registro recuperado é a
fonte da verdade para o status e o ID da região PCI; a resposta da configuração
não é usada como registro clínico. Uma Evaluation já finalizada renderiza
imediatamente um resumo somente leitura e emite a resposta persistida ao
componente pai, sem enviar de novo.

Para um rascunho, um Reactive Form tipado oferece cinco opções de rádio nativas,
LS 0 a LS 3 e "Não foi possível determinar", sem padrão. Uma escolha explícita é
obrigatória. A opção não determinado envia `clinical_ls: null` e
`annotator_confidence: null`. O LS clínico e a região PCI são fornecidos
manualmente pelo especialista quando determináveis; nenhum deles é inferido pelo
SAM. O LS clínico é atribuído segundo o protocolo do estudo. Ainda não há
descrições de limiares de tamanho da lesão embutidas. Nenhuma área de máscara,
geometria da caixa delimitadora ou metadado do SAM é usado para inferir o LS.

A confiança do anotador é opcional e começa vazia e desabilitada até que um LS
0–3 seja selecionado. Limpar o LS ou selecionar não determinado limpa e desabilita
a confiança; selecionar um LS de novo habilita o campo vazio. O campo numérico
aceita 0–100%. Na revisão, o percentual é dividido por 100 para o contrato 0–1 do
backend (73% vira 0.73, 0% vira 0 e 100% vira 1); vazio vira `null`. Essa é a
confiança do especialista na avaliação do LS clínico, não um score do SAM nem a
qualidade da segmentação.

"Revisar avaliação" captura um snapshot imutável da requisição e exibe a
qualidade da segmentação separada do LS, da confiança e do ID da região
persistida, antes de qualquer POST. "Voltar à edição" mantém os valores do
formulário. A revisão avisa que a finalização é irreversível neste protótipo.
"Finalizar avaliação" envia explicitamente um JSON para
`POST /api/v1/evaluations/{evaluation_id}/finalize` apenas com `clinical_ls`,
`annotator_confidence`, `reviewed_attempt_id` e `segmentation_quality`. O UUID da
tentativa não é exibido. A qualidade é contexto vindo da F3, não uma segunda
escolha na F4. Não há timeout curto de finalização. O envio duplicado e a volta à
edição ficam bloqueados enquanto a finalização roda, e as requisições são
canceladas na destruição do componente.

Erros na recuperação inicial oferecem "Tentar novamente". Erros de finalização
preservam o snapshot da revisão e mostram mensagens seguras do backend, com ações
explícitas de nova tentativa e "Atualizar estado da avaliação". Uma requisição
pode ser confirmada no backend mesmo se a resposta se perder; atualizar faz outro
GET. Uma resposta finalizada substitui a revisão pelo resumo persistido; uma
resposta em rascunho mantém a mesma revisão disponível para nova tentativa.
Atualizações que falham também preservam o snapshot. Não há nova tentativa
automática, polling nem idempotência no frontend.

O resumo final exibe a qualidade de segmentação persistida ("Não registrada" para
registros legados), o LS, o percentual de confiança ou "Não informada", o ID da
região e o status "Finalizada", sem controles editáveis. Região/LS não
determinados usam rótulos traduzidos em vez de null bruto; confiança sem LS mostra
"Não informada". Tanto a finalização bem-sucedida quanto o carregamento de um
registro já finalizado emitem a Evaluation persistida ao componente pai, que
marca a etapa clínica como "Concluída". Apenas esta Evaluation é finalizada: a
revisão qualitativa não aceita nem valida uma máscara como referência ou ground
truth e não significa um escore PCI completo de 13 regiões. A composição completa
do PCI continua fora do escopo.

As opções de LS usam fieldset e legend com rótulos visíveis; a confiança tem
rótulo e texto de ajuda. As mensagens de validação estão associadas aos seus
controles. O progresso assíncrono usa semântica de status, as falhas usam alertas
e os botões nativos mantêm o foco visível. Formulário e contexto se empilham em
telas menores usando CSS simples.

## Pré-requisitos e instalação

- Node.js 24 LTS com npm (o workspace declara Node 24 em `engines`).
- O backend FastAPI rodando separadamente para as informações de saúde ao vivo;
  veja a [configuração do backend](../backend/README.pt-BR.md). A disponibilidade
  do backend não é necessária para testes nem builds.

Execute a partir de `frontend/`:

```sh
npm ci
```

Use `npm install` ao alterar dependências de propósito e versione o
`package-lock.json` atualizado. Todas as dependências do frontend pertencem a
este workspace. No Windows com uma política de execução do PowerShell
restritiva, use `npm.cmd`.

## Desenvolvimento

```sh
npm start
```

Abra `http://localhost:4200`. O proxy de desenvolvimento em `proxy.conf.json`
encaminha `/health` e `/api/**` (incluindo caminhos aninhados da API) para
`http://127.0.0.1:8000`. O código da aplicação usa URLs relativas. Reinicie o
servidor de desenvolvimento após alterar o proxy. Inicie o backend
separadamente; `scripts/dev.ps1` não gerencia processos do frontend.

O health check inicial tem os estados carregando, sucesso e indisponível, um
timeout de dez segundos e atualização/nova tentativa manual. Backend pronto é
diferente de modelo carregado. A interface exibe como texto o nome do modelo, o
device e a precisão retornados; o identificador conhecido `sam2.1_hiera_small`
recebe um rótulo legível. São indicadores técnicos de disponibilidade, não
evidência de validação clínica.

## Testes e build de produção

```sh
npm test
npm run test:ci
npm run build
```

`npm test` executa o Vitest do Angular em modo watch. `test:ci` executa uma vez,
headless em jsdom, usando Angular TestBed e HttpTestingController; não é
necessário instalar navegador nem ter a API no ar. Os testes cobrem renderização,
transições de saúde, modelos não carregados, nova tentativa, requisições
relativas, erros da API, timeout, renderização segura de texto e limpeza de
requisições. Os testes do fluxo cobrem ainda validação, rótulos PCI do backend,
pré-visualizações e limpeza de URLs, requisições do ciclo de vida em ordem, novas
tentativas parciais, travamento progressivo e envio duplicado. Os testes da F3
cobrem conteúdo binário/tratamento de erros, campos multipart exatos, geometria
do ponteiro e redimensionamento, cancelamento, carregamento persistido, bloqueio
em estado finalizado, alinhamento da máscara, múltiplas tentativas, novas
tentativas após falha, transição do fluxo e limpeza de object URLs. Os testes da
F4 cobrem recuperação persistida, validação manual do LS, conversão da confiança,
snapshots da revisão, finalização com JSON exato, prevenção de duplicidade, erros
seguros, recuperação de respostas incertas, resumos somente leitura,
sincronização com o componente pai e cancelamento de requisições. Os testes
existentes da F2/F3 continuam; nenhum backend ao vivo nem SAM é necessário.

Os assets de produção são gravados em `dist/carcinoindex/browser/`. O proxy de
desenvolvimento não faz parte desse build. A hospedagem em produção deve rotear
`/health` e `/api/` para o FastAPI na mesma origem. O deploy está fora desta
iteração.

## Estrutura

```text
src/app/
  api/
    api.models.ts
    experiment-api.service.ts
    experiment-api.service.spec.ts
  experiment/
    experiment-workflow.component.ts / .html / .css / .spec.ts
    clinical-assessment/
      clinical-assessment.component.ts / .html / .css / .spec.ts
    segmentation-workspace/
      segmentation-workspace.component.ts / .html / .css / .spec.ts
      segmentation-canvas/
        segmentation-canvas.component.ts / .html / .css / .spec.ts
  i18n/
    language.service.ts
    language.service.spec.ts
    translations.ts
  app.component.ts / .html / .css / .spec.ts
  app.config.ts
```

O componente raiz é dono de um estado discriminado em signals e cancela as
inscrições na destruição. O serviço de API usa HttpClient e trata localmente o
envelope `{ error: { code, message } }` do backend. Não há rotas nem pastas de
funcionalidades futuras sem uso. O CSS global contém uma pequena paleta e estilos
de base; o layout pertence ao shell.

Dependências de runtime: Angular common/core/compiler/platform-browser/forms, RxJS
e tslib. Dependências de desenvolvimento: Angular CLI/build/compiler-cli,
TypeScript, Vitest e jsdom. Pacotes de roteamento, bibliotecas de UI e frameworks
de gerenciamento de estado não estão instalados. Nenhum asset externo, analytics,
telemetria, armazenamento no navegador ou identificador direto de paciente é
introduzido. Apenas códigos pseudonimizados são coletados. O analytics do Angular
CLI está explicitamente desabilitado em `angular.json`.

O workflow dedicado `.github/workflows/frontend.yml` instala com `npm ci`, roda os
testes unitários e faz o build com Node 24. O workflow de CI do backend continua
independente.
