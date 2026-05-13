import cv2
import numpy as np
from PIL import Image
from typing import Optional

def load_image_rgb(file_path: str) -> np.ndarray:
    """
    Carrega uma imagem a partir do disco e garante que ela esteja no espaço de cores RGB.

    O carregamento nativo do OpenCV utiliza BGR, enquanto o SAM e a maioria dos
    modelos em PyTorch/PIL esperam o formato RGB.

    Args:
        file_path: Caminho completo ou relativo para o arquivo de imagem.

    Returns:
        NumPy array tridimensional representando a imagem RGB.
    """
    # Utiliza PIL para evitar problemas com caminhos ou formatos exóticos que falham no cv2
    try:
        pil_img = Image.open(file_path).convert("RGB")
        return np.array(pil_img)
    except Exception as e:
        # Fallback para OpenCV caso necessário
        img_bgr = cv2.imread(file_path)
        if img_bgr is None:
            raise FileNotFoundError(f"Não foi possível carregar a imagem no caminho: {file_path}")
        return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

def save_mask_as_image(mask: np.ndarray, output_path: str, color_overlay: Optional[tuple] = None) -> None:
    """
    Salva uma máscara binária (ou com overlay) como imagem PNG/JPEG.

    Args:
        mask: NumPy array 2D binário ou booleano.
        output_path: Destino onde o arquivo será gravado.
        color_overlay: Tupla RGB opcional para gerar uma máscara colorida.
    """
    if color_overlay:
        # Cria uma imagem RGB preta e preenche a região da máscara com a cor desejada
        h, w = mask.shape[:2]
        colored_mask = np.zeros((h, w, 3), dtype=np.uint8)
        colored_mask[mask > 0] = color_overlay
        img_to_save = Image.fromarray(colored_mask)
    else:
        # Converte máscara booleana para escala de cinza (0/255)
        mask_uint8 = (mask > 0).astype(np.uint8) * 255
        img_to_save = Image.fromarray(mask_uint8)

    img_to_save.save(output_path)
