# Medição de grama por níveis (linhas horizontais de referência)

**Data:** 2026-08-12
**Escopo:** substituir a classificação atual baseada em `THRESHOLDS_PX` (altura do topo do verde em pixels, comparada a 2 limiares fixos) por uma classificação baseada em **3 linhas horizontais de referência** desenhadas no frame.

## Motivação

O usuário quer categorizar a grama em níveis (BAIXA / MÉDIA / ALTA) por posição vertical no frame, não por altura calculada em px. As linhas horizontais funcionam como "réguas visuais": a categoria é a faixa em que o topo do verde cai. Isso é mais intuitivo de calibrar (ajustar as % das linhas até ficarem visualmente onde você quer) e mais robusto a variações de distância câmera–grama do que thresholds em px absolutos.

## Conceito

Três linhas horizontais fixas no frame, ordenadas de **baixo pra cima** (o eixo Y de OpenCV cresce pra baixo, então "mais em baixo" na imagem = valor de Y maior):

| Índice | Papel | Fração default | Y em frame 480px |
|--------|-------|----------------|------------------|
| Linha 0 | Chão de referência (só visual) | 0.90 | 432 |
| Linha 1 | Separador BAIXA / MÉDIA | 0.60 | 288 |
| Linha 2 | Separador MÉDIA / ALTA | 0.35 | 168 |

Categorização por coluna:

| `y_topo` da coluna | Nível | Nome |
|--------------------|-------|------|
| coluna sem verde | 0 | AUSENTE |
| `y_topo > y(Linha 1)` (abaixo do sep 1) | 1 | BAIXA |
| `y(Linha 2) < y_topo <= y(Linha 1)` | 2 | MÉDIA |
| `y_topo <= y(Linha 2)` | 3 | ALTA |

Categoria final do frame = **mediana** dos níveis das 3 colunas amostradas (`SAMPLE_COLS = (0.25, 0.50, 0.75)`).

A Linha 0 (chão) **não** entra na classificação — é só uma referência visual desenhada no preview e no PNG debug pra o usuário ver onde considera o "zero".

## Constantes

Substituição no topo de `medir_grama.py`:

```python
# REMOVER
THRESHOLDS_PX = (40, 90)

# ADICIONAR (baixo → cima: chão de referência, sep BAIXA/MÉDIA, sep MÉDIA/ALTA)
LINE_FRACTIONS = (0.90, 0.60, 0.35)
LEVEL_NAMES = ("AUSENTE", "BAIXA", "MÉDIA", "ALTA")
```

`SAMPLE_COLS`, `HSV_LOWER/UPPER`, `FRAME_COUNT`, `CAMERA_*`, `DEBUG_PATH`, `COUNTDOWN_SECONDS` ficam inalterados.

## Mudanças em `medir_grama.py`

| Função | Ação |
|--------|------|
| `measure_heights()` | Renomeia pra `measure_top_y()`. Retorna `list[int | None]` com `y_topo` de cada coluna (None se sem verde). |
| `classify()` | **Remove.** Substituída por `classify_column()` + `classify_frame()`. |
| `classify_column(y_topo, altura_frame, line_fractions) -> int` | Nova. Retorna 0/1/2/3 aplicando a tabela acima. `y_topo` pode ser `None` → retorna 0. |
| `classify_frame(top_ys, altura_frame, line_fractions) -> tuple[int, str]` | Nova. Chama `classify_column` por coluna, tira mediana, retorna `(nivel, LEVEL_NAMES[nivel])`. |
| `print_report(top_ys, niveis_por_coluna, categoria)` | Assinatura muda. Imprime `top_ys` e níveis intermediários (útil pra debug). |
| `save_debug()` | Aceita `line_fractions` e `nivel_final: int`. Desenha 3 linhas horizontais (cores discretas), **destaca a linha do separador correspondente ao nível final em verde grosso**, remove as 3 verticais tracejadas vermelhas. Categoria em texto grande no topo central continua. |
| `preview_camera()` | Ganha parâmetro `line_fractions`. Desenha as 3 horizontais (chão branco tracejado, sep 1 amarelo, sep 2 laranja) com labels na lateral esquerda, além das 3 verticais amarelas já existentes. |
| `main()` | Fluxo novo (ver seção abaixo). |
| `apply_mask`, `median_stack`, `capture_frames`, `countdown` | Inalterados. |

## Fluxo `main()`

```
preview_camera(CAMERA_INDEX, CAMERA_BACKEND, SAMPLE_COLS, LINE_FRACTIONS)
  └─ ESC → return 130 ("Cancelado")
countdown(COUNTDOWN_SECONDS)
frames = capture_frames(FRAME_COUNT, ...)     # RuntimeError → return 1
masks  = [apply_mask(f) for f in frames]
mask   = median_stack(masks)
top_ys = measure_top_y(mask, SAMPLE_COLS)     # list[int | None]
niveis = [classify_column(y, mask.shape[0], LINE_FRACTIONS) for y in top_ys]
nivel_final, categoria = classify_frame(top_ys, mask.shape[0], LINE_FRACTIONS)
print_report(top_ys, niveis, categoria)
if nivel_final == 0:
    print("AVISO: sem verde detectado", file=sys.stderr)
save_debug(frames[-1], mask, top_ys, SAMPLE_COLS, LINE_FRACTIONS, nivel_final, categoria, DEBUG_PATH)
print(f"OK: {DEBUG_PATH} salvo")
return 0
```

**Exit codes preservados:** `0` sucesso, `1` erro de webcam / runtime, `130` cancelado (KeyboardInterrupt ou ESC no preview).

## Visualização

### Preview ao vivo (info máxima pra mirar)
- 3 linhas verticais amarelas (colunas de amostragem) — mantém.
- 3 linhas horizontais:
  - Chão (Linha 0): branco tracejado
  - Sep BAIXA/MÉDIA (Linha 1): amarelo sólido
  - Sep MÉDIA/ALTA (Linha 2): laranja sólido
- Labels na lateral esquerda: `chão`, `→ MÉDIA`, `→ ALTA`.
- Rodapé: `SPACE=capturar  ESC=cancelar` (mantém).

### PNG debug (`debug/ultima_medicao.png`, limpo)
- Overlay leve da máscara verde sobre o frame (mantém).
- 3 linhas horizontais em cores discretas.
- **Maior linha atingida** pela grama destacada em **verde grosso** (feedback claro do resultado):
  - AUSENTE → nenhuma linha destacada
  - BAIXA → nenhuma linha destacada (grama não atingiu nem o sep 1)
  - MÉDIA → destaca sep 1 (última linha ultrapassada)
  - ALTA → destaca sep 2
- Categoria em texto grande no topo central (mantém).
- Remove as 3 verticais tracejadas vermelhas (poluição sem valor com o novo esquema).

## Testes (`tests/test_medir_grama.py`)

| Bloco | Ação |
|-------|------|
| Testes de `classify()` (px thresholds) | **Remove todos.** |
| `classify_column()` — novos | Mínimo 6 casos: `y_topo=None` → 0; `y_topo > sep1` → 1 (BAIXA); `y_topo == sep1` → borda (verificar comportamento explícito: `<=` → nível superior); `sep2 < y_topo < sep1` → 2 (MÉDIA); `y_topo == sep2` → borda; `y_topo < sep2` → 3 (ALTA). |
| `classify_frame()` — novos | Mediana de níveis: (1,1,2) → 1; (1,2,3) → 2; (0,0,1) → 0; (3,3,3) → 3. Sanity: `LEVEL_NAMES[nivel]` bate. |
| Testes de `measure_heights` | Renomeia pra `measure_top_y`. Ajusta pra esperar `y_topo` (int ou None), não altura em px. |
| Testes de `save_debug` | Ajusta assinatura (aceita `nivel_final`, `line_fractions`). Continua verificando só que o arquivo é criado, sem validar pixels. |
| Testes de `apply_mask`, `median_stack`, `capture_frames`, `countdown`, `preview_camera` | Inalterados. |

Meta: manter ~30+ testes passando após refactor.

## Contrato de bordas (importante pra os testes)

- `classify_column` usa `y_topo <= y_linha` como "atingiu a linha". Ou seja, uma coluna com `y_topo == y(Linha 1)` classifica como MÉDIA (não BAIXA). Documentar isso via teste explícito.
- `y_topo` é o índice Y do **primeiro pixel verde de cima pra baixo** na coluna (menor Y = mais alto na imagem).

## Fora de escopo

- Calibração interativa das linhas via teclado/mouse no preview (poderia vir depois; hoje: reeditar `LINE_FRACTIONS` no script).
- Persistência de medidas em banco/CSV (já fora de escopo desde a v1).
- Loop contínuo (o script continua one-shot).
- Detecção automática de chão / horizonte (Linha 0 é fixa manual).

## Critérios de sucesso

1. `pytest tests/ -v` passa com 30+ testes verdes após o refactor.
2. `python medir_grama.py` mirando em uma superfície verde diferente-altura produz categoria coerente (BAIXA / MÉDIA / ALTA) que corresponde à posição visual do topo do verde em relação às linhas do preview.
3. PNG `debug/ultima_medicao.png` mostra as 3 linhas horizontais, a linha atingida destacada, e a categoria em texto.
4. `THRESHOLDS_PX` não aparece em lugar nenhum do código nem dos testes após o refactor.
