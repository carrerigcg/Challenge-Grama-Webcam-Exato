# Medição de altura de grama via webcam — design

**Data:** 2026-08-11
**Tipo:** Protótipo one-shot
**Stack:** Python 3.11.9 + OpenCV 5.0.0 + NumPy 2.3.3

## Resumo executivo

Script Python de execução única (`python medir_grama.py`) que aponta a webcam pra um trecho de grama, captura, processa via máscara HSV e reporta a altura classificada em três categorias (BAIXA, MÉDIA, ALTA), acompanhada do valor cru em pixels e uma imagem anotada de debug.

Sem loop contínuo, sem persistência em disco além do PNG de debug, sem banco de dados. Persistência estruturada e monitoramento contínuo ficam pra iterações futuras.

## Objetivo e escopo

**Alvo do protótipo:** protótipo demonstrável rapidamente que valida a viabilidade da abordagem (webcam + segmentação HSV + medição em colunas) num cenário outdoor real.

**Dentro do escopo:**
- Captura ao vivo da webcam padrão do sistema
- Segmentação de verde via HSV
- Medição em 3 colunas verticais fixas
- Classificação categórica com thresholds configuráveis no topo do arquivo
- Saída em terminal + PNG anotado

**Fora do escopo (v1):**
- Loop contínuo / monitoramento ao longo do tempo
- Persistência em CSV / banco de dados
- Conversão pixels → cm (calibração)
- Detecção automática de baseline (chão)
- Interface gráfica além do PNG de debug
- Detecção adaptativa de HSV a variações de iluminação

## Setup físico (requisito de uso, não código)

- **Cenário:** outdoor, apontada pra um trecho de grama real
- **Distância câmera → grama:** 30-50 cm (não 20 — foco e FOV limitantes)
- **Altura da lente:** ~15 cm acima do chão
- **Inclinação:** 0° (nivelada, horizontal, apontada de frente pra grama)
- **Fundo:** se possível, algo contrastante atrás da grama (céu, parede clara, papelão) — facilita a segmentação HSV
- **Posicionamento repetível:** um marcador no chão pra reposicionar a câmera na mesma posição entre execuções
- **Assunção da baseline:** a borda inferior do frame é o "chão". O usuário posiciona a câmera de modo que a linha do chão fique bem no fundo do frame — a altura da grama é medida a partir daí

## Arquitetura

Um único arquivo `medir_grama.py` com funções nomeadas e responsabilidade única cada. Sem estado global; constantes de configuração no topo. Cada função recebe/devolve tipos bem definidos, o que permite implementação e teste independentes (adequado a subagent-driven-development).

### Constantes de configuração

```python
CAMERA_INDEX = 0
CAMERA_BACKEND = cv2.CAP_MSMF          # confirmado como funcional no teste do ambiente
FRAME_COUNT = 5                        # frames pra estabilizar contra tremida/vento
HSV_LOWER = (35, 40, 40)               # verde inferior (H, S, V)
HSV_UPPER = (85, 255, 255)             # verde superior
SAMPLE_COLS = (0.25, 0.50, 0.75)       # posições das 3 colunas (fração da largura)
THRESHOLDS_PX = (40, 90)               # (baixa < X ≤ média < Y ≤ alta)
DEBUG_PATH = "debug/ultima_medicao.png"
COUNTDOWN_SECONDS = 3
```

### Assinaturas de função

| Função | Assinatura | Propósito |
|---|---|---|
| `countdown` | `(seconds: int) -> None` | Imprime "3... 2... 1... snap!" no terminal com `sleep` entre linhas |
| `capture_frames` | `(n: int, camera_index: int, backend: int) -> list[np.ndarray]` | Abre webcam, capta n frames BGR (480,640,3) uint8, fecha |
| `apply_mask` | `(frame_bgr: np.ndarray) -> np.ndarray` | BGR→HSV, `cv2.inRange` com HSV_LOWER/UPPER, morfologia leve (open + close 3×3). Retorna máscara (480,640) uint8 (0 ou 255) |
| `median_stack` | `(masks: list[np.ndarray]) -> np.ndarray` | Mediana pixel-a-pixel: `np.median(np.stack(masks), axis=0).astype(np.uint8)`. Retorna 1 máscara "consenso" |
| `measure_heights` | `(mask: np.ndarray, col_fractions: tuple[float, ...]) -> list[int]` | Pra cada coluna (x = int(largura × frac)): encontra o menor y com mask[y,x]==255. Altura = altura_frame − y_topo. Sem verde → 0 |
| `classify` | `(altura_px: int, thresholds: tuple[int, int]) -> str` | thresholds=(t1,t2). altura<t1 → "BAIXA"; t1≤altura<t2 → "MÉDIA"; altura≥t2 → "ALTA" |
| `print_report` | `(heights: list[int], mediana: int, categoria: str) -> None` | Formatação de saída em stdout |
| `save_debug` | `(frame_bgr, mask, heights, col_fractions, categoria, path) -> None` | Anota o frame com as 3 linhas (vermelho tracejado), o valor de px acima de cada uma, e a categoria no topo. `cv2.imwrite` |
| `main` | `() -> int` | Orquestra o pipeline; retorna 0 sucesso, 1 erro |

### Pipeline (o que `main` faz)

1. `countdown(COUNTDOWN_SECONDS)`
2. `frames = capture_frames(FRAME_COUNT, CAMERA_INDEX, CAMERA_BACKEND)`
3. `masks = [apply_mask(f) for f in frames]`
4. `mask = median_stack(masks)`
5. `heights = measure_heights(mask, SAMPLE_COLS)`
6. `altura_px = int(np.median(heights))`
7. `categoria = classify(altura_px, THRESHOLDS_PX)`
8. `print_report(heights, altura_px, categoria)`
9. `save_debug(frames[-1], mask, heights, SAMPLE_COLS, categoria, DEBUG_PATH)`

### Estrutura de dados (o que flui entre funções)

| Nome | Tipo | Shape | Vem de | Vai pra |
|---|---|---|---|---|
| `frames` | `list[ndarray]` | 5× (480, 640, 3) uint8 BGR | `capture_frames` | `apply_mask` |
| `masks` | `list[ndarray]` | 5× (480, 640) uint8 | `apply_mask` | `median_stack` |
| `mask` | `ndarray` | (480, 640) uint8 | `median_stack` | `measure_heights` |
| `heights` | `list[int]` | 3 elementos | `measure_heights` | `np.median` + `save_debug` |
| `altura_px` | `int` | escalar | `np.median(heights)` | `classify` |
| `categoria` | `str` | "BAIXA" \| "MÉDIA" \| "ALTA" | `classify` | `print_report` + `save_debug` |

## Comportamento observável

**Invocação:**
```
python medir_grama.py
```

**Saída em terminal (sucesso):**
```
3... 2... 1... snap!
Alturas: [82, 76, 88] px
Mediana:  82 px → MÉDIA
✓ debug/ultima_medicao.png salvo
```

**Arquivo gerado:** `debug/ultima_medicao.png` — último frame capturado com sobreposições:
- 3 linhas verticais vermelhas tracejadas nas posições das colunas de amostragem
- Valor de altura em px anotado acima de cada linha
- Categoria (BAIXA/MÉDIA/ALTA) em texto grande no topo

**Códigos de saída:**
- `0` — sucesso (mesmo com aviso de "sem grama detectada")
- `1` — falha de setup (webcam inacessível ou 0 frames capturáveis)
- `130` — interrompido pelo usuário via Ctrl+C (padrão Unix pra SIGINT)

## Tratamento de erros

Filosofia: **falhar rápido em erros de setup, degradar com aviso em erros de dados**.

| Cenário | Onde detecta | Comportamento | Exit |
|---|---|---|---|
| Webcam não abre no index/backend configurado | `capture_frames` | Erro claro em stderr, sai | 1 |
| Frames vindo vazios/nulos | `capture_frames` | Tenta 3× por frame; se todas falharem, erro claro, sai | 1 |
| Menos frames que o pedido (mas ≥ 1) | `capture_frames` | Aviso `"AVISO: capturou N/5 frames"`, segue | 0 |
| 0 frames capturados | `capture_frames` | Erro, sai | 1 |
| Sem pixels verdes numa coluna | `measure_heights` | Altura dessa coluna = 0 | — |
| Todas as 3 colunas com 0 verdes | `main` | Aviso `"AVISO: nenhuma grama detectada"`, reporta BAIXA | 0 |
| Pasta `debug/` não existe | `save_debug` | Cria com `os.makedirs(exist_ok=True)` | — |
| Falha ao salvar PNG | `save_debug` | Aviso, **não falha o script** | 0 |
| Ctrl+C durante execução | `main` | Captura `KeyboardInterrupt`, print `"Cancelado."`, sai | 130 |

**Deliberadamente NÃO tratado (YAGNI):**
- Retry com backends alternativos (DSHOW/MSMF/ANY) — se MSMF falhar, o usuário edita a constante
- Detecção automática de resolução — usa o default da webcam (640×480)
- Logging estruturado (só `print` pra stdout/stderr)
- Validação de tipos das constantes (Python já quebra com mensagem clara)

## Testes

**Framework:** `pytest`. Único arquivo: `tests/test_medir_grama.py`.

**Cobertura mínima** — funções puras, sem webcam nem disco:

| Função | Testes |
|---|---|
| `apply_mask` | Pixel verde puro (H=60,S=200,V=200) vira 255; pixel preto vira 0 |
| `median_stack` | 5 máscaras idênticas retornam a mesma; mix 3 zeros + 2 uns retorna zeros (mediana) |
| `measure_heights` | Máscara sintética com alturas conhecidas nas 3 colunas → retorna as alturas certas; máscara toda zerada → `[0, 0, 0]` |
| `classify` | Fronteiras: 39→BAIXA, 40→MÉDIA, 89→MÉDIA, 90→ALTA; extremos 0→BAIXA, 10000→ALTA |

**Fora dos testes automatizados:**
- `capture_frames` — depende de hardware
- `save_debug` — depende de FS (validar visualmente é mais valioso)
- `countdown`, `print_report` — trivial demais, saída visual

**Smoke test manual:** rodar `python medir_grama.py` apontado pra qualquer coisa verde e verificar que sai um número e o PNG é gerado.

**Execução:** `python -m pip install pytest && pytest tests/ -v` (segundos, sem hardware).

## Estrutura de arquivos

```
challenge-grama-webcam/
├── medir_grama.py                       # script principal (~150 linhas)
├── tests/
│   └── test_medir_grama.py              # testes das funções puras (~50 linhas)
├── debug/                               # criado em runtime pelo save_debug
│   └── ultima_medicao.png               # sobrescrito a cada execução
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-08-11-medicao-grama-webcam-design.md   # este arquivo
├── .superpowers/                        # do visual companion (adicionar a .gitignore)
└── .claude/
    └── settings.local.json              # já existe
```

## Dependências

- `opencv-python==5.0.0` — já instalado no ambiente
- `numpy==2.3.3` — já instalado no ambiente
- `pytest` — instalar quando for rodar os testes

Sem `requirements.txt` ou `pyproject.toml` na v1. Se o projeto amadurecer, formaliza.

## Adequação a subagent-driven-development

Cada função é uma unidade de trabalho independente:

- Contratos de entrada/saída explícitos (tipos e shapes documentados acima)
- Sem estado compartilhado — nenhuma função depende de outra ter rodado antes
- Testes isolados (input sintético, sem hardware) permitem verificação local
- Uma vez implementada e testada, uma função não precisa ser reaberta pra outras evoluírem

Sugestão de decomposição de tarefas pra subagents (na v1 do plano):

1. Esqueleto do arquivo + constantes + `main` como stub
2. `apply_mask` + teste
3. `median_stack` + teste
4. `measure_heights` + teste
5. `classify` + teste
6. `capture_frames` (com smoke test manual)
7. `save_debug` (com validação visual manual)
8. `countdown` + `print_report`
9. `main` — juntar as peças + smoke test end-to-end

## Riscos conhecidos e mitigações

| Risco | Impacto | Mitigação na v1 |
|---|---|---|
| Iluminação outdoor variando bagunça HSV | Alto | Fundo contrastante; se persistir, ajustar constantes HSV_LOWER/UPPER no código |
| Vento faz folhas balançarem entre frames | Médio | 5 frames com mediana pixel-a-pixel (`median_stack`) |
| Baseline "borda inferior = chão" é frágil se câmera se mexer | Médio | Marcador físico no chão pra reposicionamento repetível |
| Foco da webcam ruim a curta distância | Baixo | Distância recomendada 30-50 cm, não 20 |
| Thresholds das categorias não representam a realidade | Baixo | Constantes no topo do arquivo, ajuste em 1 linha após primeiro teste real |

## Próximos passos (fora desta v1)

- Múltiplas medições ao longo do tempo (loop + CSV)
- Calibração pixels → cm com objeto de referência no frame
- Banco de dados pra histórico
- Detecção automática de baseline por contraste terra/verde
- Threshold HSV adaptativo a variações de luz
