# Medição de grama por níveis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** substituir a classificação por `THRESHOLDS_PX` (altura do topo do verde em px) por classificação baseada em **3 linhas horizontais** (chão de referência + 2 separadoras BAIXA/MÉDIA e MÉDIA/ALTA), com categoria final = mediana dos níveis das 3 colunas amostradas.

**Architecture:** refactor local em 2 arquivos (`medir_grama.py`, `tests/test_medir_grama.py`). Estratégia: adicionar funções novas (`classify_column`, `classify_frame`, `measure_top_y`) de forma **aditiva** (coexistem com as antigas) → suite verde após cada task. No final, uma única task de **migração** troca `main()`, atualiza `save_debug`/`preview_camera`/`print_report`, remove funções e testes obsoletos.

**Tech Stack:** Python 3, OpenCV (`cv2`), NumPy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-12-medicao-por-niveis-design.md`

---

### Task 1: Baseline — confirmar suite atual passando

**Files:** nenhum

- [ ] **Step 1: Rodar suite atual**

Run: `pytest tests/ -v`
Expected: **32 passed**. Se qualquer teste falhar, PARAR e investigar — o refactor assume baseline verde.

---

### Task 2: Adicionar constantes `LINE_FRACTIONS` e `LEVEL_NAMES`

**Files:**
- Modify: `medir_grama.py` (bloco `# --- Configurações` no topo)

- [ ] **Step 1: Adicionar as novas constantes**

Em `medir_grama.py`, logo depois da linha `THRESHOLDS_PX = (40, 90)`, adicionar:

```python
# Linhas horizontais como % da altura do frame (baixo → cima).
# Índice 0 = chão de referência (só visual); 1 = separador BAIXA/MÉDIA; 2 = separador MÉDIA/ALTA.
LINE_FRACTIONS = (0.90, 0.60, 0.35)
LEVEL_NAMES = ("AUSENTE", "BAIXA", "MÉDIA", "ALTA")
```

`THRESHOLDS_PX` **fica** — será removido na Task 6.

- [ ] **Step 2: Rodar testes pra garantir baseline**

Run: `pytest tests/ -v`
Expected: **32 passed**.

- [ ] **Step 3: Commit**

```bash
git add medir_grama.py
git commit -m "feat: adiciona LINE_FRACTIONS e LEVEL_NAMES pra classificação por níveis"
```

---

### Task 3: Implementar `classify_column()` via TDD

**Files:**
- Modify: `tests/test_medir_grama.py`
- Modify: `medir_grama.py`

- [ ] **Step 1: Escrever os testes (falham primeiro)**

Em `tests/test_medir_grama.py`, adicionar depois do último teste do bloco `# --- classify` (linha 30, antes de `# --- measure_heights`):

```python
# --- classify_column ---------------------------------------------------------
# Frame de referência: altura 480 → chão y=432, sep1 y=288, sep2 y=168.

def test_classify_column_none_is_ausente():
    assert medir_grama.classify_column(None, 480, (0.90, 0.60, 0.35)) == 0


def test_classify_column_below_sep1_is_baixa():
    # y_topo=400 está abaixo de sep1(288) → BAIXA
    assert medir_grama.classify_column(400, 480, (0.90, 0.60, 0.35)) == 1


def test_classify_column_exactly_at_sep1_is_media():
    # borda: y_topo == sep1 → conta como atingiu → MÉDIA
    assert medir_grama.classify_column(288, 480, (0.90, 0.60, 0.35)) == 2


def test_classify_column_between_sep1_and_sep2_is_media():
    assert medir_grama.classify_column(220, 480, (0.90, 0.60, 0.35)) == 2


def test_classify_column_exactly_at_sep2_is_alta():
    assert medir_grama.classify_column(168, 480, (0.90, 0.60, 0.35)) == 3


def test_classify_column_above_sep2_is_alta():
    assert medir_grama.classify_column(50, 480, (0.90, 0.60, 0.35)) == 3


def test_classify_column_at_top_is_alta():
    assert medir_grama.classify_column(0, 480, (0.90, 0.60, 0.35)) == 3
```

- [ ] **Step 2: Rodar testes pra ver falhar**

Run: `pytest tests/test_medir_grama.py -v -k classify_column`
Expected: FAIL com `AttributeError: module 'medir_grama' has no attribute 'classify_column'`.

- [ ] **Step 3: Implementar a função**

Em `medir_grama.py`, adicionar depois de `classify()` (linha ~135):

```python
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
```

- [ ] **Step 4: Rodar testes pra passar**

Run: `pytest tests/test_medir_grama.py -v -k classify_column`
Expected: **7 passed**.

- [ ] **Step 5: Rodar suite completa**

Run: `pytest tests/ -v`
Expected: **39 passed** (32 antigos + 7 novos).

- [ ] **Step 6: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: classify_column() classifica coluna em nível 0-3"
```

---

### Task 4: Implementar `classify_frame()` via TDD

**Files:**
- Modify: `tests/test_medir_grama.py`
- Modify: `medir_grama.py`

- [ ] **Step 1: Escrever os testes**

Em `tests/test_medir_grama.py`, adicionar depois do bloco de `classify_column`:

```python
# --- classify_frame ----------------------------------------------------------
def test_classify_frame_all_baixa_returns_baixa():
    result = medir_grama.classify_frame([400, 400, 400], 480, (0.90, 0.60, 0.35))
    assert result == (1, "BAIXA")


def test_classify_frame_mediana_between_niveis():
    # (1, 2, 3) → mediana = 2 → MÉDIA
    result = medir_grama.classify_frame([400, 220, 50], 480, (0.90, 0.60, 0.35))
    assert result == (2, "MÉDIA")


def test_classify_frame_all_ausente_returns_ausente():
    result = medir_grama.classify_frame([None, None, None], 480, (0.90, 0.60, 0.35))
    assert result == (0, "AUSENTE")


def test_classify_frame_mixed_ausente_and_baixa():
    # (0, 0, 1) → mediana = 0 → AUSENTE
    result = medir_grama.classify_frame([None, None, 400], 480, (0.90, 0.60, 0.35))
    assert result == (0, "AUSENTE")


def test_classify_frame_all_alta_returns_alta():
    result = medir_grama.classify_frame([50, 100, 150], 480, (0.90, 0.60, 0.35))
    assert result == (3, "ALTA")
```

- [ ] **Step 2: Rodar testes pra ver falhar**

Run: `pytest tests/test_medir_grama.py -v -k classify_frame`
Expected: FAIL com `AttributeError`.

- [ ] **Step 3: Implementar a função**

Em `medir_grama.py`, adicionar depois de `classify_column()`:

```python
def classify_frame(top_ys: list[int | None], altura_frame: int,
                   line_fractions: tuple[float, ...]) -> tuple[int, str]:
    """Combina os níveis das colunas via mediana. Retorna (nivel, nome)."""
    niveis = [classify_column(y, altura_frame, line_fractions) for y in top_ys]
    nivel_final = int(np.median(niveis))
    return nivel_final, LEVEL_NAMES[nivel_final]
```

- [ ] **Step 4: Rodar testes pra passar**

Run: `pytest tests/test_medir_grama.py -v -k classify_frame`
Expected: **5 passed**.

- [ ] **Step 5: Rodar suite completa**

Run: `pytest tests/ -v`
Expected: **44 passed**.

- [ ] **Step 6: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: classify_frame() agrega colunas via mediana e retorna categoria"
```

---

### Task 5: Implementar `measure_top_y()` via TDD (aditivo, `measure_heights` fica)

**Files:**
- Modify: `tests/test_medir_grama.py`
- Modify: `medir_grama.py`

Nova função retorna `list[int | None]` — Y do primeiro pixel verde de cima ou None. Coexiste com `measure_heights` (que só será removida na Task 6).

- [ ] **Step 1: Escrever os testes**

Em `tests/test_medir_grama.py`, adicionar depois do bloco de `# --- measure_heights` existente (linha ~64):

```python
# --- measure_top_y -----------------------------------------------------------
def test_measure_top_y_all_columns_have_grass():
    mask = np.zeros((100, 100), np.uint8)
    mask[60:100, 25] = 255  # topo y=60
    mask[30:100, 50] = 255  # topo y=30
    mask[80:100, 75] = 255  # topo y=80
    result = medir_grama.measure_top_y(mask, (0.25, 0.50, 0.75))
    assert result == [60, 30, 80]


def test_measure_top_y_empty_mask_returns_all_none():
    mask = np.zeros((100, 100), np.uint8)
    result = medir_grama.measure_top_y(mask, (0.25, 0.50, 0.75))
    assert result == [None, None, None]


def test_measure_top_y_column_without_green_returns_none_for_that_column():
    mask = np.zeros((100, 100), np.uint8)
    mask[50:100, 25] = 255  # só a coluna 25% tem verde
    result = medir_grama.measure_top_y(mask, (0.25, 0.50, 0.75))
    assert result == [50, None, None]


def test_measure_top_y_returns_ints_not_numpy_scalars():
    mask = np.zeros((100, 100), np.uint8)
    mask[70:100, 50] = 255
    result = medir_grama.measure_top_y(mask, (0.50,))
    assert isinstance(result[0], int)
```

- [ ] **Step 2: Rodar testes pra ver falhar**

Run: `pytest tests/test_medir_grama.py -v -k measure_top_y`
Expected: FAIL com `AttributeError`.

- [ ] **Step 3: Implementar a função**

Em `medir_grama.py`, adicionar depois de `measure_heights()` (linha ~125):

```python
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
```

- [ ] **Step 4: Rodar testes pra passar**

Run: `pytest tests/test_medir_grama.py -v -k measure_top_y`
Expected: **4 passed**.

- [ ] **Step 5: Rodar suite completa**

Run: `pytest tests/ -v`
Expected: **48 passed**.

- [ ] **Step 6: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: measure_top_y() retorna y_topo|None de cada coluna"
```

---

### Task 6: Migração — troca `main()`, refactora `save_debug`/`preview_camera`/`print_report`, remove obsoletos

**Files:**
- Modify: `medir_grama.py`
- Modify: `tests/test_medir_grama.py`

Task grande mas atômica: atualiza tudo que muda assinatura + `main()` + remove antigas em um único commit pra manter a suite verde na virada. Ao final: 32 originais - 6 (classify) - 4 (measure_heights) - 3 (save_debug) - 1 (print_report) + 3 (save_debug novos) + 2 (print_report novos) + 16 (classify_column + classify_frame + measure_top_y das tasks 3-5) = **39 testes**.

- [ ] **Step 1: Atualizar testes de `save_debug` (novas assinaturas)**

Em `tests/test_medir_grama.py`, substituir o bloco `# --- save_debug` (linhas 224-253 do arquivo original) inteiro por:

```python
# --- save_debug --------------------------------------------------------------
def test_save_debug_creates_png_file(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "out.png"
    medir_grama.save_debug(
        frame, mask, [200, 220, 210], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 2, "MÉDIA", str(out),
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_save_debug_creates_parent_directory(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "sub" / "dir" / "out.png"
    medir_grama.save_debug(
        frame, mask, [None, None, None], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 0, "AUSENTE", str(out),
    )
    assert out.exists()


def test_save_debug_does_not_raise_on_write_failure(tmp_path, capsys, monkeypatch):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    monkeypatch.setattr(medir_grama.cv2, "imwrite", lambda *a, **kw: False)
    medir_grama.save_debug(
        frame, mask, [400, 400, 400], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 1, "BAIXA", str(tmp_path / "x.png"),
    )
    assert "AVISO" in capsys.readouterr().err
```

- [ ] **Step 2: Atualizar teste de `print_report` (nova assinatura)**

Em `tests/test_medir_grama.py`, substituir o bloco `# --- print_report` (linhas 140-147 do arquivo original) inteiro por:

```python
# --- print_report ------------------------------------------------------------
def test_print_report_contains_top_ys_niveis_and_categoria(capsys):
    medir_grama.print_report([300, 220, 180], [1, 2, 2], "MÉDIA")
    out = capsys.readouterr().out
    assert "300" in out
    assert "220" in out
    assert "180" in out
    assert "MÉDIA" in out


def test_print_report_handles_none_top_ys(capsys):
    medir_grama.print_report([None, None, None], [0, 0, 0], "AUSENTE")
    out = capsys.readouterr().out
    assert "AUSENTE" in out
    assert "None" in out
```

- [ ] **Step 3: Remover testes obsoletos**

Em `tests/test_medir_grama.py`:
1. Apagar o bloco `# --- classify` inteiro (linhas 8-30 do original: as 6 funções `test_classify_*`). Não confundir com `classify_column` / `classify_frame` — esses ficam.
2. Apagar o bloco `# --- measure_heights` inteiro (as 4 funções `test_measure_heights_*` do original). Os testes `measure_top_y` (adicionados na Task 5) ficam.

- [ ] **Step 4: Refatorar `preview_camera` em `medir_grama.py`**

Substituir a assinatura e o corpo inteiro de `preview_camera` (linhas 57-96) por:

```python
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
        line_colors = [(255, 255, 255), (0, 200, 200), (0, 140, 255)]
        line_labels = ["chão", "-> MÉDIA", "-> ALTA"]
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
                                 line_colors[i], 1)
                else:
                    cv2.line(display, (0, y), (largura_frame, y), line_colors[i], 1)
                cv2.putText(
                    display, line_labels[i], (5, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, line_colors[i], 1,
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
```

- [ ] **Step 5: Refatorar `print_report` em `medir_grama.py`**

Substituir a função `print_report` inteira (3 linhas do corpo original) por:

```python
def print_report(top_ys: list[int | None], niveis: list[int], categoria: str) -> None:
    print(f"y_topo por coluna: {top_ys}")
    print(f"níveis por coluna: {niveis}")
    print(f"Categoria: {categoria}")
```

- [ ] **Step 6: Refatorar `save_debug` em `medir_grama.py`**

Substituir a função `save_debug` inteira (linhas 142-181) por:

```python
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

        line_colors = [(255, 255, 255), (0, 200, 200), (0, 140, 255)]
        line_labels = ["chão", "-> MÉDIA", "-> ALTA"]
        idx_destacada = None
        if nivel_final == 2:
            idx_destacada = 1
        elif nivel_final == 3:
            idx_destacada = 2

        for i, frac in enumerate(line_fractions):
            y = int(altura_frame * frac)
            if i == 0:
                for x in range(0, largura_frame, 14):
                    cv2.line(annotated, (x, y), (min(x + 8, largura_frame), y),
                             line_colors[i], 1)
            else:
                cv2.line(annotated, (0, y), (largura_frame, y), line_colors[i], 1)
            cv2.putText(
                annotated, line_labels[i], (5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, line_colors[i], 1,
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
```

- [ ] **Step 7: Refatorar `main()` em `medir_grama.py`**

Substituir a função `main` inteira (linhas 184-207) por:

```python
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
```

- [ ] **Step 8: Remover `classify()`, `measure_heights()` e `THRESHOLDS_PX`**

Em `medir_grama.py`:
1. Apagar a linha `THRESHOLDS_PX = (40, 90)` no topo.
2. Apagar a função `classify()` inteira (7 linhas do corpo original).
3. Apagar a função `measure_heights()` inteira (13 linhas do corpo original).

- [ ] **Step 9: Grep pra confirmar que sumiram**

Run: `grep -nE "THRESHOLDS_PX|def classify\(|def measure_heights" medir_grama.py tests/test_medir_grama.py`
Expected: **nenhum resultado** (grep sai com exit code 1 se não encontra — ok). Se algo aparecer, remover.

- [ ] **Step 10: Rodar suite completa**

Run: `pytest tests/ -v`
Expected: **39 passed**. Qualquer falha PARAR e investigar. Os 3 testes de `main` mockam `preview_camera` com `lambda *a, **kw: True`, então o novo parâmetro `line_fractions` é aceito sem mudanças.

- [ ] **Step 11: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "$(cat <<'EOF'
refactor: main() usa classify_frame + measure_top_y

- save_debug e preview_camera aceitam line_fractions; save_debug destaca
  a maior linha atingida em verde grosso
- print_report imprime y_topo e níveis por coluna
- remove classify(), measure_heights() e THRESHOLDS_PX
EOF
)"
```

---

### Task 7: Smoke test manual (usuário roda)

**Files:** nenhum

- [ ] **Step 1: Rodar o script com webcam**

Run: `python medir_grama.py`

Expected:
1. Janela de preview abre com: overlay verde da máscara, 3 verticais amarelas (colunas), 3 horizontais (chão branco tracejado, sep 1 amarelo, sep 2 laranja), labels `chão / -> MÉDIA / -> ALTA` na esquerda, rodapé `SPACE=capturar ESC=cancelar`.
2. Ao apertar SPACE: countdown `3... 2... 1... snap!`, captura 5 frames.
3. Terminal imprime `y_topo por coluna: [...]`, `níveis por coluna: [...]`, `Categoria: BAIXA/MÉDIA/ALTA/AUSENTE`.
4. Mensagem final: `OK: debug/ultima_medicao.png salvo`.

- [ ] **Step 2: Abrir o PNG salvo e conferir**

Abrir `debug/ultima_medicao.png` e verificar:
- 3 linhas horizontais visíveis com labels.
- Se categoria = MÉDIA ou ALTA: uma linha verde grossa em cima do separador atingido.
- Se categoria = BAIXA ou AUSENTE: nenhuma linha verde grossa destacada.
- Texto grande da categoria centralizado no topo.
- Sem as verticais tracejadas vermelhas antigas.

- [ ] **Step 3: Reportar ao usuário**

Se a categoria não corresponder à posição visual do topo do verde no preview, ajustar `LINE_FRACTIONS` (defaults `(0.90, 0.60, 0.35)`) no topo de `medir_grama.py` e re-rodar.
