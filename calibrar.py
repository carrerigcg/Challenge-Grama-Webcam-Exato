"""Script one-shot pra calibrar câmera fixa: gera calibration.json.

Fluxo:
1. Usuário informa quantos cm mede o segmento de referência (ex: 10.0).
2. Abre preview da webcam. Usuário clica em 2 extremos do segmento.
3. Usuário clica na linha do chão (base da grama).
4. Congela frame, mostra marcações. ENTER=salvar, R=refazer, ESC=cancelar.
5. Grava calibration.json.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

import cv2
import numpy as np
from dotenv import load_dotenv

import camera

load_dotenv()

# --- Configurações -----------------------------------------------------------
CAMERA_INDEX = camera.detectar_indice()
CAMERA_BACKEND = camera.detectar_backend()  # MSMF no Windows, V4L2 na Pi
OUTPUT_PATH = "calibration.json"
COR_PONTO_REF = (0, 255, 255)      # amarelo — pontos da régua
COR_LINHA_REF = (0, 200, 200)      # amarelo escuro — linha entre eles
COR_LINHA_CHAO = (255, 255, 255)   # branco — chão
COR_TEXTO = (255, 255, 255)
JANELA = "Calibrar Camera"


# --- Funções puras (testadas) ------------------------------------------------
def calcular_px_por_cm(
    p1: tuple[int, int], p2: tuple[int, int], cm_ref: float
) -> float:
    """Distância euclidiana em pixels dividida pelo tamanho conhecido em cm."""
    if cm_ref <= 0:
        raise ValueError("cm_ref deve ser > 0")
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    dist_px = math.sqrt(dx * dx + dy * dy)
    if dist_px == 0:
        raise ValueError("pontos p1 e p2 são idênticos")
    return dist_px / cm_ref


def montar_calibration_dict(
    px_por_cm: float, y_chao: int, resolucao: tuple[int, int], cm_ref: float
) -> dict:
    return {
        "px_por_cm": float(px_por_cm),
        "y_chao": int(y_chao),
        "resolucao": [int(resolucao[0]), int(resolucao[1])],
        "created_at": datetime.now().replace(microsecond=0).isoformat(),
        "segmento_cm_referencia": float(cm_ref),
    }


def salvar_calibration(dados: dict, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


# --- UI (não testada, exige webcam) ------------------------------------------
def _ler_cm_ref() -> float | None:
    """Pergunta ao usuário o tamanho em cm. Retorna None se cancelado/invalido."""
    try:
        entrada = input(
            "Quantos cm mede o segmento de referência (ex: 10.0)? "
        ).strip().replace(",", ".")
        valor = float(entrada)
        if valor <= 0:
            print("ERRO: valor deve ser > 0", file=sys.stderr)
            return None
        return valor
    except (ValueError, EOFError, KeyboardInterrupt):
        return None


def _abrir_webcam() -> cv2.VideoCapture:
    cap = cv2.VideoCapture(CAMERA_INDEX, CAMERA_BACKEND)
    if not cap.isOpened():
        raise RuntimeError(
            f"webcam nao acessivel (index={CAMERA_INDEX}, backend={CAMERA_BACKEND})"
        )
    return cap


def _capturar_cliques(
    cap: cv2.VideoCapture, instrucao: str, n_cliques: int
) -> list[tuple[int, int]] | None:
    """Preview ao vivo aceitando N cliques do mouse. Retorna None se ESC."""
    cliques: list[tuple[int, int]] = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(cliques) < n_cliques:
            cliques.append((x, y))

    cv2.namedWindow(JANELA)
    cv2.setMouseCallback(JANELA, on_mouse)
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            if cv2.waitKey(1) & 0xFF == 27:
                return None
            continue
        display = frame.copy()
        altura, largura = display.shape[:2]

        for frac in (0.10, 0.50, 0.90):
            y = int(altura * frac)
            cv2.line(display, (0, y), (largura, y), (200, 200, 200), 1)

        for i, (cx, cy) in enumerate(cliques):
            cv2.circle(display, (cx, cy), 6, COR_PONTO_REF, -1)
            cv2.putText(display, str(i + 1), (cx + 10, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, COR_PONTO_REF, 2)
        if len(cliques) >= 2 and n_cliques >= 2:
            cv2.line(display, cliques[0], cliques[1], COR_LINHA_REF, 2)

        cv2.putText(display, instrucao, (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COR_TEXTO, 1)
        cv2.putText(display, f"Cliques: {len(cliques)}/{n_cliques}",
                    (10, altura - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COR_TEXTO, 1)
        cv2.imshow(JANELA, display)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            return None
        if len(cliques) >= n_cliques:
            return cliques


def _confirmar(
    cap: cv2.VideoCapture, p1: tuple[int, int], p2: tuple[int, int],
    y_chao: int, px_por_cm: float, cm_ref: float,
) -> str:
    """Congela um frame com marcações, aguarda ENTER/R/ESC."""
    ok, frame = cap.read()
    if not ok or frame is None:
        frame = np.zeros((480, 640, 3), np.uint8)
    display = frame.copy()
    altura, largura = display.shape[:2]

    cv2.line(display, (0, y_chao), (largura, y_chao), COR_LINHA_CHAO, 2)
    cv2.putText(display, "chao", (5, y_chao - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COR_LINHA_CHAO, 1)

    cv2.line(display, p1, p2, COR_LINHA_REF, 2)
    for ponto in (p1, p2):
        cv2.circle(display, ponto, 6, COR_PONTO_REF, -1)

    linha1 = f"{cm_ref:g}cm = {math.hypot(p2[0]-p1[0], p2[1]-p1[1]):.1f}px"
    linha2 = f"→ {px_por_cm:.2f} px/cm"
    cv2.putText(display, linha1, (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COR_TEXTO, 1)
    cv2.putText(display, linha2, (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COR_TEXTO, 1)
    cv2.putText(display, "ENTER=salvar  R=refazer  ESC=cancelar",
                (10, altura - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COR_TEXTO, 1)

    cv2.imshow(JANELA, display)
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key == 27:
            return "cancelar"
        if key == 13:  # ENTER
            return "salvar"
        if key in (ord("r"), ord("R")):
            return "refazer"


def main() -> int:
    cm_ref = _ler_cm_ref()
    if cm_ref is None:
        print("Cancelado.")
        return 130

    try:
        cap = _abrir_webcam()
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1

    try:
        while True:
            print(
                f"\nPreview aberto. Clique nos 2 extremos do segmento de "
                f"{cm_ref:g}cm.",
                flush=True,
            )
            pontos_ref = _capturar_cliques(
                cap, f"Clique nos 2 extremos do segmento de {cm_ref:g}cm",
                n_cliques=2,
            )
            if pontos_ref is None:
                print("Cancelado.")
                return 130

            print("Agora clique na linha do chao (base da grama).", flush=True)
            pontos_chao = _capturar_cliques(
                cap, "Clique na linha do chao (base da grama)",
                n_cliques=1,
            )
            if pontos_chao is None:
                print("Cancelado.")
                return 130

            p1, p2 = pontos_ref[0], pontos_ref[1]
            y_chao = pontos_chao[0][1]
            try:
                px_por_cm = calcular_px_por_cm(p1, p2, cm_ref)
            except ValueError as e:
                print(f"ERRO: {e}. Refazendo...", file=sys.stderr)
                continue

            decisao = _confirmar(cap, p1, p2, y_chao, px_por_cm, cm_ref)
            if decisao == "cancelar":
                print("Cancelado.")
                return 130
            if decisao == "refazer":
                continue

            resolucao = (
                int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
            dados = montar_calibration_dict(px_por_cm, y_chao, resolucao, cm_ref)
            salvar_calibration(dados, OUTPUT_PATH)
            print(
                f"\nOK: {OUTPUT_PATH} salvo.\n"
                f"   px_por_cm = {px_por_cm:.2f}\n"
                f"   y_chao    = {y_chao}\n"
                f"   resolucao = {resolucao[0]}x{resolucao[1]}"
            )
            return 0
    except KeyboardInterrupt:
        print("Cancelado.")
        return 130
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
