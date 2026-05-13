import numpy as np
from typing import Any, Dict, List, Optional

class SAMSegmenterStub:
    """
    Interface/Wrapper para carregamento e execução do Segment Anything Model (SAM).

    Esta classe encapsula a inicialização do modelo e os métodos para inferência de máscaras.
    A implementação base atual visa facilitar a experimentação isolada nos notebooks e 
    suportar o carregamento lazy dos pesos na pipeline principal.
    """

    def __init__(self, model_type: str = "vit_h", checkpoint_path: Optional[str] = None):
        """
        Inicializa o wrapper do SAM.

        Args:
            model_type: Arquitetura do backbone (ex: 'vit_h', 'vit_l', 'vit_b').
            checkpoint_path: Caminho para os pesos pré-treinados do modelo.
        """
        self.model_type = model_type
        self.checkpoint_path = checkpoint_path
        self.predictor: Optional[Any] = None
        self.is_loaded: bool = False

    def load_model(self, device: str = "cuda") -> None:
        """
        Carrega o modelo na memória/GPU sob demanda (lazy loading).
        
        A lógica real de `sam_model_registry` e `SamPredictor` será invocada aqui
        durante os experimentos práticos.
        """
        # Exemplo de código futuro:
        # from segment_anything import sam_model_registry, SamPredictor
        # sam = sam_model_registry[self.model_type](checkpoint=self.checkpoint_path)
        # sam.to(device=device)
        # self.predictor = SamPredictor(sam)
        self.is_loaded = True
        print(f"SAM ({self.model_type}) inicializado em modo de prototipação no dispositivo: {device}")

    def generate_masks(self, image: np.ndarray, prompts: Optional[Dict[str, Any]] = None) -> List[np.ndarray]:
        """
        Gera máscaras de segmentação para uma imagem de entrada.

        Args:
            image: Imagem de entrada em formato NumPy array (RGB).
            prompts: Dicionário opcional contendo bounding boxes ou pontos (point_coords/point_labels)
                     para segmentação guiada.

        Returns:
            Lista de máscaras binárias (NumPy arrays) correspondentes às lesões/regiões detectadas.
        """
        if not self.is_loaded:
            raise RuntimeError("O modelo SAM não foi carregado. Chame load_model() primeiramente.")

        # Retorna uma máscara de exemplo vazia/simulada para validação da interface
        height, width = image.shape[:2]
        dummy_mask = np.zeros((height, width), dtype=bool)
        return [dummy_mask]
