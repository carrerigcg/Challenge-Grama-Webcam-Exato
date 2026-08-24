"""Script one-shot pra medir altura de grama via webcam."""
from __future__ import annotations

import json
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
LEVEL_NAMES = ("AUSENTE", "BAIXA", "MÉDIA", "ALTA")
# Cores BGR (OpenCV) por nível — usado na legenda do preview e nas bolinhas do PNG.
LEVEL_COLORS_BGR = (
    (150, 150, 150),  # AUSENTE — cinza
    (0, 255, 0),      # BAIXA — verde
    (0, 255, 255),    # MÉDIA — amarelo
    (0, 0, 255),      # ALTA — vermelho
)
# Faixas em cm (limites superiores inclusivos). Ajustar aqui pra recategorizar.
FAIXA_BAIXA_CM = 3.0     # altura <= FAIXA_BAIXA_CM  → BAIXA
FAIXA_MEDIA_CM = 7.0     # FAIXA_BAIXA_CM < altura <= FAIXA_MEDIA_CM → MÉDIA
                         # altura > FAIXA_MEDIA_CM → ALTA
CALIBRATION_PATH = "calibration.json"
DEBUG_PATH = "debug/ultima_medicao.png"
COUNTDOWN_SECONDS = 3


# --- Funções -----------------------------------------------------------------
def load_calibration(path: str) -> dict:
    """Carrega calibration.json e valida schema mínimo.

    Levanta FileNotFoundError com dica pra rodar calibrar.py, ou RuntimeError
    com mensagem clara se o JSON estiver corrompido / faltando campos.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} não encontrado. Rode: python calibrar.py"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path}: JSON inválido ({e})") from e

    if "px_por_cm" not in data:
        raise RuntimeError(f"{path}: campo px_por_cm ausente")
    if "y_chao" not in data:
        raise RuntimeError(f"{path}: campo y_chao ausente")
    if not isinstance(data["px_por_cm"], (int, float)) or data["px_por_cm"] <= 0:
        raise RuntimeError(f"{path}: px_por_cm deve ser número > 0")
    if not isinstance(data["y_chao"], int) or data["y_chao"] < 0:
        raise RuntimeError(f"{path}: y_chao deve ser inteiro >= 0")
    return data


def y_para_altura_cm(
    y_topo: int | None, y_chao: int, px_por_cm: float
) -> float | None:
    """Converte y do topo do verde em altura em cm acima do chão calibrado.

    None se sem verde. 0.0 se topo estiver no chão ou abaixo (grama não
    ultrapassa o baseline). Senão: (y_chao - y_topo) / px_por_cm.
    """
    if y_topo is None:
        return None
    if y_topo >= y_chao:
        return 0.0
    return (y_chao - y_topo) / px_por_cm


def classify_cm(
    altura_cm: float | None, faixa_baixa: float, faixa_media: float
) -> tuple[int, str]:
    """Classifica altura em cm em (nivel, nome).

    None → AUSENTE. <= faixa_baixa → BAIXA. <= faixa_media → MÉDIA. Senão ALTA.
    """
    if altura_cm is None:
        return 0, LEVEL_NAMES[0]
    if altura_cm <= faixa_baixa:
        return 1, LEVEL_NAMES[1]
    if altura_cm <= faixa_media:
        return 2, LEVEL_NAMES[2]
    return 3, LEVEL_NAMES[3]


def classify_frame_cm(
    alturas_cm: list[float | None], faixa_baixa: float, faixa_media: float
) -> tuple[int, str, float | None]:
    """Agrega alturas das colunas via mediana. Retorna (nivel, categoria, mediana_cm).

    Mediana ignora None. Se todas None → (0, "AUSENTE", None).
    """
    validas = [a for a in alturas_cm if a is not None]
    if not validas:
        return 0, LEVEL_NAMES[0], None
    mediana = float(np.median(validas))
    nivel, categoria = classify_cm(mediana, faixa_baixa, faixa_media)
    return nivel, categoria, mediana


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
    y_chao: int,
    faixa_baixa: float,
    faixa_media: float,
) -> bool:
    """Abre janela com preview ao vivo. SPACE=continuar, ESC=cancelar.

    Desenha uma linha branca no `y_chao` (chão calibrado) + colunas verticais
    de amostragem. Legenda no topo mostra as faixas em cm.
    """
    legenda = (
        f"BAIXA <= {faixa_baixa:g}cm | "
        f"MEDIA <= {faixa_media:g}cm | "
        f"ALTA > {faixa_media:g}cm"
    )
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

            for frac_guia in (0.10, 0.50, 0.90):
                y_guia = int(altura_frame * frac_guia)
                cv2.line(display, (0, y_guia), (largura_frame, y_guia),
                         (200, 200, 200), 1)

            for frac in col_fractions:
                x = int(largura_frame * frac)
                cv2.line(display, (x, 0), (x, altura_frame), (0, 255, 255), 1)

            # Linha branca sólida = chão calibrado
            cv2.line(display, (0, y_chao), (largura_frame, y_chao),
                     (255, 255, 255), 2)
            cv2.putText(
                display, "chao", (5, y_chao - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
            )

            cv2.putText(
                display, legenda, (10, 22),
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


def margem_erro_cm(alturas_cm: list[float | None]) -> float | None:
    """Metade da amplitude (max - min) das alturas válidas em cm.

    None se menos de 2 colunas válidas. 0.0 se todas iguais.
    """
    validas = [a for a in alturas_cm if a is not None]
    if len(validas) < 2:
        return None
    return (max(validas) - min(validas)) / 2.0


def _formatar_cm(valor: float | None) -> str:
    """Formata cm com 1 decimal e vírgula PT-BR. None → '—'."""
    if valor is None:
        return "—"
    return f"{valor:.1f}".replace(".", ",") + " cm"


def _formatar_mediana_com_margem(
    mediana: float | None, margem: float | None
) -> str:
    """Formata mediana + margem. Ex.: '2,8 cm ± 0,4 cm' | '2,8 cm ± —' | '—'."""
    if mediana is None:
        return "—"
    if margem is None:
        return f"{_formatar_cm(mediana)} ± —"
    return f"{_formatar_cm(mediana)} ± {_formatar_cm(margem)}"


def print_report(
    alturas_cm: list[float | None],
    altura_mediana_cm: float | None,
    margem_cm: float | None,
    categoria: str,
) -> None:
    formatadas = [_formatar_cm(a) for a in alturas_cm]
    print(f"Alturas por coluna: {formatadas}")
    print(f"Altura mediana:     {_formatar_mediana_com_margem(altura_mediana_cm, margem_cm)}")
    print(f"Categoria:          {categoria}")


def save_debug(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    top_ys: list[int | None],
    alturas_cm: list[float | None],
    altura_mediana_cm: float | None,
    col_fractions: tuple[float, ...],
    y_chao: int,
    px_por_cm: float,
    categoria: str,
    path: str,
) -> None:
    try:
        annotated = frame_bgr.copy()
        altura_frame, largura_frame = annotated.shape[:2]

        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        annotated = cv2.addWeighted(annotated, 0.7, mask_bgr, 0.3, 0)

        # Linha branca sólida = chão calibrado
        cv2.line(annotated, (0, y_chao), (largura_frame, y_chao),
                 (255, 255, 255), 2)
        cv2.putText(
            annotated, "chao", (5, y_chao - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        )

        # Colunas verticais + marca do topo + label de cm
        for frac, y_topo, altura in zip(col_fractions, top_ys, alturas_cm):
            x = int(largura_frame * frac)
            cv2.line(annotated, (x, 0), (x, altura_frame), (0, 255, 255), 1)
            if y_topo is not None:
                cv2.circle(annotated, (x, y_topo), 5, (0, 255, 0), -1)
                label = _formatar_cm(altura)
                cv2.putText(
                    annotated, label, (x + 8, y_topo - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
                )

        # Régua vertical de referência no canto direito (marcas 1 em 1 cm até 10)
        _desenhar_regua(annotated, y_chao, px_por_cm, altura_frame, largura_frame)

        # Texto grande centralizado no topo: "X,X cm — CATEGORIA"
        titulo = f"{_formatar_cm(altura_mediana_cm)} - {categoria}"
        (tw, _), _ = cv2.getTextSize(titulo, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        cv2.putText(
            annotated, titulo, ((largura_frame - tw) // 2, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2,
        )

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        ok = cv2.imwrite(path, annotated)
        if not ok:
            print(f"AVISO: nao consegui salvar debug em {path}", file=sys.stderr)
    except Exception as e:
        print(f"AVISO: falha ao salvar debug: {e}", file=sys.stderr)


def _desenhar_regua(
    img: np.ndarray, y_chao: int, px_por_cm: float,
    altura_frame: int, largura_frame: int, max_cm: int = 10,
) -> None:
    """Desenha uma régua vertical no canto direito partindo do chão pra cima."""
    x_regua = largura_frame - 25
    for cm in range(0, max_cm + 1):
        y = y_chao - int(cm * px_por_cm)
        if y < 0 or y >= altura_frame:
            continue
        largura_marca = 15 if cm % 5 == 0 else 8
        cv2.line(img, (x_regua, y), (x_regua + largura_marca, y),
                 (255, 255, 255), 1)
        if cm % 5 == 0:
            cv2.putText(
                img, f"{cm}", (x_regua + 17, y + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
            )
    cv2.line(img, (x_regua, min(y_chao, altura_frame - 1)),
             (x_regua, max(0, y_chao - int(max_cm * px_por_cm))),
             (255, 255, 255), 1)


def main() -> int:
    try:
        calibration = load_calibration(CALIBRATION_PATH)
        y_chao = calibration["y_chao"]
        px_por_cm = float(calibration["px_por_cm"])
        if not preview_camera(
            CAMERA_INDEX, CAMERA_BACKEND, SAMPLE_COLS,
            y_chao, FAIXA_BAIXA_CM, FAIXA_MEDIA_CM,
        ):
            print("Cancelado.")
            return 130
        countdown(COUNTDOWN_SECONDS)
        frames = capture_frames(FRAME_COUNT, CAMERA_INDEX, CAMERA_BACKEND)
        masks = [apply_mask(f) for f in frames]
        mask = median_stack(masks)
        top_ys = measure_top_y(mask, SAMPLE_COLS)
        alturas_cm = [y_para_altura_cm(y, y_chao, px_por_cm) for y in top_ys]
        nivel, categoria, altura_mediana = classify_frame_cm(
            alturas_cm, FAIXA_BAIXA_CM, FAIXA_MEDIA_CM,
        )
        print_report(alturas_cm, altura_mediana, categoria)
        if nivel == 0:
            print("AVISO: nenhuma grama detectada no frame", file=sys.stderr)
        save_debug(
            frames[-1], mask, top_ys, alturas_cm, altura_mediana,
            SAMPLE_COLS, y_chao, px_por_cm, categoria, DEBUG_PATH,
        )
        print(f"OK: {DEBUG_PATH} salvo")
        return 0
    except KeyboardInterrupt:
        print("Cancelado.")
        return 130
    except FileNotFoundError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
