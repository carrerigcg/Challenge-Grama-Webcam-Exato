"""Script one-shot pra medir altura de grama via webcam."""
from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np

# --- Configurações -----------------------------------------------------------
CAMERA_INDEX = 0
CAMERA_BACKEND = cv2.CAP_MSMF
FRAME_COUNT = 5
HSV_LOWER = (35, 40, 40)
HSV_UPPER = (85, 255, 255)
SAMPLE_COLS = (0.25, 0.50, 0.75)
# Linhas horizontais como % da altura do frame (baixo → cima).
# Índice 0 = chão de referência (só visual); 1 = separador BAIXA/MÉDIA; 2 = separador MÉDIA/ALTA.
LINE_FRACTIONS = (0.90, 0.60, 0.35)
LEVEL_NAMES = ("AUSENTE", "BAIXA", "MÉDIA", "ALTA")
LINE_COLORS = ((255, 255, 255), (0, 200, 200), (0, 140, 255))
LINE_LABELS = ("chão", "-> MÉDIA", "-> ALTA")
LEGEND_TEXT = "Baixo <= 3cm  /  Medio > 3 e <= 7cm  /  Alto > 7cm"
DEBUG_PATH = "debug/ultima_medicao.png"
COUNTDOWN_SECONDS = 3


# --- Funções -----------------------------------------------------------------
def countdown(seconds: int) -> None:
    for i in range(seconds, 0, -1):
        print(f"{i}...", flush=True)
        time.sleep(1)
    print("snap!", flush=True)


def capture_frames(n: int, camera_index: int, backend: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(camera_index, backend)
    try:
        if not cap.isOpened():
            raise RuntimeError(
                f"webcam nao acessivel (index={camera_index}, backend={backend})"
            )
        frames: list[np.ndarray] = []
        for _ in range(n):
            frame = None
            for _tentativa in range(3):
                ok, f = cap.read()
                if ok and f is not None:
                    frame = f
                    break
            if frame is not None:
                frames.append(frame)
        if not frames:
            raise RuntimeError("nenhum frame capturado da webcam")
        if len(frames) < n:
            print(f"AVISO: capturou {len(frames)}/{n} frames", file=sys.stderr)
        return frames
    finally:
        cap.release()


def preview_camera(
    camera_index: int,
    backend: int,
    col_fractions: tuple[float, ...],
    line_fractions: tuple[float, ...],
) -> bool:
    """Abre janela com preview ao vivo. SPACE=continuar, ESC=cancelar."""
    cap = cv2.VideoCapture(camera_index, backend)
    try:
        if not cap.isOpened():
            raise RuntimeError(
                f"webcam nao acessivel (index={camera_index}, backend={backend})"
            )
        print("Preview aberto. SPACE=capturar, ESC=cancelar", flush=True)
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                if cv2.waitKey(1) & 0xFF == 27:
                    return False
                continue
            altura_frame, largura_frame = frame.shape[:2]
            mask = apply_mask(frame)
            mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            display = cv2.addWeighted(frame, 0.7, mask_bgr, 0.3, 0)

            for frac in col_fractions:
                x = int(largura_frame * frac)
                cv2.line(display, (x, 0), (x, altura_frame), (0, 255, 255), 1)

            for i, frac in enumerate(line_fractions):
                y = int(altura_frame * frac)
                if i == 0:
                    for x in range(0, largura_frame, 14):
                        cv2.line(display, (x, y), (min(x + 8, largura_frame), y),
                                 LINE_COLORS[i], 1)
                else:
                    cv2.line(display, (0, y), (largura_frame, y), LINE_COLORS[i], 1)
                cv2.putText(
                    display, LINE_LABELS[i], (5, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, LINE_COLORS[i], 1,
                )

            cv2.putText(
                display, LEGEND_TEXT, (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
            )
            cv2.putText(
                display, "SPACE=capturar  ESC=cancelar",
                (10, altura_frame - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
            )
            cv2.imshow("Preview - Medir Grama", display)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                return False
            if key == 32:
                return True
    finally:
        cap.release()
        cv2.destroyAllWindows()


def apply_mask(frame_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(HSV_LOWER), np.array(HSV_UPPER))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def median_stack(masks: list[np.ndarray]) -> np.ndarray:
    stack = np.stack(masks, axis=0)
    return np.median(stack, axis=0).astype(np.uint8)


def measure_top_y(mask: np.ndarray, col_fractions: tuple[float, ...]) -> list[int | None]:
    """Retorna Y do primeiro pixel verde de cima em cada coluna, ou None se vazio."""
    _altura_frame, largura_frame = mask.shape[:2]
    top_ys: list[int | None] = []
    for frac in col_fractions:
        x = int(largura_frame * frac)
        coluna = mask[:, x]
        indices = np.where(coluna == 255)[0]
        if indices.size == 0:
            top_ys.append(None)
        else:
            top_ys.append(int(indices[0]))
    return top_ys


def classify_column(y_topo: int | None, altura_frame: int,
                    line_fractions: tuple[float, ...]) -> int:
    """Retorna nível 0/1/2/3 (AUSENTE/BAIXA/MÉDIA/ALTA) da coluna.

    line_fractions = (chão, sep1, sep2). Só sep1 e sep2 classificam.
    Menor y = mais alto na imagem = grama mais alta.
    """
    if y_topo is None:
        return 0
    sep1_y = int(altura_frame * line_fractions[1])
    sep2_y = int(altura_frame * line_fractions[2])
    if y_topo <= sep2_y:
        return 3
    if y_topo <= sep1_y:
        return 2
    return 1


def classify_frame(top_ys: list[int | None], altura_frame: int,
                   line_fractions: tuple[float, ...]) -> tuple[int, str]:
    """Combina os níveis das colunas via mediana. Retorna (nivel, nome)."""
    niveis = [classify_column(y, altura_frame, line_fractions) for y in top_ys]
    nivel_final = int(np.median(niveis))
    return nivel_final, LEVEL_NAMES[nivel_final]


def print_report(top_ys: list[int | None], niveis: list[int], categoria: str) -> None:
    print(f"y_topo por coluna: {top_ys}")
    print(f"níveis por coluna: {niveis}")
    print(f"Categoria: {categoria}")


def save_debug(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    top_ys: list[int | None],
    col_fractions: tuple[float, ...],
    line_fractions: tuple[float, ...],
    nivel_final: int,
    categoria: str,
    path: str,
) -> None:
    try:
        annotated = frame_bgr.copy()
        altura_frame, largura_frame = annotated.shape[:2]

        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        annotated = cv2.addWeighted(annotated, 0.7, mask_bgr, 0.3, 0)

        for frac in col_fractions:
            x = int(largura_frame * frac)
            cv2.line(annotated, (x, 0), (x, altura_frame), (0, 255, 255), 1)

        # Destaca a linha separadora que a grama atingiu (idx 0 = chão, não destacado).
        idx_destacada = None
        if nivel_final == 2:  # MÉDIA -> atingiu sep1
            idx_destacada = 1
        elif nivel_final == 3:  # ALTA -> atingiu sep2
            idx_destacada = 2

        for i, frac in enumerate(line_fractions):
            y = int(altura_frame * frac)
            if i == 0:
                for x in range(0, largura_frame, 14):
                    cv2.line(annotated, (x, y), (min(x + 8, largura_frame), y),
                             LINE_COLORS[i], 1)
            else:
                cv2.line(annotated, (0, y), (largura_frame, y), LINE_COLORS[i], 1)
            cv2.putText(
                annotated, LINE_LABELS[i], (5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, LINE_COLORS[i], 1,
            )

        if idx_destacada is not None:
            y = int(altura_frame * line_fractions[idx_destacada])
            cv2.line(annotated, (0, y), (largura_frame, y), (0, 255, 0), 3)

        (tw, _), _ = cv2.getTextSize(categoria, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)
        cv2.putText(
            annotated, categoria, ((largura_frame - tw) // 2, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3,
        )

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        ok = cv2.imwrite(path, annotated)
        if not ok:
            print(f"AVISO: nao consegui salvar debug em {path}", file=sys.stderr)
    except Exception as e:
        print(f"AVISO: falha ao salvar debug: {e}", file=sys.stderr)


def main() -> int:
    try:
        if not preview_camera(CAMERA_INDEX, CAMERA_BACKEND, SAMPLE_COLS, LINE_FRACTIONS):
            print("Cancelado.")
            return 130
        countdown(COUNTDOWN_SECONDS)
        frames = capture_frames(FRAME_COUNT, CAMERA_INDEX, CAMERA_BACKEND)
        masks = [apply_mask(f) for f in frames]
        mask = median_stack(masks)
        top_ys = measure_top_y(mask, SAMPLE_COLS)
        niveis = [classify_column(y, mask.shape[0], LINE_FRACTIONS) for y in top_ys]
        nivel_final, categoria = classify_frame(top_ys, mask.shape[0], LINE_FRACTIONS)
        print_report(top_ys, niveis, categoria)
        if nivel_final == 0:
            print("AVISO: nenhuma grama detectada no frame", file=sys.stderr)
        save_debug(
            frames[-1], mask, top_ys, SAMPLE_COLS, LINE_FRACTIONS,
            nivel_final, categoria, DEBUG_PATH,
        )
        print(f"OK: {DEBUG_PATH} salvo")
        return 0
    except KeyboardInterrupt:
        print("Cancelado.")
        return 130
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
