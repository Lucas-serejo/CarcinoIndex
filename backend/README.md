# Módulo Backend & AI Pipeline — CarcinoIndex

Este módulo contém a API mínima (FastAPI) e a estrutura modular de processamento de Inteligência Artificial para validação experimental do **CarcinoIndex**.

Conforme as diretrizes de desenvolvimento do projeto, evitamos abstrações prematuras. A API atualmente expõe unicamente uma rota de verificação de integridade (`GET /health`), e os serviços da pipeline estão estruturados de forma limpa para desacoplar a pesquisa científica do código de produção.

---

## 📦 Estrutura de Subpacotes

- **`app/`**: Aplicação FastAPI.
  - `api/`: Definição de rotas (apenas `/health` no momento).
  - `core/`: Configurações centrais do sistema (ex: caminhos relativos).
  - `schemas/`: Modelos de validação de dados via Pydantic.
  - `services/`: Orquestradores da lógica de negócios (contém `pipeline_service.py` como esqueleto/stub arquitetural).
  - `main.py`: Ponto de inicialização do servidor Uvicorn.

- **`ai/`**: Implementações de algoritmos de Visão Computacional e Aprendizado de Máquina.
  - `segmentation/`: Integração com o Segment Anything Model (SAM).
  - `feature_extraction/`: Funções puras para extração de propriedades de máscaras (área, bounding box).
  - `classification/`: Placeholders para o futuro modelo preditivo dos scores LS (Sugarbaker).
  - `utils/`: Utilitários de leitura/escrita de imagens usando OpenCV e Pillow.

---

## 🛠️ Execução Local

### 1. Ativação do Ambiente Virtual
Certifique-se de ter criado e ativado o ambiente Python na pasta `backend/`:
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### 2. Inicialização do Servidor de Desenvolvimento
```bash
uvicorn app.main:app --reload
```
Acesse `http://localhost:8000/health` para validar se o backend está ativo.
