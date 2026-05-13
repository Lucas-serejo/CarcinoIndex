# CarcinoIndex

**CarcinoIndex** é um projeto de pesquisa acadêmica (TCC) focado no suporte à decisão médica durante cirurgias laparoscópicas para avaliação da **Carcinomatose Peritoneal**, seguindo o protocolo de estadiamento de **Sugarbaker** (Índice de Carcinomatose Peritoneal - PCI).

O objetivo principal do sistema é auxiliar na classificação automática dos scores de lesão (**LS1, LS2, LS3**) em imagens laparoscópicas monoculares. 

---

## 🔬 Contexto e Hipótese Científica

Imagens laparoscópicas monoculares possuem uma limitação intrínseca de **ambiguidade de escala** (não é possível extrair medidas absolutas em centímetros com precisão sem referências físicas conhecidas). Portanto, o projeto adota uma abordagem de aprendizado de padrões visuais e geométricos relativos em vez de metrificação absoluta direta.

A estratégia e fluxo experimental do projeto consistem em:
1. **Modelos Fundacionais de Visão**: Utilizar o **SAM (Segment Anything Model)** para segmentação e geração de máscaras das regiões suspeitas.
2. **Extração de Características**: Obter propriedades geométricas (área da máscara, proporções da *bounding box*) e, futuramente, profundidade relativa como *features* auxiliares.
3. **Classificação Supervisionada**: Mapear as *features* extraídas para os scores clínicos de lesão (LS1, LS2, LS3) utilizando algoritmos de aprendizado supervisionado (ex: XGBoost, scikit-learn).
4. **Redução da Subjetividade**: Apoiar o especialista médico na consistência da avaliação do PCI, atuando como ferramenta de segunda opinião.

### 🎯 Hipótese Primária Atual
> *"O Segment Anything Model (SAM) consegue representar adequadamente as lesões peritoniais em imagens laparoscópicas, fornecendo máscaras consistentes para extração de features geométricas?"*

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
│   ├── sam_validation.ipynb  # Validação qualitativa da segmentação com SAM
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
Abra o arquivo `notebooks/sam_validation.ipynb` para iniciar os testes qualitativos com o SAM.

---

## ⚠️ Limitações e Escopo Atual
- **Sem Frontend / Autenticação**: O foco atual é exclusivamente validação científica e backend modular.
- **Classificação LS em Prototipação**: O módulo de classificação possui apenas interfaces e stubs aguardando a consolidação do dataset de lesões.