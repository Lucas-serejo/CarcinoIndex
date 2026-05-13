import numpy as np
from typing import Dict, Any

def extract_mask_area(mask: np.ndarray) -> int:
    """
    Calcula a área em pixels da região segmentada (máscara binária).

    Como as imagens laparoscópicas não possuem escala absoluta definida, a área em pixels
    representa a extensão relativa da lesão no campo de visão atual.

    Args:
        mask: NumPy array 2D representando a máscara binária (valores booleanos ou 0/1).

    Returns:
        Número total de pixels pertencentes à máscara.
    """
    return int(np.sum(mask > 0))

def extract_bounding_box_properties(mask: np.ndarray) -> Dict[str, Any]:
    """
    Extrai as coordenadas e proporções da bounding box que circunscreve a lesão.

    As proporções (aspect ratio) e a ocupação relativa (extent) servem como features
    geométricas invariantes à escala absoluta.

    Args:
        mask: NumPy array 2D representando a máscara binária.

    Returns:
        Dicionário contendo bounding box (x_min, y_min, x_max, y_max), largura, altura,
        e aspect ratio.
    """
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    
    if not np.any(rows) or not np.any(cols):
        # Retorna valores zerados se a máscara for completamente vazia
        return {
            "bbox": (0, 0, 0, 0),
            "width": 0,
            "height": 0,
            "aspect_ratio": 0.0
        }

    y_min, y_max = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
    x_min, x_max = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])

    width = x_max - x_min + 1
    height = y_max - y_min + 1
    aspect_ratio = float(width) / float(height) if height > 0 else 0.0

    return {
        "bbox": (x_min, y_min, x_max, y_max),
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio
    }
