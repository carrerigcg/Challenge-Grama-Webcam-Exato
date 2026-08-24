# Legenda Colorida + Margem de Erro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar legenda multicolorida no preview (com AUSENTE + faixa inferior da BAIXA), bolinhas coloridas por categoria no PNG debug, e margem de erro `± cm` no output do console e no título do PNG.

**Architecture:** 3 mudanças coordenadas em `medir_grama.py` — 1 constante nova (`LEVEL_COLORS_BGR`), 1 função pura nova (`margem_erro_cm`), 2 helpers de formatação/desenho (`_formatar_mediana_com_margem`, `_draw_legenda_niveis`), assinaturas de `print_report` e `save_debug` estendidas com `margem_cm`, `save_debug` passa a colorir bolinha por categoria via `classify_cm`. Sem mudança de arquitetura — tudo continua num arquivo só.

**Tech Stack:** Python 3, OpenCV (`cv2`), NumPy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-legenda-e-margem-erro-design.md`

---

## File Structure

**Modificados:**
- `medir_grama.py` — adiciona constante `LEVEL_COLORS_BGR`, funções `margem_erro_cm`, `_formatar_mediana_com_margem`, `_draw_legenda_niveis`; estende assinaturas `print_report(alturas, mediana, **margem**, categoria)` e `save_debug(..., altura_mediana, **margem**, col_fractions, ...)`; substitui `putText` da legenda em `preview_camera`; colore bolinha em `save_debug`; passa `margem` no `main()`.
- `tests/test_medir_grama.py` — atualiza chamadas existentes de `print_report` e `save_debug` pra incluir `margem_cm`; adiciona blocos de testes novos.

**Sem criação de arquivos novos.**

---

## Task 1: Constante LEVEL_COLORS_BGR + função `margem_erro_cm`

**Files:**
- Modify: `medir_grama.py` (adiciona constante perto de `LEVEL_NAMES` na linha 19; adiciona função nova junto às outras funções puras, antes de `_formatar_cm` na linha 238)
- Test: `tests/test_medir_grama.py` (novo bloco `# --- margem_erro_cm`)

- [ ] **Step 1: Write failing tests**

Adicionar ao final de `tests/test_medir_grama.py` (antes do bloco `# --- capture_frames` ou no final do arquivo, tanto faz — pytest não liga pra ordem):

```python
# --- margem_erro_cm ----------------------------------------------------------
def test_margem_erro_cm_lista_vazia_returns_none():
    assert medir_grama.margem_erro_cm([]) is None


def test_margem_erro_cm_uma_valida_returns_none():
    assert medir_grama.margem_erro_cm([2.0]) is None


def test_margem_erro_cm_uma_valida_com_nones_returns_none():
    assert medir_grama.margem_erro_cm([2.0, None, None]) is None


def test_margem_erro_cm_duas_validas_returns_metade_da_amplitude():
    # (4.0 - 2.0) / 2 = 1.0
    assert medir_grama.margem_erro_cm([2.0, 4.0]) == 1.0


def test_margem_erro_cm_tres_validas_ignora_ordem():
    # (4.0 - 2.0) / 2 = 1.0, independente da ordem
    assert medir_grama.margem_erro_cm([2.0, 3.0, 4.0]) == 1.0
    assert medir_grama.margem_erro_cm([4.0, 2.0, 3.0]) == 1.0


def test_margem_erro_cm_todas_iguais_returns_zero():
    assert medir_grama.margem_erro_cm([3.0, 3.0, 3.0]) == 0.0


def test_margem_erro_cm_ignora_none_no_calculo():
    # Só 2.0 e 4.0 contam → (4-2)/2 = 1.0
    assert medir_grama.margem_erro_cm([None, 2.0, 4.0, None]) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_medir_grama.py -v -k margem_erro_cm`
Expected: FAIL com `AttributeError: module 'medir_grama' has no attribute 'margem_erro_cm'`

- [ ] **Step 3: Adicionar constante `LEVEL_COLORS_BGR`**

Em `medir_grama.py`, logo após a linha 19 (`LEVEL_NAMES = ...`), adicionar:

```python
# Cores BGR (OpenCV) por nível — usado na legenda do preview e nas bolinhas do PNG.
LEVEL_COLORS_BGR = (
    (150, 150, 150),  # AUSENTE — cinza
    (0, 255, 0),      # BAIXA — verde
    (0, 255, 255),    # MÉDIA — amarelo
    (0, 0, 255),      # ALTA — vermelho
)
```

- [ ] **Step 4: Implementar `margem_erro_cm`**

Em `medir_grama.py`, adicionar antes de `_formatar_cm` (linha 238):

```python
def margem_erro_cm(alturas_cm: list[float | None]) -> float | None:
    """Metade da amplitude (max - min) das alturas válidas em cm.

    None se menos de 2 colunas válidas. 0.0 se todas iguais.
    """
    validas = [a for a in alturas_cm if a is not None]
    if len(validas) < 2:
        return None
    return (max(validas) - min(validas)) / 2.0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_medir_grama.py -v -k margem_erro_cm`
Expected: PASS (7 testes)

- [ ] **Step 6: Rodar suíte completa pra garantir que nada quebrou**

Run: `pytest tests/test_medir_grama.py -v`
Expected: todos os testes anteriores continuam PASS + 7 novos PASS.

- [ ] **Step 7: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: adiciona LEVEL_COLORS_BGR e margem_erro_cm"
```

---

## Task 2: Helper `_formatar_mediana_com_margem`

**Files:**
- Modify: `medir_grama.py` (adiciona helper logo após `_formatar_cm`, ~linha 242)
- Test: `tests/test_medir_grama.py` (novo bloco)

- [ ] **Step 1: Write failing tests**

Adicionar em `tests/test_medir_grama.py`:

```python
# --- _formatar_mediana_com_margem --------------------------------------------
def test_formatar_mediana_com_margem_mediana_none_returns_placeholder():
    assert medir_grama._formatar_mediana_com_margem(None, None) == "—"
    assert medir_grama._formatar_mediana_com_margem(None, 0.4) == "—"


def test_formatar_mediana_com_margem_sem_margem_mostra_placeholder():
    assert medir_grama._formatar_mediana_com_margem(2.8, None) == "2,8 cm ± —"


def test_formatar_mediana_com_margem_com_valor():
    assert medir_grama._formatar_mediana_com_margem(2.8, 0.4) == "2,8 cm ± 0,4 cm"


def test_formatar_mediana_com_margem_zero_ainda_imprime_zero():
    assert medir_grama._formatar_mediana_com_margem(3.0, 0.0) == "3,0 cm ± 0,0 cm"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_medir_grama.py -v -k formatar_mediana_com_margem`
Expected: FAIL com `AttributeError`.

- [ ] **Step 3: Implementar `_formatar_mediana_com_margem`**

Em `medir_grama.py`, logo após `_formatar_cm` (linha 242):

```python
def _formatar_mediana_com_margem(
    mediana: float | None, margem: float | None
) -> str:
    """Formata mediana + margem. Ex.: '2,8 cm ± 0,4 cm' | '2,8 cm ± —' | '—'."""
    if mediana is None:
        return "—"
    if margem is None:
        return f"{_formatar_cm(mediana)} ± —"
    return f"{_formatar_cm(mediana)} ± {_formatar_cm(margem)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_medir_grama.py -v -k formatar_mediana_com_margem`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: adiciona _formatar_mediana_com_margem"
```

---

## Task 3: Estender `print_report` com `margem_cm`

**Files:**
- Modify: `medir_grama.py:245-253` (função `print_report`)
- Modify: `tests/test_medir_grama.py:260-273` (testes existentes de `print_report`)

- [ ] **Step 1: Atualizar testes existentes de `print_report` pra passar margem**

Substituir os testes `test_print_report_contains_alturas_mediana_e_categoria` e `test_print_report_handles_none_alturas` em `tests/test_medir_grama.py`:

```python
def test_print_report_contains_alturas_mediana_e_categoria(capsys):
    medir_grama.print_report([5.2, 6.1, 5.5], 5.5, 0.45, "MÉDIA")
    out = capsys.readouterr().out
    assert "5,2 cm" in out
    assert "6,1 cm" in out
    assert "5,5 cm" in out
    assert "MÉDIA" in out


def test_print_report_handles_none_alturas(capsys):
    medir_grama.print_report([None, None, None], None, None, "AUSENTE")
    out = capsys.readouterr().out
    assert "AUSENTE" in out
    assert "—" in out  # placeholder pra None


def test_print_report_com_margem_imprime_no_output(capsys):
    medir_grama.print_report([2.5, 3.0, 3.5], 3.0, 0.5, "BAIXA")
    out = capsys.readouterr().out
    assert "3,0 cm ± 0,5 cm" in out


def test_print_report_sem_margem_imprime_placeholder(capsys):
    medir_grama.print_report([2.5, None, None], 2.5, None, "BAIXA")
    out = capsys.readouterr().out
    assert "2,5 cm ± —" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_medir_grama.py -v -k print_report`
Expected: FAIL com `TypeError: print_report() takes 3 positional arguments but 4 were given` (ou similar).

- [ ] **Step 3: Atualizar assinatura de `print_report` em `medir_grama.py`**

Substituir lines 245-253 de `medir_grama.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_medir_grama.py -v -k print_report`
Expected: PASS (4 testes).

- [ ] **Step 5: Rodar suíte completa — vai quebrar `main()` porque ele ainda chama `print_report` com 3 args**

Run: `pytest tests/test_medir_grama.py -v`
Expected: FAIL nos testes de `main()` (`test_main_success_returns_zero`, `test_main_reports_altura_em_cm`, `test_main_no_green_detected_still_returns_zero_with_warning`) porque `main()` chama `print_report(alturas_cm, altura_mediana, categoria)` — sem margem.

Isso é OK — vamos consertar no Task 6. Prosseguir mesmo com falhas de `main`.

- [ ] **Step 6: Commit (com o débito conhecido em `main()`)**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: print_report aceita margem_cm

Testes de main() ficam quebrados temporariamente ate Task 6 atualizar
a chamada em main() pra passar a margem."
```

---

## Task 4: Helper `_draw_legenda_niveis` + integração em `preview_camera`

**Files:**
- Modify: `medir_grama.py:136-206` (função `preview_camera` — substitui linhas 149-153 e 189-192)
- Modify: `medir_grama.py` (adiciona helper novo antes de `preview_camera`, ~linha 135)
- Test: `tests/test_medir_grama.py` (bloco novo)

- [ ] **Step 1: Write failing test**

Adicionar em `tests/test_medir_grama.py`:

```python
# --- _draw_legenda_niveis ----------------------------------------------------
def test_draw_legenda_niveis_modifica_imagem():
    """Smoke test: desenhar em preto deve deixar algum pixel != 0."""
    img = np.zeros((60, 800, 3), np.uint8)
    medir_grama._draw_legenda_niveis(img, 3.0, 7.0)
    assert (img > 0).any(), "esperava pixels desenhados na imagem"


def test_draw_legenda_niveis_usa_todas_cores_dos_niveis():
    """Cada uma das 4 cores de nível deve aparecer na imagem."""
    img = np.zeros((60, 800, 3), np.uint8)
    medir_grama._draw_legenda_niveis(img, 3.0, 7.0)
    # Confere que cada cor BGR aparece em pelo menos 1 pixel.
    for cor in medir_grama.LEVEL_COLORS_BGR:
        b, g, r = cor
        match = (img[:, :, 0] == b) & (img[:, :, 1] == g) & (img[:, :, 2] == r)
        assert match.any(), f"cor {cor} nao aparece na legenda"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_medir_grama.py -v -k draw_legenda_niveis`
Expected: FAIL com `AttributeError: module 'medir_grama' has no attribute '_draw_legenda_niveis'`.

- [ ] **Step 3: Implementar `_draw_legenda_niveis`**

Em `medir_grama.py`, adicionar antes de `preview_camera` (linha 136):

```python
def _draw_legenda_niveis(
    img: np.ndarray,
    faixa_baixa: float,
    faixa_media: float,
    x_inicial: int = 10,
    y: int = 22,
) -> None:
    """Desenha a legenda multicolorida no topo da imagem.

    Cada nível é desenhado na sua cor (LEVEL_COLORS_BGR), separadores em branco.
    """
    branco = (255, 255, 255)
    fonte = cv2.FONT_HERSHEY_SIMPLEX
    escala = 0.55
    espessura = 1
    segmentos = [
        ("AUSENTE", LEVEL_COLORS_BGR[0]),
        (" | ", branco),
        (f"BAIXA (0-{faixa_baixa:g}cm)", LEVEL_COLORS_BGR[1]),
        (" | ", branco),
        (f"MEDIA ({faixa_baixa:g}-{faixa_media:g}cm)", LEVEL_COLORS_BGR[2]),
        (" | ", branco),
        (f"ALTA (>{faixa_media:g}cm)", LEVEL_COLORS_BGR[3]),
    ]
    x = x_inicial
    for texto, cor in segmentos:
        cv2.putText(img, texto, (x, y), fonte, escala, cor, espessura)
        (w, _), _ = cv2.getTextSize(texto, fonte, escala, espessura)
        x += w
```

- [ ] **Step 4: Substituir a legenda velha em `preview_camera`**

Em `medir_grama.py`, remover linhas 149-153 (variável local `legenda`):

```python
    legenda = (
        f"BAIXA <= {faixa_baixa:g}cm | "
        f"MEDIA <= {faixa_media:g}cm | "
        f"ALTA > {faixa_media:g}cm"
    )
```

E substituir linhas 189-192 (o `cv2.putText` que desenhava `legenda`):

```python
            cv2.putText(
                display, legenda, (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
            )
```

por:

```python
            _draw_legenda_niveis(display, faixa_baixa, faixa_media)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_medir_grama.py -v -k draw_legenda_niveis`
Expected: PASS (2 testes).

- [ ] **Step 6: Rodar suíte completa (main ainda quebrado, mas nada regredindo)**

Run: `pytest tests/test_medir_grama.py -v`
Expected: mesmos testes de `main()` continuam falhando por causa do débito do Task 3, mas nenhum teste NOVO quebrou.

- [ ] **Step 7: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: legenda multicolorida no preview

Substitui o cv2.putText unico da legenda por _draw_legenda_niveis,
que desenha cada nivel na sua cor de categoria (AUSENTE cinza,
BAIXA verde, MEDIA amarelo, ALTA vermelho) e mostra a faixa em cm."
```

---

## Task 5: Estender `save_debug` com `margem_cm` + bolinha colorida por categoria

**Files:**
- Modify: `medir_grama.py:256-314` (função `save_debug`)
- Modify: `tests/test_medir_grama.py:351-429` (testes existentes de `save_debug`)

- [ ] **Step 1: Atualizar testes existentes de `save_debug` pra passar `margem_cm`**

Em `tests/test_medir_grama.py`, adicionar `margem_cm=...` (com o valor apropriado) em cada chamada de `save_debug` dos testes existentes:

Em `test_save_debug_creates_png_file` (linhas 351-367): adicionar `margem_cm=1.25` após `altura_mediana_cm=26.25`.

Em `test_save_debug_creates_parent_directory` (linhas 370-383): adicionar `margem_cm=None` após `altura_mediana_cm=None`.

Em `test_save_debug_does_not_raise_on_write_failure` (linhas 386-399): adicionar `margem_cm=0.0` após `altura_mediana_cm=2.5`.

Em `test_save_debug_desenha_linha_do_chao_branca` (linhas 402-429): adicionar `margem_cm=0.0` após `altura_mediana_cm=15.0`.

- [ ] **Step 2: Adicionar teste novo pra bolinha colorida por categoria**

Adicionar após `test_save_debug_desenha_linha_do_chao_branca`:

```python
def test_save_debug_bolinha_colorida_por_categoria(tmp_path, monkeypatch):
    """Cada coluna deve ter bolinha desenhada com a cor da sua categoria."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    circles = []
    original_circle = medir_grama.cv2.circle

    def spy(img, center, radius, color, thickness, *a, **kw):
        circles.append((center, color))
        return original_circle(img, center, radius, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "circle", spy)
    # Alturas: 2,5cm (BAIXA), 5,0cm (MÉDIA), 10,0cm (ALTA) com faixas 3/7
    medir_grama.save_debug(
        frame, mask,
        top_ys=[400, 380, 340],
        alturas_cm=[2.5, 5.0, 10.0],
        altura_mediana_cm=5.0,
        margem_cm=3.75,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="MÉDIA",
        path=str(tmp_path / "c.png"),
    )
    cores = [color for _, color in circles]
    assert (0, 255, 0) in cores      # BAIXA — verde
    assert (0, 255, 255) in cores    # MÉDIA — amarelo
    assert (0, 0, 255) in cores      # ALTA — vermelho


def test_save_debug_titulo_contem_margem(tmp_path, monkeypatch):
    """O texto grande no topo deve incluir a margem ± cm."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    textos = []
    original_putText = medir_grama.cv2.putText

    def spy(img, text, org, font, scale, color, thickness, *a, **kw):
        textos.append(text)
        return original_putText(img, text, org, font, scale, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "putText", spy)
    medir_grama.save_debug(
        frame, mask,
        top_ys=[400, 400, 400],
        alturas_cm=[2.5, 2.5, 2.5],
        altura_mediana_cm=2.5,
        margem_cm=0.3,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="BAIXA",
        path=str(tmp_path / "t.png"),
    )
    juntos = " ".join(textos)
    assert "2,5 cm ± 0,3 cm" in juntos
    assert "BAIXA" in juntos
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_medir_grama.py -v -k save_debug`
Expected: FAIL em `test_save_debug_bolinha_colorida_por_categoria` (todas as bolinhas ainda verdes), `test_save_debug_titulo_contem_margem` (título ainda sem margem), e possivelmente os antigos porque `save_debug` ainda não aceita `margem_cm`.

- [ ] **Step 4: Atualizar `save_debug` — assinatura + título + bolinha colorida**

Em `medir_grama.py`, substituir a função `save_debug` inteira (linhas 256-314) por:

```python
def save_debug(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    top_ys: list[int | None],
    alturas_cm: list[float | None],
    altura_mediana_cm: float | None,
    margem_cm: float | None,
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

        # Colunas verticais + marca do topo colorida pela categoria + label
        for frac, y_topo, altura in zip(col_fractions, top_ys, alturas_cm):
            x = int(largura_frame * frac)
            cv2.line(annotated, (x, 0), (x, altura_frame), (0, 255, 255), 1)
            if y_topo is not None:
                nivel_col, _ = classify_cm(altura, FAIXA_BAIXA_CM, FAIXA_MEDIA_CM)
                cor = LEVEL_COLORS_BGR[nivel_col]
                cv2.circle(annotated, (x, y_topo), 5, cor, -1)
                label = _formatar_cm(altura)
                cv2.putText(
                    annotated, label, (x + 8, y_topo - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, cor, 1,
                )

        # Régua vertical de referência no canto direito (marcas 1 em 1 cm até 10)
        _desenhar_regua(annotated, y_chao, px_por_cm, altura_frame, largura_frame)

        # Texto grande centralizado no topo: "X,X cm ± Y,Y cm — CATEGORIA"
        titulo = f"{_formatar_mediana_com_margem(altura_mediana_cm, margem_cm)} - {categoria}"
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_medir_grama.py -v -k save_debug`
Expected: PASS (6 testes — 4 antigos ajustados + 2 novos).

- [ ] **Step 6: Rodar suíte completa (main ainda quebrado)**

Run: `pytest tests/test_medir_grama.py -v`
Expected: só os testes de `main()` continuam falhando (débito conhecido do Task 3).

- [ ] **Step 7: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: save_debug aceita margem_cm e colore bolinha por categoria

Titulo grande no topo agora inclui '± X,X cm'. Bolinha e label de
cada coluna usam a cor da categoria daquela coluna (via classify_cm)
em vez do verde fixo. Assinatura ganhou margem_cm entre altura_mediana
e col_fractions."
```

---

## Task 6: Wire margem em `main()` + verde total

**Files:**
- Modify: `medir_grama.py:340-378` (função `main` — linhas 357-366)

- [ ] **Step 1: Atualizar `main()` pra calcular e passar `margem`**

Em `medir_grama.py`, substituir o bloco linhas 357-366:

```python
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
```

por:

```python
        nivel, categoria, altura_mediana = classify_frame_cm(
            alturas_cm, FAIXA_BAIXA_CM, FAIXA_MEDIA_CM,
        )
        margem = margem_erro_cm(alturas_cm)
        print_report(alturas_cm, altura_mediana, margem, categoria)
        if nivel == 0:
            print("AVISO: nenhuma grama detectada no frame", file=sys.stderr)
        save_debug(
            frames[-1], mask, top_ys, alturas_cm, altura_mediana, margem,
            SAMPLE_COLS, y_chao, px_por_cm, categoria, DEBUG_PATH,
        )
```

- [ ] **Step 2: Rodar suíte completa — tudo deve passar agora**

Run: `pytest tests/test_medir_grama.py -v`
Expected: TODOS os testes PASS (incluindo os de `main` que estavam falhando desde o Task 3). Verificar contagem: originais + novos de `margem_erro_cm` (7) + `_formatar_mediana_com_margem` (4) + `_draw_legenda_niveis` (2) + `print_report` novos (2) + `save_debug` novos (2) = **originais + 17 novos**.

- [ ] **Step 3: Sanity end-to-end — usar o teste existente pra confirmar `± cm` no output do `main`**

Adicionar ao final de `tests/test_medir_grama.py` (bloco `# --- main`):

```python
def test_main_output_inclui_margem_de_erro(monkeypatch, tmp_path, capsys):
    """End-to-end: output do main() deve conter '± ... cm' na linha da mediana."""
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    out = capsys.readouterr().out
    # _fake_green_frames tem verde uniforme → 3 colunas com mesma altura →
    # amplitude = 0 → margem = 0,0 cm
    assert "±" in out
    assert "0,0 cm" in out  # margem calculada
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_medir_grama.py -v`
Expected: TUDO PASS.

- [ ] **Step 5: Verificação manual (recomendada, não obrigatória)**

Se for possível rodar com uma webcam:
```
python medir_grama.py
```
Confirmar visualmente:
- Preview: legenda no topo em 4 cores (cinza/verde/amarelo/vermelho).
- Console: linha `Altura mediana:     X,X cm ± Y,Y cm`.
- `debug/ultima_medicao.png`: bolinhas com cores diferentes se colunas tiverem alturas diferentes; título grande com `± cm`.

Se não puder rodar com webcam, os testes de `main` cobrem o suficiente.

- [ ] **Step 6: Commit**

```bash
git add medir_grama.py tests/test_medir_grama.py
git commit -m "feat: main() calcula margem_erro_cm e passa para print_report/save_debug

Fecha a integracao: output do console e PNG debug agora sempre mostram
'± X,X cm' junto da mediana."
```

---

## Task 7: Verificação final do plano completo

- [ ] **Step 1: Rodar suíte inteira**

Run: `pytest tests/ -v`
Expected: TUDO PASS, sem warnings novos.

- [ ] **Step 2: `git log` das mudanças**

Run: `git log --oneline main..HEAD` (ou `git log --oneline -10` se estiver na `main`)
Expected: ver 6 commits — 1 por Task.

- [ ] **Step 3: Diff final consolidado**

Run: `git diff <hash-antes-task-1>..HEAD -- medir_grama.py tests/test_medir_grama.py`
Confirmar visualmente que:
- `LEVEL_COLORS_BGR` está definido.
- 3 funções novas: `margem_erro_cm`, `_formatar_mediana_com_margem`, `_draw_legenda_niveis`.
- `print_report` e `save_debug` têm `margem_cm` na assinatura.
- `preview_camera` usa `_draw_legenda_niveis`, variável local `legenda` sumiu.
- Bolinha em `save_debug` usa `LEVEL_COLORS_BGR[nivel_col]`.
- `main()` chama `margem_erro_cm` e passa pros dois consumidores.

Nada mais a fazer.
