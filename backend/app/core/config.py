import os
from pathlib import Path

# Caminho raiz do projeto (CarcinoIndex/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent

# Subdiretórios principais
DATASETS_DIR = ROOT_DIR / "datasets"
EXPERIMENTS_DIR = ROOT_DIR / "experiments"

class Settings:
    PROJECT_NAME: str = "CarcinoIndex"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

settings = Settings()
