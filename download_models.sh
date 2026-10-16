#!/usr/bin/env bash
# Descarga los modelos de InsightFace (pack antelopev2) a models/ y los enlaza en src/models/.
#   - glintr100.onnx        reconocedor ArcFace ResNet100 @ Glint360K (embedding 512, entrada 112x112)
#   - scrfd_10g_bnkps.onnx  detector SCRFD-10GF con 5 keypoints (idéntico a det_10g.onnx de buffalo_l)
#   - 1k3d68.onnx           landmarks 3D (68 puntos), se usa para estimar la pose en el registro
# Licencia de los modelos: solo uso no comercial / investigación.
# Además descarga el detector de imágenes generadas con IA:
#   - community_forensics_vit_s384.onnx  Community Forensics (Park & Owens, CVPR 2025), ViT-S/16 384,
#     re-subido en ONNX por buildborderless en Hugging Face, fijado a un commit. Ese repo lo publica
#     como MIT, pero la licencia de los autores originales no está confirmada y el dataset de
#     entrenamiento es CC-BY-4.0 "para investigación": tratarlo como uso no comercial / investigación.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
URL="https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip"
FILES=(glintr100.onnx scrfd_10g_bnkps.onnx 1k3d68.onnx)

mkdir -p "$ROOT/models" "$ROOT/src/models"

missing=0
for f in "${FILES[@]}"; do [ -f "$ROOT/models/$f" ] || missing=1; done

if [ "$missing" -eq 1 ]; then
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    echo "Descargando $URL ..."
    curl -fL --progress-bar -o "$tmp/antelopev2.zip" "$URL"
    unzip -q "$tmp/antelopev2.zip" -d "$tmp"
    for f in "${FILES[@]}"; do cp "$tmp/antelopev2/$f" "$ROOT/models/$f"; done
fi

AI_MODEL=community_forensics_vit_s384.onnx
AI_MODEL_URL="https://huggingface.co/buildborderless/CommunityForensics-DeepfakeDet-ViT/resolve/ac6ee457bea904a373065754107451793b56db00/onnx/model.onnx"
AI_MODEL_SHA256=a42c7d740fbb345ba9a26d469b22f301d73089ce3c6da993877ed2b6965a8ba1
if [ ! -f "$ROOT/models/$AI_MODEL" ]; then
    echo "Descargando $AI_MODEL ..."
    curl -fL --progress-bar -o "$ROOT/models/$AI_MODEL.part" "$AI_MODEL_URL"
    echo "$AI_MODEL_SHA256  $ROOT/models/$AI_MODEL.part" | sha256sum -c --quiet
    mv "$ROOT/models/$AI_MODEL.part" "$ROOT/models/$AI_MODEL"
fi
FILES+=("$AI_MODEL")

# Para la ejecución local (desde src/, MODEL_PATH=models)
for f in "${FILES[@]}"; do ln -sf "../../models/$f" "$ROOT/src/models/$f"; done

ls -lh "$ROOT/models"
