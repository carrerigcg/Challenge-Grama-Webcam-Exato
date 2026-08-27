"""Configuração de câmera por plataforma.

O mesmo código roda nas estações Windows e nas Raspberry Pi (Linux), que
exigem backends diferentes do OpenCV: MSMF é API da Microsoft e não existe
no Linux; V4L2 é o driver de vídeo do kernel Linux e não existe no Windows.

Ambos os valores aceitam override por variável de ambiente, para o caso de
uma câmera CSI ou driver que peça outro backend.
"""
from __future__ import annotations

import os
import sys

import cv2

# Backends de captura aceitos no override. Restringir a lista evita que um
# nome qualquer de atributo do cv2 (cv2.imread, por exemplo) passe adiante.
BACKENDS_VALIDOS = (
    "CAP_ANY",
    "CAP_MSMF",
    "CAP_DSHOW",
    "CAP_V4L2",
    "CAP_V4L",
    "CAP_GSTREAMER",
    "CAP_FFMPEG",
)


def detectar_backend() -> int:
    """Backend do OpenCV: CAMERA_BACKEND do env, senão pela plataforma."""
    nome = os.environ.get("CAMERA_BACKEND")
    if nome:
        if nome not in BACKENDS_VALIDOS:
            raise RuntimeError(
                f"CAMERA_BACKEND={nome!r} não é um backend de captura válido. "
                f"Use um destes: {', '.join(BACKENDS_VALIDOS)}"
            )
        return getattr(cv2, nome)
    if sys.platform.startswith("win"):
        return cv2.CAP_MSMF
    return cv2.CAP_V4L2


def detectar_indice() -> int:
    """Índice da câmera: CAMERA_INDEX do env, senão 0."""
    bruto = os.environ.get("CAMERA_INDEX", "0")
    try:
        return int(bruto)
    except ValueError:
        raise RuntimeError(
            f"CAMERA_INDEX={bruto!r} não é um número inteiro. "
            "Use 0 para a primeira câmera, 1 para a segunda, etc."
        ) from None
