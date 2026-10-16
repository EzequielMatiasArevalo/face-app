from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
import onnxruntime
from PIL import Image

from lib.schemas import AIDetection

logger = logging.getLogger(__name__)

# Marcas de procedencia que declaran contenido generado o editado con IA (en minúsculas: la
# búsqueda no distingue mayúsculas). Si una imagen las trae, no hace falta correr el modelo.
_METADATA_MARKERS: tuple[tuple[bytes, str], ...] = (
    # IPTC DigitalSourceType, en XMP o dentro de un manifiesto C2PA (ChatGPT, Firefly, Imagen, Photoshop, ...)
    (b"compositewithtrainedalgorithmicmedia", "metadatos IPTC/C2PA: editada con IA (compositeWithTrainedAlgorithmicMedia)"),
    (b"trainedalgorithmicmedia", "metadatos IPTC/C2PA: generada con IA (trainedAlgorithmicMedia)"),
    # Parámetros que Stable Diffusion WebUI y ComfyUI guardan en los chunks de texto del PNG
    (b"negative prompt:", "metadatos de Stable Diffusion (prompt)"),
    (b"cfg scale: ", "metadatos de Stable Diffusion (parámetros de generación)"),
    (b'"class_type"', "metadatos de ComfyUI (workflow)"),
)

# Preprocesamiento del modelo (CLIPImageProcessor de su model card)
_RESIZE_SHORTEST_EDGE = 440
_CROP_SIZE = 384
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


class AIImageDetector:
    """
    Decide si una imagen fue generada o alterada con IA: primero por metadatos de procedencia
    (concluyentes cuando están) y, si no hay, con el clasificador Community Forensics
    (ViT-S/16 384, CVPR 2025) exportado a ONNX, que devuelve un logit por imagen.
    """

    def __init__(self, model_path: Path, threshold: float) -> None:
        if not Path(model_path).exists():
            raise ValueError(f"AI detector model path does not exist: {model_path}")
        self.threshold = threshold
        self.session = onnxruntime.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    @staticmethod
    def metadata_evidence(data: bytes) -> str | None:
        lowered = data.lower()
        for marker, evidence in _METADATA_MARKERS:
            if marker in lowered:
                return evidence
        return None

    def score(self, image: Image.Image) -> float:
        """Probabilidad (0-1) de que la imagen sea generada con IA según el modelo."""
        rgb = image.convert("RGB")
        scale = _RESIZE_SHORTEST_EDGE / min(rgb.size)
        width, height = (max(_CROP_SIZE, round(side * scale)) for side in rgb.size)
        rgb = rgb.resize((width, height), Image.Resampling.BICUBIC)
        left, top = (width - _CROP_SIZE) // 2, (height - _CROP_SIZE) // 2
        crop = rgb.crop((left, top, left + _CROP_SIZE, top + _CROP_SIZE))
        pixels = (np.asarray(crop, dtype=np.float32) / 255.0 - _MEAN) / _STD
        logit = self.session.run(None, {self.input_name: pixels.transpose(2, 0, 1)[None]})[0][0][0]
        return float(1.0 / (1.0 + np.exp(-logit)))

    def check(self, data: bytes) -> AIDetection:
        evidence = self.metadata_evidence(data)
        if evidence:
            return AIDetection(is_ai_generated=True, method="metadata", score=None, evidence=evidence)
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except OSError as exc:
            raise ValueError("Could not read image") from exc
        score = self.score(image)
        return AIDetection(
            is_ai_generated=score >= self.threshold,
            method="model",
            score=round(score, 4),
            evidence=f"modelo: probabilidad de IA {score:.2f}, umbral {self.threshold:g}",
        )
