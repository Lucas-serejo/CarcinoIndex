# CarcinoIndex

**CarcinoIndex** é um projeto de pesquisa acadêmica (TCC) focado no suporte à decisão médica durante cirurgias laparoscópicas para avaliação da **Carcinomatose Peritoneal**, seguindo o protocolo de estadiamento de **Sugarbaker** (Índice de Carcinomatose Peritoneal - PCI).

O objetivo principal do sistema é auxiliar na classificação automática dos scores de lesão (**LS1, LS2, LS3**) em imagens laparoscópicas monoculares. 

---

## 🔬 Contexto e Hipótese Científica

Imagens laparoscópicas monoculares possuem uma limitação intrínseca de **ambiguidade de escala** (não é possível extrair medidas absolutas em centímetros com precisão sem referências físicas conhecidas). Portanto, o projeto adota uma abordagem de aprendizado de padrões visuais e geométricos relativos em vez de metrificação absoluta direta.

A estratégia e fluxo experimental do projeto consistem em:
1. **Modelos Fundacionais de Visão**: Utilizar o **SAM 2.1 Hiera Small** para segmentação guiada por bounding box ou pontos positivos e negativos.
2. **Extração de Características**: Obter propriedades geométricas (área da máscara, proporções da *bounding box*) e, futuramente, profundidade relativa como *features* auxiliares.
3. **Classificação Supervisionada**: Mapear as *features* extraídas para os scores clínicos de lesão (LS1, LS2, LS3) utilizando algoritmos de aprendizado supervisionado (ex: XGBoost, scikit-learn).
4. **Redução da Subjetividade**: Apoiar o especialista médico na consistência da avaliação do PCI, atuando como ferramenta de segunda opinião.

### 🎯 Hipótese Primária Atual
> *"O SAM 2.1 consegue representar adequadamente as lesões peritoniais em imagens laparoscópicas, fornecendo máscaras consistentes para extração de features geométricas?"*

---

## 📂 Estrutura do Projeto

A arquitetura do projeto foi desenhada para priorizar clareza, modularidade e facilidade de experimentação científica:

```text
CarcinoIndex/
│
├── backend/                  # API mínima e pipeline modular de IA
│   ├── app/                  # Aplicação FastAPI (Health check)
│   ├── ai/                   # Módulos de Segmentação, Features e Classificação
│   └── requirements.txt      # Dependências do projeto
│
├── datasets/                 # Organização dos dados experimentais
│   ├── raw/                  # Imagens originais brutas
│   ├── processed/            # Imagens pré-processadas
│   ├── masks/                # Máscaras geradas pelo SAM
│   ├── metadata/             # Metadados e anotações clínicas
│   └── samples/              # Amostras isoladas para depuração e testes rápidos
│
├── notebooks/                # Roteiros experimentais em Jupyter Notebook
│   ├── sam_validation.ipynb  # Validação sintética do wrapper SAM 2.1
│   ├── feature_extraction.ipynb
│   └── classification_tests.ipynb
│
├── experiments/              # Rastreamento de experimentos e modelos
│   ├── outputs/              # Saídas visuais e resultados de testes
│   ├── logs/                 # Logs de execução
│   ├── checkpoints/          # Pesos intermediários de modelos
│   └── models/               # Modelos finais validados
│
└── docs/                     # Metodologia, referências e diagramas
```

---

## 🚀 Como Começar (Ambiente de Pesquisa)

### 1. Pré-requisitos
- Python 3.10+ recomendado.
- Conhecimento básico em execução de notebooks Jupyter.

### 2. Configuração do Ambiente Virtual
Navegue até o diretório `backend/` e instale as dependências listadas:

```bash
cd backend
python -m venv venv

# Ativação no Windows:
venv\Scripts\activate

# Instalação dos pacotes:
pip install -r requirements.txt
```

### 3. Execução da API Mínima (Health Check)
Para verificar se a stack base está operando corretamente:
```bash
uvicorn app.main:app --reload
```
Acesse `http://localhost:8000/health` no navegador para confirmar a disponibilidade.

### 4. Pesquisa e Experimentação
Inicie o servidor Jupyter na raiz do projeto para explorar os notebooks:
```bash
jupyter notebook
```
Abra o arquivo `notebooks/sam_validation.ipynb` para validar o wrapper SAM 2.1
com uma imagem sintética.

### SAM 2.1 Hiera Small

O wrapper `SAM2Segmenter` usa o clone oficial
`https://github.com/facebookresearch/sam2.git` instalado em modo editável.
O checkpoint `sam2.1_hiera_small.pt` deve permanecer fora deste repositório;
o notebook apenas recebe seu caminho e nunca faz download automático.

No Windows validado, a extensão CUDA opcional foi desativada. A máscara
selecionada é a de maior score previsto pelo modelo, mas esse score não
representa confiança clínica. Máscaras automáticas também não constituem
*ground truth*. Imagens clínicas e checkpoints não devem ser versionados.

Para validar uma imagem local não clínica com box e pontos, use
`scripts/run_sam2_real_image.py`. O contrato de estado e concorrência para
a API está em `docs/architecture/sam2_inference_contract.md`.

### API experimental M3

A API aceita segmentação assistida por box ou pontos, exige seleção manual da
região PCI e permite LS manual opcional. O PCI é composto com o maior LS
informado em cada uma das 13 regiões; enquanto houver região pendente, há
somente subtotal e `pci_total` permanece nulo. O SAM não classifica lesões e
área em pixels não é convertida em centímetros.

Os comandos de configuração e execução com um único worker estão em
`backend/README.md`. Não há persistência, frontend ou diagnóstico autônomo.

---

## ⚠️ Limitações e Escopo Atual
- **Sem Frontend / Autenticação**: O foco atual é exclusivamente validação científica e backend modular.
- **Classificação LS em Prototipação**: O módulo de classificação possui apenas interfaces e stubs aguardando a consolidação do dataset de lesões.
