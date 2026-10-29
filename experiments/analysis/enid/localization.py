"""Visible figure text only; scientific values and layout are never localized."""

from matplotlib.text import Text

LANGUAGES = ("en", "pt-BR")
PT_BR = {
    "Annotation-level Dice distribution": "Distribuição de Dice por anotação",
    "Annotation-level IoU distribution": "Distribuição de IoU por anotação",
    "Annotation count": "Número de anotações",
    "Median": "Mediana",
    "Annotation-level exploratory association": "Associação exploratória por anotação",
    "SAM selected score": "Escore selecionado pelo SAM",
    "Reference-mask area (pixels; log scale)": "Área da máscara de referência (pixels; escala logarítmica)",
    "Pearson (raw area)": "Pearson (área original)",
    "undefined": "indefinido",
    "A. Original + reference bbox": "A. Imagem original + caixa delimitadora de referência",
    "B. ENID reference segmentation": "B. Segmentação de referência do ENID",
    "C. SAM selected mask": "C. Máscara selecionada pelo SAM",
    "D. Mask agreement / disagreement": "D. Concordância / discordância das máscaras",
    "Both": "Interseção",
    "Reference only": "Apenas referência",
    "SAM only": "Apenas SAM",
    "ENID annotation": "Anotação ENID",
    "Benchmark Dice": "Dice do benchmark",
}


def validate_language(language):
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported rendering language: {language}")


def localize_figure(figure, language):
    validate_language(language)
    if language == "en":
        return
    # Solve the original English layout at the export DPI before changing text.
    # Otherwise constrained_layout may move/resize panels for translated labels.
    figure.set_dpi(180)
    figure.canvas.draw()
    figure.set_layout_engine("none")
    for artist in figure.findobj(match=Text):
        value = artist.get_text()
        for source, target in PT_BR.items():
            value = value.replace(source, target)
        artist.set_text(value)
