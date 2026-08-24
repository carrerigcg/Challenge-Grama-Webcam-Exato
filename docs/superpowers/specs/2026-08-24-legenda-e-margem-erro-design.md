# Legenda colorida no preview + margem de erro no output

**Data:** 2026-08-24
**Escopo:** duas mudanças pequenas e independentes em `medir_grama.py`:
1. Legenda do preview passa a incluir `AUSENTE` e a faixa inferior da `BAIXA`, com cada nível colorido pela sua cor de categoria. Bolinha/label de cada coluna no PNG debug também passa a ser colorida por categoria.
2. Output (console e título do PNG debug) passa a mostrar margem de erro `± X,X cm` da mediana, calculada como dispersão entre as colunas amostradas.

## Motivação

- **Legenda:** hoje ela mostra só `BAIXA / MEDIA / ALTA` em branco, sem AUSENTE e sem indicar o piso da BAIXA (0 cm). Colorir cada label e alinhar com a cor da bolinha desenhada no PNG cria consistência visual entre "o que a legenda promete" e "o que a foto final mostra".
- **Margem de erro:** hoje o output entrega só a mediana pontual, o que dá falsa impressão de precisão. Com 3 colunas amostradas há uma dispersão natural (grama irregular + máscara HSV ruidosa) que precisa aparecer no output pra o usuário calibrar expectativa.

## Cores por categoria (BGR do OpenCV)

| Nível     | BGR             |
|-----------|-----------------|
| AUSENTE   | `(150, 150, 150)` (cinza) |
| BAIXA     | `(0, 255, 0)` (verde) |
| MÉDIA     | `(0, 255, 255)` (amarelo) |
| ALTA      | `(0, 0, 255)` (vermelho) |

Constante nova no topo de `medir_grama.py`, ao lado de `LEVEL_NAMES`:

```python
LEVEL_COLORS_BGR = (
    (150, 150, 150),  # AUSENTE
    (0, 255, 0),      # BAIXA
    (0, 255, 255),    # MÉDIA
    (0, 0, 255),      # ALTA
)
```

## Mudança 1 — Legenda colorida no preview

### Formato

Uma linha só no topo:
```
AUSENTE | BAIXA (0-3cm) | MEDIA (3-7cm) | ALTA (>7cm)
```

Cada label é desenhado na sua cor de categoria. O separador ` | ` é desenhado em branco.

### Mecânica

`cv2.putText` não colore substring dentro da mesma chamada. Solução: dividir o texto em segmentos e desenhar um por vez, medindo a largura de cada com `cv2.getTextSize` pra calcular o `x` inicial do próximo.

Função nova auxiliar:

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
    Não retorna nada — desenha in-place.
    """
```

Segmentos (ordem):
1. `"AUSENTE"` — cor `LEVEL_COLORS_BGR[0]`
2. `" | "` — branco
3. `f"BAIXA (0-{faixa_baixa:g}cm)"` — cor `LEVEL_COLORS_BGR[1]`
4. `" | "` — branco
5. `f"MEDIA ({faixa_baixa:g}-{faixa_media:g}cm)"` — cor `LEVEL_COLORS_BGR[2]`
6. `" | "` — branco
7. `f"ALTA (>{faixa_media:g}cm)"` — cor `LEVEL_COLORS_BGR[3]`

Fonte, escala e espessura idênticas à legenda atual: `FONT_HERSHEY_SIMPLEX`, `0.55`, `1`.

### Onde é chamada

Substituir o bloco atual dentro de `preview_camera` (linhas 189-192 do `medir_grama.py`):
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

A variável local `legenda` (linhas 149-153) é removida.

## Mudança 2 — Bolinha/label da coluna colorida por categoria (PNG debug)

Hoje `save_debug` desenha bolinha e label sempre em verde `(0, 255, 0)` (linhas 288 e 292 do `medir_grama.py`). Passa a colorir por categoria daquela coluna individualmente.

### Diff conceitual em `save_debug`

Dentro do loop `for frac, y_topo, altura in zip(col_fractions, top_ys, alturas_cm):`:

```python
if y_topo is not None:
    nivel_col, _ = classify_cm(altura, FAIXA_BAIXA_CM, FAIXA_MEDIA_CM)
    cor = LEVEL_COLORS_BGR[nivel_col]
    cv2.circle(annotated, (x, y_topo), 5, cor, -1)
    label = _formatar_cm(altura)
    cv2.putText(
        annotated, label, (x + 8, y_topo - 4),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, cor, 1,
    )
```

`save_debug` já tem acesso a `FAIXA_BAIXA_CM` / `FAIXA_MEDIA_CM` via constantes de módulo (usa o mesmo padrão que o resto do arquivo). Sem mudança de assinatura.

## Mudança 3 — Margem de erro no output

### Função nova

```python
def margem_erro_cm(alturas_cm: list[float | None]) -> float | None:
    """Metade da amplitude (max - min) das alturas válidas em cm.

    None se < 2 colunas válidas. 0.0 se todas iguais.
    """
    validas = [a for a in alturas_cm if a is not None]
    if len(validas) < 2:
        return None
    return (max(validas) - min(validas)) / 2.0
```

### Formatação

O helper existente `_formatar_cm` continua igual. Uma função nova pra o par mediana+margem:

```python
def _formatar_mediana_com_margem(
    mediana: float | None, margem: float | None
) -> str:
    """Ex.: '2,8 cm ± 0,4 cm' | '2,8 cm ± —' | '—'."""
    if mediana is None:
        return "—"
    if margem is None:
        return f"{_formatar_cm(mediana)} ± —"
    return f"{_formatar_cm(mediana)} ± {_formatar_cm(margem)}"
```

### Onde aparece

**Console** — `print_report` passa a receber `margem` e imprime:
```
Alturas por coluna: ['2,3 cm', '3,1 cm', '2,8 cm']
Altura mediana:     2,8 cm ± 0,4 cm
Categoria:          BAIXA
```

Nova assinatura:
```python
def print_report(
    alturas_cm: list[float | None],
    altura_mediana_cm: float | None,
    margem_cm: float | None,
    categoria: str,
) -> None:
```

Corpo: a linha `Alturas por coluna:` e `Categoria:` ficam iguais. A linha `Altura mediana:` passa a usar `_formatar_mediana_com_margem(altura_mediana_cm, margem_cm)` em vez de `_formatar_cm(altura_mediana_cm)`.

**PNG debug** — `save_debug` passa a receber `margem` e o título vira:
```
2,8 cm ± 0,4 cm - BAIXA
```

Nova assinatura (só adiciona `margem_cm` antes de `col_fractions`, mantém a ordem posicional dos outros):
```python
def save_debug(
    frame_bgr, mask, top_ys, alturas_cm, altura_mediana_cm,
    margem_cm,   # NOVO
    col_fractions, y_chao, px_por_cm, categoria, path,
) -> None:
```

O `titulo` (linha 299) passa a ser:
```python
titulo = f"{_formatar_mediana_com_margem(altura_mediana_cm, margem_cm)} - {categoria}"
```

### Categorização não muda

`classify_frame_cm` continua usando só a mediana, sem aviso de fronteira. A margem é puramente informativa no output.

## Fluxo `main()` — diff

Adicionar uma linha após a classificação (após linha 359) e passar `margem` pra `print_report` e `save_debug`:

```python
nivel, categoria, altura_mediana = classify_frame_cm(
    alturas_cm, FAIXA_BAIXA_CM, FAIXA_MEDIA_CM,
)
margem = margem_erro_cm(alturas_cm)                   # NOVO
print_report(alturas_cm, altura_mediana, margem, categoria)  # +margem
if nivel == 0:
    print("AVISO: nenhuma grama detectada no frame", file=sys.stderr)
save_debug(
    frames[-1], mask, top_ys, alturas_cm, altura_mediana,
    margem,                                            # NOVO
    SAMPLE_COLS, y_chao, px_por_cm, categoria, DEBUG_PATH,
)
```

## Testes (`tests/test_medir_grama.py`)

| Bloco | Ação |
|-------|------|
| `margem_erro_cm` — novos | 5 casos mínimos: `[]` → None; `[2.0]` → None (só 1 válida); `[2.0, None]` → None; `[2.0, 4.0]` → 1.0; `[2.0, 3.0, 4.0]` → 1.0; `[3.0, 3.0, 3.0]` → 0.0. |
| `_formatar_mediana_com_margem` — novos | 3 casos: `(None, ...)` → "—"; `(2.8, None)` → "2,8 cm ± —"; `(2.8, 0.4)` → "2,8 cm ± 0,4 cm". |
| `_draw_legenda_niveis` — novo | Smoke test: chama com uma imagem preta, verifica que retorna sem erro e que a imagem foi modificada (algum pixel != 0). Sem validar pixels específicos. |
| `print_report` | Ajusta assinatura pra incluir `margem_cm`. Se houver assertion sobre saída, atualiza pra esperar a linha nova. |
| `save_debug` | Ajusta assinatura pra incluir `margem_cm`. Testes existentes que verificam só criação do arquivo continuam OK. |
| Resto (`classify_cm`, `classify_frame_cm`, `apply_mask`, `capture_frames`, `preview_camera`, etc.) | Inalterados. |

Meta: manter todos os testes passando após o refactor.

## Fora de escopo

- Aviso de fronteira quando a margem cruza limite de faixa (usuário rejeitou explicitamente).
- Erro de resolução de pixel (`1 / px_por_cm`) incorporado à margem — usuário escolheu só dispersão entre colunas.
- Recalibração das cores de categoria em outros lugares do preview (as linhas verticais amarelas de guia, a linha branca do chão, etc. seguem inalteradas).
- Toggle pra ligar/desligar a legenda ou a margem.

## Critérios de sucesso

1. `pytest tests/ -v` passa (com os testes novos e assinaturas atualizadas).
2. `python medir_grama.py` mostra no preview a legenda multicolorida com os 4 níveis + faixas em cm.
3. Console imprime `Altura mediana:     X,X cm ± Y,Y cm` (ou `± —` se 1 coluna).
4. `debug/ultima_medicao.png` mostra bolinhas/labels das colunas coloridas por categoria de cada coluna, e o título grande no topo inclui a margem.
