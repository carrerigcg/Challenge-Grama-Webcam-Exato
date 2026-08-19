# Medição de Grama via Webcam — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir um script Python one-shot que captura imagens da webcam, segmenta grama por HSV, mede altura em 3 colunas verticais fixas e reporta uma categoria (BAIXA/MÉDIA/ALTA) com valor cru em px e uma imagem anotada de debug.

**Architecture:** Um único arquivo `medir_grama.py` com 9 funções puras/isoladas + testes unitários em `tests/test_medir_grama.py` (pytest). Funções puras são TDD; funções que tocam hardware (webcam) ou disco (PNG debug) usam mock + smoke test manual.

**Tech Stack:** Python 3.11.9, OpenCV 5.0.0 (`cv2`), NumPy 2.3.3, pytest.

**Spec de referência:** `docs/superpowers/specs/2026-08-11-medicao-grama-webcam-design.md`

---

## Estrutura de arquivos

```
challenge-grama-webcam/
├── medir_grama.py                       # script principal + todas as funções
├── tests/
│   ├── __init__.py                      # marca como pacote
│   └── test_medir_grama.py              # testes das funções puras + main
├── debug/                               # criado em runtime pelo save_debug
├── .gitignore                           # ignora .superpowers/, debug/, cache, etc.
└── docs/superpowers/
    ├── specs/2026-08-11-medicao-grama-webcam-design.md
    └── plans/2026-08-11-medicao-grama-webcam.md    # este arquivo
```

## Ordem das tasks (por dependência)

| # | Task | Depende de |
|---|---|---|
| 1 | Bootstrap (git init, .gitignore, esqueleto do arquivo, pytest) | — |
| 2 | `classify()` | 1 |
| 3 | `measure_heights()` | 1 |
| 4 | `median_stack()` | 1 |
| 5 | `apply_mask()` | 1 |
| 6 | `countdown()` + `print_report()` | 1 |
| 7 | `capture_frames()` | 1 |
| 8 | `save_debug()` | 1 |
| 9 | `main()` + smoke test end-to-end | 2-8 |

Tasks 2-8 são totalmente independentes entre si (não compartilham código), então podem ser paralelizadas por subagents sem risco de conflito.

---

## Task 1: Bootstrap do projeto

**Files:**
- Create: `.gitignore`
- Create: `medir_grama.py`
- Create: `tests/__init__.py`
- Create: `tests/test_medir_grama.py`

- [ ] **Step 1: Inicializar git**

Run:
```bash
git init
git branch -M main
```
Expected: `Initialized empty Git repository...`

- [ ] **Step 2: Criar .gitignore**

Create `.gitignore`:
```
# Python
__pycache__/
*.pyc
.pytest_cache/

# Runtime
debug/

# Ferramentas
.superpowers/

# IDE / OS
.vscode/
.idea/
Thumbs.db
.DS_Store
```

- [ ] **Step 3: Criar esqueleto do medir_grama.py com constantes e stubs**

Create `medir_grama.py`:
```python
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
THRESHOLDS_PX = (40, 90)
DEBUG_PATH = "debug/ultima_medicao.png"
COUNTDOWN_SECONDS = 3


# --- Funções -----------------------------------------------------------------
def countdown(seconds: int) -> None:
    raise NotImplementedError


def capture_frames(n: int, camera_index: int, backend: int) -> list[np.ndarray]:
    raise NotImplementedError


def apply_mask(frame_bgr: np.ndarray) -> np.ndarray:
    raise NotImplementedError


def median_stack(masks: list[np.ndarray]) -> np.ndarray:
    raise NotImplementedError


def measure_heights(mask: np.ndarray, col_fractions: tuple[float, ...]) -> list[int]:
    raise NotImplementedError


def classify(altura_px: int, thresholds: tuple[int, int]) -> str:
    raise NotImplementedError


def print_report(heights: list[int], mediana: int, categoria: str) -> None:
    raise NotImplementedError


def save_debug(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    heights: list[int],
    col_fractions: tuple[float, ...],
    categoria: str,
    path: str,
) -> None:
    raise NotImplementedError


def main() -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Criar pacote de testes**

Create `tests/__init__.py`: (arquivo vazio)

Create `tests/test_medir_grama.py`:
```python
"""Testes das funções puras de medir_grama."""
import numpy as np
import pytest

import medir_grama
```

- [ ] **Step 5: Instalar pytest**

Run:
```bash
python -m pip install pytest
```
Expected: `Successfully installed pytest-...`

- [ ] **Step 6: Verificar que o esqueleto importa**

Run:
```bash
python -c "import medir_grama; print('ok')"
```
Expected: `ok`

Run:
```bash
pytest tests/ -v
```
Expected: `no tests ran` (arquivo de teste só tem imports).

- [ ] **Step 7: Commit**

```bash
git add .gitignore medir_grama.py tests/__init__.py tests/test_medir_grama.py
git commit -m "chore: bootstrap projeto com stubs, pytest e gitignore"
```

---

## Task 2: `classify()` (função pura, sem deps)

**Files:**
- Modify: `medir_grama.py` (função `classify`)
- Modify: `tests/test_medir_grama.py` (adicionar testes)

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- classify ----------------------------------------------------------------
def test_classify_below_lower_threshold_is_baixa():
    assert medir_grama.classify(39, (40, 90)) == "BAIXA"


def test_classify_at_lower_threshold_is_media():
    assert medir_grama.classify(40, (40, 90)) == "MÉDIA"


def test_classify_below_upper_threshold_is_media():
    assert medir_grama.classify(89, (40, 90)) == "MÉDIA"


def test_classify_at_upper_threshold_is_alta():
    assert medir_grama.classify(90, (40, 90)) == "ALTA"


def test_classify_zero_is_baixa():
    assert medir_grama.classify(0, (40, 90)) == "BAIXA"


def test_classify_very_large_is_alta():
    assert medir_grama.classify(10000, (40, 90)) == "ALTA"
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k classify
```
Expected: 6 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar classify()**

Substituir a função stub em `medir_grama.py`:
```python
def classify(altura_px: int, thresholds: tuple[int, int]) -> str:
    t1, t2 = thresholds
    if altura_px < t1:
        return "BAIXA"
    if altura_px < t2:
        return "MÉDIA"
    return "ALTA"
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k classify
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: classify() classifica altura em BAIXA/MÉDIA/ALTA"
```

---

## Task 3: `measure_heights()` (função pura, np only)

**Files:**
- Modify: `medir_grama.py` (função `measure_heights`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- measure_heights ---------------------------------------------------------
def test_measure_heights_all_columns_have_grass():
    mask = np.zeros((100, 100), np.uint8)
    # coluna x=25 (25%): topo em y=60 → altura = 100-60 = 40
    mask[60:100, 25] = 255
    # coluna x=50 (50%): topo em y=30 → altura = 70
    mask[30:100, 50] = 255
    # coluna x=75 (75%): topo em y=80 → altura = 20
    mask[80:100, 75] = 255
    result = medir_grama.measure_heights(mask, (0.25, 0.50, 0.75))
    assert result == [40, 70, 20]


def test_measure_heights_empty_mask_returns_zeros():
    mask = np.zeros((100, 100), np.uint8)
    result = medir_grama.measure_heights(mask, (0.25, 0.50, 0.75))
    assert result == [0, 0, 0]


def test_measure_heights_column_without_green_returns_zero_for_that_column():
    mask = np.zeros((100, 100), np.uint8)
    mask[50:100, 25] = 255  # só a coluna 25% tem verde (altura 50)
    result = medir_grama.measure_heights(mask, (0.25, 0.50, 0.75))
    assert result == [50, 0, 0]


def test_measure_heights_returns_ints_not_numpy_scalars():
    mask = np.zeros((100, 100), np.uint8)
    mask[70:100, 50] = 255
    result = medir_grama.measure_heights(mask, (0.50,))
    assert isinstance(result[0], int)
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k measure_heights
```
Expected: 4 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar measure_heights()**

Substituir a função stub em `medir_grama.py`:
```python
def measure_heights(mask: np.ndarray, col_fractions: tuple[float, ...]) -> list[int]:
    altura_frame, largura_frame = mask.shape[:2]
    heights: list[int] = []
    for frac in col_fractions:
        x = int(largura_frame * frac)
        coluna = mask[:, x]
        indices = np.where(coluna == 255)[0]
        if indices.size == 0:
            heights.append(0)
        else:
            y_topo = int(indices[0])
            heights.append(altura_frame - y_topo)
    return heights
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k measure_heights
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: measure_heights() mede altura em px por coluna"
```

---

## Task 4: `median_stack()` (função pura, np only)

**Files:**
- Modify: `medir_grama.py` (função `median_stack`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- median_stack ------------------------------------------------------------
def test_median_stack_identical_masks_returns_same_mask():
    m = np.array([[0, 255], [255, 0]], np.uint8)
    result = medir_grama.median_stack([m.copy() for _ in range(5)])
    np.testing.assert_array_equal(result, m)


def test_median_stack_majority_wins():
    zero = np.zeros((2, 2), np.uint8)
    um = np.full((2, 2), 255, np.uint8)
    # 3 zeros vs 2 uns → mediana = 0
    result = medir_grama.median_stack([zero, zero, zero, um, um])
    np.testing.assert_array_equal(result, zero)


def test_median_stack_returns_uint8():
    m = np.zeros((3, 3), np.uint8)
    result = medir_grama.median_stack([m, m, m])
    assert result.dtype == np.uint8


def test_median_stack_shape_matches_input():
    m = np.zeros((10, 20), np.uint8)
    result = medir_grama.median_stack([m, m, m])
    assert result.shape == (10, 20)
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k median_stack
```
Expected: 4 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar median_stack()**

Substituir a função stub em `medir_grama.py`:
```python
def median_stack(masks: list[np.ndarray]) -> np.ndarray:
    stack = np.stack(masks, axis=0)
    return np.median(stack, axis=0).astype(np.uint8)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k median_stack
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: median_stack() combina 5 máscaras via mediana px-a-px"
```

---

## Task 5: `apply_mask()` (função pura, cv2 + np)

**Files:**
- Modify: `medir_grama.py` (função `apply_mask`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- apply_mask --------------------------------------------------------------
def test_apply_mask_pure_green_becomes_255():
    frame = np.zeros((30, 30, 3), np.uint8)
    frame[:, :] = (0, 180, 0)  # verde puro em BGR
    result = medir_grama.apply_mask(frame)
    assert result.shape == (30, 30)
    assert result.dtype == np.uint8
    assert (result == 255).all()


def test_apply_mask_pure_black_becomes_0():
    frame = np.zeros((30, 30, 3), np.uint8)
    result = medir_grama.apply_mask(frame)
    assert (result == 0).all()


def test_apply_mask_pure_red_becomes_0():
    frame = np.zeros((30, 30, 3), np.uint8)
    frame[:, :] = (0, 0, 200)  # vermelho em BGR
    result = medir_grama.apply_mask(frame)
    assert (result == 0).all()


def test_apply_mask_removes_isolated_green_pixel_via_morfologia():
    # 1 pixel verde solto no meio de preto — o open 3×3 deve engolir
    frame = np.zeros((30, 30, 3), np.uint8)
    frame[15, 15] = (0, 180, 0)
    result = medir_grama.apply_mask(frame)
    assert result[15, 15] == 0
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k apply_mask
```
Expected: 4 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar apply_mask()**

Substituir a função stub em `medir_grama.py`:
```python
def apply_mask(frame_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(HSV_LOWER), np.array(HSV_UPPER))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k apply_mask
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: apply_mask() segmenta verde via HSV + morfologia"
```

---

## Task 6: `countdown()` + `print_report()` (I/O leve)

**Files:**
- Modify: `medir_grama.py` (funções `countdown` e `print_report`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- countdown ---------------------------------------------------------------
def test_countdown_prints_countdown_and_snap(capsys, monkeypatch):
    monkeypatch.setattr(medir_grama.time, "sleep", lambda s: None)
    medir_grama.countdown(3)
    out = capsys.readouterr().out
    assert "3" in out and "2" in out and "1" in out
    assert "snap" in out.lower()


def test_countdown_zero_seconds_still_prints_snap(capsys, monkeypatch):
    monkeypatch.setattr(medir_grama.time, "sleep", lambda s: None)
    medir_grama.countdown(0)
    out = capsys.readouterr().out
    assert "snap" in out.lower()


# --- print_report ------------------------------------------------------------
def test_print_report_contains_heights_mediana_and_categoria(capsys):
    medir_grama.print_report([82, 76, 88], 82, "MÉDIA")
    out = capsys.readouterr().out
    assert "82" in out
    assert "76" in out
    assert "88" in out
    assert "MÉDIA" in out
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k "countdown or print_report"
```
Expected: 3 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar countdown() e print_report()**

Substituir stubs em `medir_grama.py`:
```python
def countdown(seconds: int) -> None:
    for i in range(seconds, 0, -1):
        print(f"{i}...", flush=True)
        time.sleep(1)
    print("snap!", flush=True)


def print_report(heights: list[int], mediana: int, categoria: str) -> None:
    print(f"Alturas: {heights} px")
    print(f"Mediana:  {mediana} px → {categoria}")
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k "countdown or print_report"
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: countdown() e print_report() pra UX no terminal"
```

---

## Task 7: `capture_frames()` (webcam, mockada nos testes)

**Files:**
- Modify: `medir_grama.py` (função `capture_frames`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- capture_frames ----------------------------------------------------------
class _FakeCapOK:
    """Fake VideoCapture que sempre retorna frames válidos."""
    def isOpened(self):
        return True
    def read(self):
        return True, np.zeros((480, 640, 3), np.uint8)
    def release(self):
        pass


class _FakeCapNotOpened:
    def isOpened(self):
        return False
    def release(self):
        pass


class _FakeCapReadFails:
    def isOpened(self):
        return True
    def read(self):
        return False, None
    def release(self):
        pass


class _FakeCapFirstOkThenFails:
    """Retorna n_ok frames válidos, depois sempre falha."""
    def __init__(self, n_ok):
        self.n_ok = n_ok
        self.calls = 0
    def isOpened(self):
        return True
    def read(self):
        self.calls += 1
        if self.calls <= self.n_ok:
            return True, np.zeros((480, 640, 3), np.uint8)
        return False, None
    def release(self):
        pass


def test_capture_frames_returns_n_frames(monkeypatch):
    monkeypatch.setattr(medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapOK())
    frames = medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)
    assert len(frames) == 5
    assert all(f.shape == (480, 640, 3) for f in frames)
    assert all(f.dtype == np.uint8 for f in frames)


def test_capture_frames_raises_when_camera_wont_open(monkeypatch):
    monkeypatch.setattr(medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapNotOpened())
    with pytest.raises(RuntimeError, match="webcam"):
        medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)


def test_capture_frames_raises_when_all_reads_fail(monkeypatch):
    monkeypatch.setattr(medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapReadFails())
    with pytest.raises(RuntimeError):
        medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)


def test_capture_frames_partial_capture_prints_warning(monkeypatch, capsys):
    monkeypatch.setattr(
        medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapFirstOkThenFails(3)
    )
    frames = medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)
    assert len(frames) == 3
    err = capsys.readouterr().err
    assert "AVISO" in err
    assert "3/5" in err
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k capture_frames
```
Expected: 4 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar capture_frames()**

Substituir stub em `medir_grama.py`:
```python
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
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k capture_frames
```
Expected: 4 passed.

- [ ] **Step 5: Smoke test manual com a webcam real**

Rodar em um REPL Python (não commit):
```python
python -c "import medir_grama; frames = medir_grama.capture_frames(5, medir_grama.CAMERA_INDEX, medir_grama.CAMERA_BACKEND); print(len(frames), frames[0].shape, frames[0].dtype)"
```
Expected: `5 (480, 640, 3) uint8` (pode variar o shape se webcam tiver outra resolução default).

Se falhar com "webcam nao acessivel", verificar se outro app (Teams, Zoom, browser) tá segurando a câmera.

- [ ] **Step 6: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: capture_frames() abre webcam e captura N frames com retry"
```

---

## Task 8: `save_debug()` (FS, testável parcialmente)

**Files:**
- Modify: `medir_grama.py` (função `save_debug`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- save_debug --------------------------------------------------------------
def test_save_debug_creates_png_file(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "out.png"
    medir_grama.save_debug(
        frame, mask, [80, 70, 90], (0.25, 0.5, 0.75), "MÉDIA", str(out)
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_save_debug_creates_parent_directory(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "sub" / "dir" / "out.png"
    medir_grama.save_debug(
        frame, mask, [0, 0, 0], (0.25, 0.5, 0.75), "BAIXA", str(out)
    )
    assert out.exists()


def test_save_debug_does_not_raise_on_write_failure(tmp_path, capsys, monkeypatch):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    monkeypatch.setattr(medir_grama.cv2, "imwrite", lambda *a, **kw: False)
    medir_grama.save_debug(
        frame, mask, [0, 0, 0], (0.25, 0.5, 0.75), "BAIXA", str(tmp_path / "x.png")
    )
    assert "AVISO" in capsys.readouterr().err
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k save_debug
```
Expected: 3 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar save_debug()**

Substituir stub em `medir_grama.py`:
```python
def save_debug(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    heights: list[int],
    col_fractions: tuple[float, ...],
    categoria: str,
    path: str,
) -> None:
    try:
        annotated = frame_bgr.copy()
        altura_frame, largura_frame = annotated.shape[:2]

        # 3 linhas verticais tracejadas (vermelho) nas colunas de amostragem
        for frac, altura in zip(col_fractions, heights):
            x = int(largura_frame * frac)
            # simulação de "tracejado": traços de 8 px com gap de 6 px
            for y in range(0, altura_frame, 14):
                cv2.line(annotated, (x, y), (x, min(y + 8, altura_frame)), (0, 0, 255), 2)
            # texto com o valor de altura, colocado perto do topo do frame
            cv2.putText(
                annotated, str(altura), (x - 15, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
            )

        # categoria em texto grande no topo central
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
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run:
```bash
pytest tests/test_medir_grama.py -v -k save_debug
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: save_debug() gera PNG anotado com linhas e categoria"
```

---

## Task 9: `main()` + smoke test end-to-end

**Files:**
- Modify: `medir_grama.py` (função `main`)
- Modify: `tests/test_medir_grama.py`

- [ ] **Step 1: Escrever os testes falhando**

Adicionar em `tests/test_medir_grama.py`:
```python
# --- main --------------------------------------------------------------------
def _fake_green_frames(n=5):
    """Frame 640×480 com verde na metade inferior (altura ≈ 240 px)."""
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[240:, :] = (0, 180, 0)  # verde puro em BGR
    return [frame.copy() for _ in range(n)]


def test_main_success_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    assert (tmp_path / "out.png").exists()


def test_main_camera_failure_returns_one(monkeypatch, capsys):
    def raise_runtime(*a, **kw):
        raise RuntimeError("webcam nao acessivel")
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "capture_frames", raise_runtime)
    result = medir_grama.main()
    assert result == 1
    assert "ERRO" in capsys.readouterr().err


def test_main_keyboard_interrupt_returns_130(monkeypatch, capsys):
    def raise_kbint(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(medir_grama, "countdown", raise_kbint)
    result = medir_grama.main()
    assert result == 130
    assert "Cancelado" in capsys.readouterr().out


def test_main_no_green_detected_still_returns_zero_with_warning(monkeypatch, tmp_path, capsys):
    empty_frames = [np.zeros((480, 640, 3), np.uint8) for _ in range(5)]
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: empty_frames)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    assert "nenhuma grama" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Rodar os testes pra ver que falham**

Run:
```bash
pytest tests/test_medir_grama.py -v -k "test_main"
```
Expected: 4 falhas com `NotImplementedError`.

- [ ] **Step 3: Implementar main()**

Substituir stub em `medir_grama.py`:
```python
def main() -> int:
    try:
        countdown(COUNTDOWN_SECONDS)
        frames = capture_frames(FRAME_COUNT, CAMERA_INDEX, CAMERA_BACKEND)
        masks = [apply_mask(f) for f in frames]
        mask = median_stack(masks)
        heights = measure_heights(mask, SAMPLE_COLS)
        altura_px = int(np.median(heights))
        categoria = classify(altura_px, THRESHOLDS_PX)
        print_report(heights, altura_px, categoria)
        if all(h == 0 for h in heights):
            print("AVISO: nenhuma grama detectada no frame", file=sys.stderr)
        save_debug(frames[-1], mask, heights, SAMPLE_COLS, categoria, DEBUG_PATH)
        print(f"✓ {DEBUG_PATH} salvo")
        return 0
    except KeyboardInterrupt:
        print("Cancelado.")
        return 130
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Rodar todos os testes e ver todos passarem**

Run:
```bash
pytest tests/ -v
```
Expected: todos os testes passam (~25 total).

- [ ] **Step 5: Smoke test end-to-end com webcam real**

Aponta a webcam pra uma coisa verde (planta, papel, camiseta):
```bash
python medir_grama.py
```
Expected:
```
3...
2...
1...
snap!
Alturas: [XX, XX, XX] px
Mediana:  XX px → BAIXA|MÉDIA|ALTA
✓ debug/ultima_medicao.png salvo
```
Exit code 0. Abrir `debug/ultima_medicao.png` — deve ver o frame com 3 linhas vermelhas tracejadas e a categoria em amarelo no topo.

- [ ] **Step 6: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: main() orquestra o pipeline end-to-end"
```
