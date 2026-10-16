# Jogo da feira de ciências — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um jogo web no formato Kahoot para a feira de ciências: até cinco visitantes chutam pelo celular quanto mede a grama, o apresentador manda medir pela webcam real e o valor sobe numa animação com pódio.

**Architecture:** Serviço FastAPI hospedado na Render guarda a sala em memória e fala com os clientes por WebSocket. A webcam fica no notebook da feira, onde roda `jogo/ponte.py`, que abre um WebSocket **de saída** para o serviço e espera a ordem de medir — isso dispensa IP público e dispensa que os celulares estejam na mesma rede. A máquina de estado da sala (`jogo/sala.py`) é função pura sobre um dataclass, sem I/O, então a suíte roda inteira sem webcam e sem navegador.

**Tech Stack:** Python 3.11, FastAPI, WebSockets nativos do Starlette, `qrcode` para o QR em SVG, pytest. Frontend em HTML/CSS/JS puro servido pelo próprio FastAPI — sem build step, sem npm, sem CDN.

**Spec:** `docs/superpowers/specs/2026-10-16-jogo-da-feira-design.md`

**Prazo:** 24/10/2026.

---

## Contexto para quem nunca viu este repositório

- `medir_grama.py` — pipeline de visão que roda nas estações. Funções puras e importáveis: `load_calibration`, `capture_frames`, `apply_mask`, `median_stack`, `measure_top_y`, `y_para_altura_cm`, `classify_frame_cm`, `margem_erro_cm`, `save_debug`. **Este plano não altera uma linha dele** — só importa.
- `camera.py` — detecta backend/índice do OpenCV por plataforma. Importado por `medir_grama.py` no topo do módulo, então **importar `medir_grama` exige `cv2` instalado**.
- `api/` — API de produção, deployada na Render a cada `push origin main`. **Este plano não altera nada aqui.**
- `calibration.json` — gerado por `calibrar.py`, específico de cada câmera e posição.
- `tests/conftest.py` — fixtures da API, todas dependentes de Postgres. **Os testes deste plano não usam nenhuma delas**: o jogo não tem banco.

Rodar a suíte: `python -m pytest -v`

## Decisões de implementação que o spec não fecha

Três coisas que o spec deixa em aberto e que este plano resolve. Estão aqui para você não ter que decidir no meio de uma task:

**Um payload só, igual para todos.** O servidor transmite o mesmo JSON para o palco e para todos os celulares. Nenhum cliente recebe uma versão especial. Em `AGUARDANDO`, cada jogador vai no payload apenas como `{"id", "nome", "chutou": true}` — **nunca o valor do chute**, que é o que impede o último a chutar de copiar olhando a tela grande. Os valores só aparecem no `ranking`, em `RESULTADO`, quando já não há o que copiar. O cartão pessoal do celular é montado procurando o próprio `id` dentro do `ranking`.

**A transição `REVELANDO → RESULTADO` é cronometrada pelo servidor**, não disparada pelo cliente. Se o palco mandasse "a animação acabou", um palco fechado ou travado deixaria todos os celulares presos em `REVELANDO` para sempre. O servidor espera `DURACAO_REVELACAO_S` e transmite o estado novo para todo mundo junto.

**Os tokens são lidos a cada requisição, não no import do módulo.** `api/main.py` lê no topo do módulo, mas lá isso nunca precisou ser testado. Aqui os testes precisam exercitar token certo, errado e ausente, e recarregar o módulo a cada caso seria frágil. Ler dentro da função deixa `monkeypatch.setenv` funcionar direto.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `jogo/__init__.py` | pacote, vazio |
| `jogo/sala.py` | máquina de estado: entrar, chutar, medir, ranquear, travar, resetar. **Zero I/O** — não importa FastAPI, WebSocket, OpenCV nem `requests` |
| `jogo/medicao.py` | a costura da medição: registra a ponte, manda a ordem, espera a resposta com timeout. Falsificável nos testes |
| `jogo/envio.py` | POST da medição para a API de produção, em background, com `regiao="Feira de Ciências"` |
| `jogo/main.py` | app FastAPI: rotas, três tipos de WebSocket, tokens, `/qr.svg`, broadcast. Cola, sem regra de negócio |
| `jogo/ponte.py` | roda no notebook da feira: conecta para fora, mede com a webcam, devolve, reconecta, keep-alive |
| `jogo/templates/palco.html` | tela do apresentador |
| `jogo/templates/controle.html` | tela do celular |
| `jogo/static/comum.css` | paleta e tipografia compartilhadas |
| `jogo/static/palco.css`, `palco.js` | layout e animações do palco |
| `jogo/static/controle.css`, `controle.js` | layout e comportamento do celular |
| `requirements-jogo.txt` | serviço hospedado: `fastapi`, `uvicorn`, `qrcode`, `requests`, `python-dotenv` |
| `requirements-ponte.txt` | notebook: `websockets` + `-r requirements-station.txt` |
| `tests/test_jogo_sala.py` | máquina de estado |
| `tests/test_jogo_medicao.py` | a costura da medição |
| `tests/test_jogo_envio.py` | envio para a API de produção |
| `tests/test_jogo_api.py` | rotas, WebSockets, tokens, fluxo fim-a-fim com ponte falsa |
| `tests/test_jogo_ponte.py` | ponte: ordem das chamadas do pipeline, boot sem calibração, reconexão |

`jogo/envio.py` não estava na lista do spec — ele previa o envio dentro de `main.py`. Separei porque `main.py` já carrega rotas, três WebSockets e broadcast, e o envio tem a única regra de negócio que sobraria lá dentro.

---

## Task 1: Pacote e entrada de jogadores

**Files:**
- Create: `jogo/__init__.py`
- Create: `jogo/sala.py`
- Test: `tests/test_jogo_sala.py`

- [ ] **Step 1: Criar o pacote vazio**

```bash
mkdir jogo
python -c "open('jogo/__init__.py','w').close()"
```

- [ ] **Step 2: Escrever os testes que falham**

Crie `tests/test_jogo_sala.py`:

```python
"""Máquina de estado da sala do jogo da feira.

Sem fixtures de banco de propósito: o jogo não tem persistência. A sala é um
dataclass em memória e estes testes são aritmética de estado, não integração.
"""
import ast
from pathlib import Path

import pytest

from jogo.sala import MAX_JOGADORES, MAX_NOME, ErroDeJogo, Estado, Sala


def test_sala_nasce_aguardando_e_aberta():
    sala = Sala()
    assert sala.estado is Estado.AGUARDANDO
    assert sala.aberta is True
    assert sala.jogadores == []


def test_entrar_devolve_jogador_com_id_e_nome():
    sala = Sala()
    jogador = sala.entrar("Ana")
    assert jogador.nome == "Ana"
    assert jogador.id
    assert jogador.chute_cm is None
    assert sala.jogadores == [jogador]


def test_entrar_gera_ids_diferentes():
    sala = Sala()
    a = sala.entrar("Ana")
    b = sala.entrar("Bruno")
    assert a.id != b.id


def test_entrar_recusa_nome_vazio_ou_em_branco():
    sala = Sala()
    for nome in ("", "   ", "\t"):
        with pytest.raises(ErroDeJogo, match="Digite"):
            sala.entrar(nome)


def test_entrar_corta_espacos_em_volta_do_nome():
    sala = Sala()
    assert sala.entrar("  Ana  ").nome == "Ana"


def test_entrar_recusa_nome_repetido_ignorando_caixa():
    sala = Sala()
    sala.entrar("Ana")
    # Asserts distintos de propósito: as duas mensagens contêm "nome", então um
    # match="nome" nos dois não detectaria erro trocado entre os casos.
    with pytest.raises(ErroDeJogo, match="já está em uso"):
        sala.entrar("ana")


def test_entrar_recusa_o_sexto_jogador():
    sala = Sala()
    for i in range(MAX_JOGADORES):
        sala.entrar(f"Jogador {i}")
    with pytest.raises(ErroDeJogo, match="cheia"):
        sala.entrar("Sexto")


def test_entrar_recusa_quando_a_sala_esta_travada():
    sala = Sala()
    sala.definir_trava(True)
    with pytest.raises(ErroDeJogo, match="travada"):
        sala.entrar("Ana")


def test_entrar_recusa_fora_de_aguardando():
    sala = Sala()
    sala.entrar("Ana")
    # Força o estado em vez de passar por chutar/iniciar_medicao: este teste é
    # sobre a recusa da entrada, não sobre como a sala chegou em MEDINDO. Assim
    # ele não depende de métodos que só nascem nas Tasks 2 e 3, e a branch
    # fecha verde neste commit.
    sala.estado = Estado.MEDINDO
    with pytest.raises(ErroDeJogo, match="andamento"):
        sala.entrar("Bruno")


def test_entrar_aceita_nome_no_limite():
    sala = Sala()
    nome = "A" * MAX_NOME
    assert sala.entrar(nome).nome == nome


def test_entrar_recusa_nome_longo_demais():
    sala = Sala()
    with pytest.raises(ErroDeJogo, match="muito longo"):
        sala.entrar("A" * (MAX_NOME + 1))


# O que `jogo/sala.py` pode importar. Allowlist, não blocklist: um módulo novo
# de I/O não entra sozinho na lista.
IMPORTS_PERMITIDOS = {"__future__", "math", "secrets", "dataclasses", "enum"}


def test_sala_nao_ganha_io_sem_ninguem_notar():
    """Guarda da fronteira que o spec declara: a sala não fala com o mundo.

    A suíte inteira roda sem webcam e sem rede por causa disso. Um `import
    requests` acrescentado sem pensar dissolveria a garantia em silêncio — e
    doze tasks vão passar perto deste arquivo. Docstring avisa; teste impede.
    """
    codigo = (Path(__file__).parent.parent / "jogo" / "sala.py").read_text(
        encoding="utf-8"
    )
    importados = set()
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Import):
            for apelido in no.names:
                importados.add(apelido.name.split(".")[0])
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module.split(".")[0])
    proibidos = importados - IMPORTS_PERMITIDOS
    assert not proibidos, (
        f"jogo/sala.py passou a importar {sorted(proibidos)}. A sala tem que "
        "continuar sem I/O: nada de rede, câmera ou framework web."
    )
```

Depois de escrever o guarda, **confirme que ele guarda**: acrescente
temporariamente um `import json` ao topo de `jogo/sala.py`, rode só esse teste,
veja falhar, e remova o import. Teste de guarda que não falha quando deveria é
pior que nenhum.

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_sala.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jogo.sala'`

- [ ] **Step 4: Escrever a implementação mínima**

Crie `jogo/sala.py`:

```python
"""Máquina de estado da sala do jogo da feira. Zero I/O.

Este módulo não importa FastAPI, WebSocket, OpenCV nem `requests` — e não
deve passar a importar. É o que permite testar ranking, empates e sala cheia
sem webcam, sem rede e sem navegador.

Quem chama a medição é `jogo/main.py`; a sala só recebe o resultado pronto.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum

MAX_JOGADORES = 5
CHUTE_MIN_CM = 0.0
# Teto por motivo prático: alguém digita 99999 de brincadeira e isso explode a
# escala da animação e o layout do pódio.
CHUTE_MAX_CM = 200.0
# O HTML põe maxlength=20 no campo, mas o WebSocket aceita o que mandarem e a
# URL do jogo é pública. Sem teto aqui, um nome de 10.000 caracteres destrói o
# layout do palco — o mesmo motivo que justifica CHUTE_MAX_CM.
MAX_NOME = 20


class Estado(str, Enum):
    AGUARDANDO = "AGUARDANDO"
    MEDINDO = "MEDINDO"
    REVELANDO = "REVELANDO"
    RESULTADO = "RESULTADO"


class ErroDeJogo(Exception):
    """Ação recusada. A mensagem é mostrada ao jogador, então escreva para ele."""


@dataclass
class Jogador:
    id: str
    nome: str
    chute_cm: float | None = None
    ordem_do_chute: int | None = None


@dataclass
class Sala:
    estado: Estado = Estado.AGUARDANDO
    aberta: bool = True
    jogadores: list[Jogador] = field(default_factory=list)
    # Contador interno: fora do __init__, do repr e do __eq__. `Sala(_proxima_ordem=3)`
    # não é uma construção que faça sentido para quem usa a sala.
    _proxima_ordem: int = field(default=0, init=False, repr=False, compare=False)

    # --- entrada -------------------------------------------------------------

    def entrar(self, nome: str) -> Jogador:
        if self.estado is not Estado.AGUARDANDO:
            raise ErroDeJogo("Rodada em andamento. Espere a próxima.")
        if not self.aberta:
            raise ErroDeJogo("A sala está travada. Fale com o apresentador.")
        nome_limpo = nome.strip()
        if not nome_limpo:
            raise ErroDeJogo("Digite um nome.")
        if len(nome_limpo) > MAX_NOME:
            raise ErroDeJogo(f"Nome muito longo (máximo {MAX_NOME} letras).")
        if len(self.jogadores) >= MAX_JOGADORES:
            raise ErroDeJogo("Sala cheia. Espere a próxima rodada.")
        if any(j.nome.casefold() == nome_limpo.casefold() for j in self.jogadores):
            raise ErroDeJogo("Esse nome já está em uso. Escolha outro.")
        jogador = Jogador(id=secrets.token_urlsafe(8), nome=nome_limpo)
        self.jogadores.append(jogador)
        return jogador

    def definir_trava(self, travada: bool) -> None:
        self.aberta = not travada
```

- [ ] **Step 5: Rodar os testes**

Run: `python -m pytest tests/test_jogo_sala.py -v`
Expected: **12 passed**, nenhum vermelho. São os 9 testes de entrada, os 2 de
tamanho de nome e o guarda de import. A branch fecha verde neste commit: teste
vermelho commitado quebra `git bisect` e faz quem rodar a suíte tropeçar.

- [ ] **Step 6: Commit**

```bash
git add jogo/__init__.py jogo/sala.py tests/test_jogo_sala.py
git commit -m "feat(jogo): sala com entrada de jogadores, limite de nome e trava"
```

---

## Task 2: Chutes

**Files:**
- Modify: `jogo/sala.py`
- Test: `tests/test_jogo_sala.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_jogo_sala.py`:

```python
def _sala_com(*nomes: str) -> tuple[Sala, list[str]]:
    """Sala em AGUARDANDO com os jogadores dados. Devolve (sala, ids)."""
    sala = Sala()
    ids = [sala.entrar(nome).id for nome in nomes]
    return sala, ids


def test_chutar_guarda_valor_e_ordem():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_bruno, 20.0)
    sala.chutar_por_id(id_ana, 10.0)
    bruno = sala.jogador(id_bruno)
    ana = sala.jogador(id_ana)
    assert bruno.chute_cm == 20.0
    assert ana.chute_cm == 10.0
    # Bruno chutou primeiro, então tem ordem menor — é o critério de desempate.
    assert bruno.ordem_do_chute < ana.ordem_do_chute


def test_chutar_aceita_editar_e_atualiza_a_ordem():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 10.0)
    sala.chutar_por_id(id_bruno, 20.0)
    sala.chutar_por_id(id_ana, 12.5)
    assert sala.jogador(id_ana).chute_cm == 12.5
    # A regra é relativa, não absoluta: comparar a ordem da Ana só com ela
    # mesma passaria com qualquer implementação em que a ordem crescesse. O que
    # importa é que o Bruno, que cravou antes, agora está na frente dela.
    assert sala.jogador(id_bruno).ordem_do_chute < sala.jogador(id_ana).ordem_do_chute


def test_chutar_aceita_os_extremos():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 0.0)
    assert sala.jogador(id_ana).chute_cm == 0.0
    sala.chutar_por_id(id_ana, 200.0)
    assert sala.jogador(id_ana).chute_cm == 200.0


def test_chutar_recusa_fora_da_faixa():
    sala, (id_ana,) = _sala_com("Ana")
    for valor in (-0.1, 200.1, 99999.0):
        with pytest.raises(ErroDeJogo, match="0 e 200"):
            sala.chutar_por_id(id_ana, valor)


@pytest.mark.parametrize("nao_numero", [float("nan"), float("inf"), float("-inf")])
def test_chutar_recusa_nao_numero(nao_numero):
    sala, (id_ana,) = _sala_com("Ana")
    # Infinito cai no `isfinite`, não na faixa: a mensagem certa é "digite um
    # número", não "entre 0 e 200".
    with pytest.raises(ErroDeJogo, match="número"):
        sala.chutar_por_id(id_ana, nao_numero)


def test_chutar_recusa_id_desconhecido():
    sala, _ = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="não está mais na sala"):
        sala.chutar_por_id("id-que-nao-existe", 10.0)


@pytest.mark.parametrize(
    "estado", [Estado.MEDINDO, Estado.REVELANDO, Estado.RESULTADO]
)
def test_chutar_recusa_fora_de_aguardando(estado):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    # Força o estado, como na Task 1: `iniciar_medicao` só nasce na Task 3, e
    # este teste é sobre a recusa do chute, não sobre a transição.
    sala.estado = estado
    # `match="já está valendo"` e não `match="andamento"`: as duas mensagens de
    # rodada em andamento contêm "andamento", então o match frouxo passaria
    # mesmo com a ramificação do `chute_cm is None` invertida. A Ana tem chute,
    # então é esta mensagem que ela tem que ouvir.
    with pytest.raises(ErroDeJogo, match="já está valendo"):
        sala.chutar_por_id(id_ana, 11.0)
    # O chute que já valia continua valendo.
    assert sala.jogador(id_ana).chute_cm == 10.0


def test_quem_nao_chutou_nao_ouve_que_tem_chute_valendo():
    sala, (id_ana,) = _sala_com("Ana")
    sala.estado = Estado.MEDINDO
    # Criança distraída que entrou e não chutou antes de o apresentador medir é
    # o caso mais provável na feira. Dizer "seu chute já está valendo" para ela
    # é prometer o que não existe.
    with pytest.raises(ErroDeJogo, match="sem chute"):
        sala.chutar_por_id(id_ana, 11.0)


@pytest.mark.parametrize("chute_ruim", [999.0, -5.0, float("nan"), float("inf")])
def test_chute_recusado_nao_apaga_o_chute_anterior(chute_ruim):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ordem_original = sala.jogador(id_ana).ordem_do_chute
    with pytest.raises(ErroDeJogo):
        sala.chutar_por_id(id_ana, chute_ruim)
    # Nada é gravado até as validações passarem. É a regressão mais provável se
    # alguém reordenar as linhas de `chutar_por_id`.
    assert sala.jogador(id_ana).chute_cm == 10.0
    assert sala.jogador(id_ana).ordem_do_chute == ordem_original


def test_quantos_chutaram():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    assert sala.quantos_chutaram() == 0
    sala.chutar_por_id(id_ana, 10.0)
    assert sala.quantos_chutaram() == 1
    sala.chutar_por_id(id_ana, 11.0)
    assert sala.quantos_chutaram() == 1
    sala.chutar_por_id(id_bruno, 12.0)
    assert sala.quantos_chutaram() == 2
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_sala.py -k chutar -v`
Expected: FAIL — `AttributeError: 'Sala' object has no attribute 'chutar_por_id'`

- [ ] **Step 3: Implementar**

Em `jogo/sala.py`, acrescente `import math` ao topo, junto de `import secrets`
— é aqui que ele passa a ser usado (`math.isfinite`), e por isso a Task 1 não o
trouxe. Depois acrescente estes métodos dentro de `Sala`, logo abaixo de
`definir_trava`:

```python
    # --- chutes --------------------------------------------------------------

    def jogador(self, id_jogador: str) -> Jogador:
        for j in self.jogadores:
            if j.id == id_jogador:
                return j
        raise ErroDeJogo("Você não está mais na sala. Entre de novo.")

    def chutar_por_id(self, id_jogador: str, valor_cm: float) -> None:
        # O jogador é buscado ANTES da checagem de estado para que a mensagem
        # possa dizer a verdade: quem entrou e não chutou antes da medição não
        # tem chute "valendo", e dizer que tem é prometer o que não existe.
        # Efeito colateral desejado: id desconhecido passa a ser reportado
        # primeiro em qualquer estado, que é a informação mais útil.
        jogador = self.jogador(id_jogador)
        if self.estado is not Estado.AGUARDANDO:
            if jogador.chute_cm is None:
                raise ErroDeJogo(
                    "Rodada em andamento. Você ficou sem chute nesta rodada."
                )
            raise ErroDeJogo("Rodada em andamento. Seu chute já está valendo.")
        if not math.isfinite(valor_cm):
            raise ErroDeJogo("Digite um número.")
        if not CHUTE_MIN_CM <= valor_cm <= CHUTE_MAX_CM:
            raise ErroDeJogo("O chute tem que estar entre 0 e 200 cm.")
        jogador.chute_cm = float(valor_cm)
        # Reatribuir a ordem na edição é proposital: quem muda de ideia depois
        # perde a vantagem do desempate sobre quem cravou antes.
        jogador.ordem_do_chute = self._proxima_ordem
        self._proxima_ordem += 1

    def quantos_chutaram(self) -> int:
        return sum(1 for j in self.jogadores if j.chute_cm is not None)
```

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_jogo_sala.py -v`
Expected: **29 passed**, nenhum vermelho.

- [ ] **Step 5: Commit**

```bash
git add jogo/sala.py tests/test_jogo_sala.py
git commit -m "feat(jogo): chutes com validacao, edicao e ordem de desempate"
```

---

## Task 3: Medição, ranking e falha

**Files:**
- Modify: `jogo/sala.py`
- Test: `tests/test_jogo_sala.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_jogo_sala.py`:

```python
def test_iniciar_medicao_exige_pelo_menos_um_chute():
    sala, _ = _sala_com("Ana")
    with pytest.raises(ErroDeJogo, match="Ninguém chutou"):
        sala.iniciar_medicao()


def test_iniciar_medicao_muda_para_medindo():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.iniciar_medicao()
    assert sala.estado is Estado.MEDINDO


def test_segundo_iniciar_medicao_e_recusado():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.iniciar_medicao()
    with pytest.raises(ErroDeJogo, match="andamento"):
        sala.iniciar_medicao()


def test_concluir_medicao_vai_para_revelando_e_guarda_o_resultado():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, altura_cm=17.5, margem_cm=0.4, categoria="ALTA",
                          imagem_b64="iVBOR")
    assert sala.estado is Estado.REVELANDO
    assert sala.altura_cm == 17.5
    assert sala.margem_cm == 0.4
    assert sala.categoria == "ALTA"
    assert sala.imagem_b64 == "iVBOR"
    assert sala.erro is None


def test_revelacao_terminou_vai_para_resultado():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    sala.revelacao_terminou(ticket)
    assert sala.estado is Estado.RESULTADO


def test_falhar_medicao_volta_para_aguardando_preservando_chutes():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 10.0)
    sala.chutar_por_id(id_bruno, 20.0)
    ticket = sala.iniciar_medicao()
    sala.falhar_medicao(ticket, "A câmera não respondeu.")
    assert sala.estado is Estado.AGUARDANDO
    assert sala.erro == "A câmera não respondeu."
    # O grupo não digita tudo de novo por causa de um cabo solto.
    assert sala.jogador(id_ana).chute_cm == 10.0
    assert sala.jogador(id_bruno).chute_cm == 20.0


def test_erro_e_limpo_na_medicao_seguinte():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()
    sala.falhar_medicao(ticket, "A câmera não respondeu.")
    sala.iniciar_medicao()
    assert sala.erro is None


def test_ranking_ordena_por_erro_absoluto():
    sala, (id_ana, id_bruno, id_caio) = _sala_com("Ana", "Bruno", "Caio")
    sala.chutar_por_id(id_ana, 16.0)    # erra 1.5
    sala.chutar_por_id(id_bruno, 25.0)  # erra 7.5
    sala.chutar_por_id(id_caio, 17.0)   # erra 0.5
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    nomes = [linha["nome"] for linha in sala.ranking()]
    assert nomes == ["Caio", "Ana", "Bruno"]
    assert sala.ranking()[0]["posicao"] == 1
    assert sala.ranking()[0]["erro_cm"] == 0.5
    assert sala.ranking()[0]["chute_cm"] == 17.0


def test_ranking_desempata_por_quem_chutou_primeiro():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_bruno, 20.0)  # erra 2.5, chutou primeiro
    sala.chutar_por_id(id_ana, 15.0)    # erra 2.5, chutou depois
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    assert [linha["nome"] for linha in sala.ranking()] == ["Bruno", "Ana"]


def test_ranking_desempata_por_ordem_quando_o_erro_arredondado_empata():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    # Medida 12,3: o erro do Bruno é 0.7000000000000011 e o da Ana é
    # 0.6999999999999993. O palco mostra "0,7 cm" nos dois. Sem arredondar
    # antes de ordenar, a Ana ganharia por uma diferença invisível, apesar de
    # o Bruno ter cravado primeiro.
    sala.chutar_por_id(id_bruno, 11.6)
    sala.chutar_por_id(id_ana, 13.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 12.3, 0.1, "ALTA", "iVBOR")
    linhas = sala.ranking()
    assert linhas[0]["erro_cm"] == linhas[1]["erro_cm"] == 0.7
    assert linhas[0]["nome"] == "Bruno"


def test_ranking_ignora_quem_nao_chutou():
    sala, (id_ana, _id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 16.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    assert [linha["nome"] for linha in sala.ranking()] == ["Ana"]


def test_ranking_com_dois_jogadores_nao_inventa_terceiro_lugar():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 16.0)
    sala.chutar_por_id(id_bruno, 19.0)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    # Grupo de dois é comum na feira e não pode parecer defeito.
    assert len(sala.ranking()) == 2


def test_ranking_vazio_antes_da_medicao():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 16.0)
    assert sala.ranking() == []


def test_ticket_velho_nao_afeta_a_medicao_nova():
    """O coração da correção: resposta atrasada não entra na rodada seguinte."""
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t1 = sala.iniciar_medicao()
    sala.falhar_medicao(t1, "A câmera não respondeu.")
    t2 = sala.iniciar_medicao()
    assert t1 != t2
    # A resposta da medição 1 chega agora, atrasada.
    assert sala.concluir_medicao(t1, 17.5, 0.4, "ALTA", "iVBOR") is False
    assert sala.estado is Estado.MEDINDO
    assert sala.altura_cm is None
    # A medição 2 conclui normalmente.
    assert sala.concluir_medicao(t2, 9.0, 0.2, "MÉDIA", None) is True
    assert sala.altura_cm == 9.0


def test_falhar_medicao_obsoleta_nao_derruba_a_medicao_nova():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t1 = sala.iniciar_medicao()
    sala.falhar_medicao(t1, "primeira falhou")
    t2 = sala.iniciar_medicao()
    # A falha atrasada da medição 1 não pode derrubar a 2 por baixo — era o
    # buraco que a guarda de estado sozinha deixava.
    assert sala.falhar_medicao(t1, "falha atrasada") is False
    assert sala.estado is Estado.MEDINDO
    assert sala.erro is None
    assert t2 == sala._medicao


def test_concluir_medicao_duas_vezes_descarta_a_segunda():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    assert sala.concluir_medicao(t, 17.5, 0.4, "ALTA", "iVBOR") is True
    assert sala.concluir_medicao(t, 99.0, 0.4, "ALTA", None) is False
    assert sala.altura_cm == 17.5


def test_revelacao_terminou_duas_vezes_descarta_a_segunda():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    sala.concluir_medicao(t, 17.5, 0.4, "ALTA", None)
    assert sala.revelacao_terminou(t) is True
    assert sala.revelacao_terminou(t) is False
    assert sala.estado is Estado.RESULTADO


@pytest.mark.parametrize("ruim", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_concluir_medicao_recusa_altura_invalida(ruim):
    """NaN e infinito quebrariam o JSON de TODOS os clientes de uma vez."""
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    with pytest.raises(ValueError):
        sala.concluir_medicao(t, ruim, 0.4, "ALTA", None)
    # Nada gravado pela metade: a validação roda antes de qualquer mutação.
    assert sala.estado is Estado.MEDINDO
    assert sala.altura_cm is None


@pytest.mark.parametrize("ruim", [float("nan"), float("inf")])
def test_concluir_medicao_recusa_margem_invalida(ruim):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    with pytest.raises(ValueError):
        sala.concluir_medicao(t, 17.5, ruim, "ALTA", None)
    assert sala.estado is Estado.MEDINDO


def test_iniciar_medicao_apaga_o_resultado_da_rodada_anterior():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t1 = sala.iniciar_medicao()
    sala.concluir_medicao(t1, 17.5, 0.4, "ALTA", "iVBOR")
    # Na Task 4 isto acontece por `nova_rodada`; forçar o estado testa só a
    # limpeza, sem depender do método que ainda não existe.
    sala.estado = Estado.AGUARDANDO
    sala.iniciar_medicao()
    assert sala.altura_cm is None
    assert sala.margem_cm is None
    assert sala.categoria is None
    assert sala.imagem_b64 is None


def test_ranking_vazio_depois_de_falha_na_medicao():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    t = sala.iniciar_medicao()
    sala.falhar_medicao(t, "A câmera não respondeu.")
    assert sala.ranking() == []


def test_ranking_com_chute_exato_tem_erro_zero():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 17.5)
    t = sala.iniciar_medicao()
    sala.concluir_medicao(t, 17.5, 0.4, "ALTA", None)
    assert sala.ranking()[0]["erro_cm"] == 0.0


def test_ranking_desempata_por_ordem_reatribuida_na_edicao():
    sala, (id_ana, id_bruno) = _sala_com("Ana", "Bruno")
    sala.chutar_por_id(id_ana, 15.0)    # erra 2.5, cravou primeiro
    sala.chutar_por_id(id_bruno, 20.0)  # erra 2.5, cravou depois
    sala.chutar_por_id(id_ana, 15.0)    # reedita o MESMO número
    t = sala.iniciar_medicao()
    sala.concluir_medicao(t, 17.5, 0.4, "ALTA", None)
    # Mexer no chute custa a vantagem do desempate mesmo sem mudar o número.
    # É a interação entre a regra de edição (Task 2) e o ranking (Task 3).
    assert [linha["nome"] for linha in sala.ranking()] == ["Bruno", "Ana"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_sala.py -k "medicao or ranking or revelacao" -v`
Expected: FAIL — `AttributeError: 'Sala' object has no attribute 'iniciar_medicao'`

- [ ] **Step 3: Implementar**

Em `jogo/sala.py`, acrescente os cinco campos ao dataclass `Sala`, logo antes de
`_proxima_ordem`:

```python
    altura_cm: float | None = None
    margem_cm: float | None = None
    categoria: str | None = None
    imagem_b64: str | None = None
    erro: str | None = None
```

Acrescente também, **no nível do módulo** e logo antes da classe `Estado`:

```python
def _exigir_numero_finito(valor: float, campo: str) -> None:
    """Recusa NaN, infinito, negativo e não-número.

    Não é paranoia: o `send_json` do Starlette usa `json.dumps` com
    `allow_nan` no padrão, então NaN sai no WebSocket como o token `NaN` e
    infinito como `Infinity` — nenhum dos dois é JSON válido. O `JSON.parse`
    lança no navegador e, como o broadcast manda um payload só para todos, um
    valor assim derruba o palco e os cinco celulares ao mesmo tempo.
    Verificado em starlette 0.47.3.

    `ValueError` e não `ErroDeJogo`: isto é invariante do sistema, não recado
    para o visitante. Quem chama converte na borda.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"{campo} tem que ser número, veio {type(valor).__name__}")
    if not math.isfinite(valor):
        raise ValueError(f"{campo} tem que ser finito, veio {valor!r}")
    if valor < 0:
        raise ValueError(f"{campo} não pode ser negativo, veio {valor!r}")
```

E mais um campo ao dataclass `Sala`, antes de `_proxima_ordem`:

```python
    # Identifica a medição em curso. Serve para descartar resposta atrasada de
    # uma rodada que já acabou. A `nova_rodada` da Task 4 também o incrementa,
    # invalidando tudo que estiver em voo.
    _medicao: int = field(default=0, init=False, repr=False, compare=False)
```

E estes métodos dentro de `Sala`, abaixo de `quantos_chutaram`:

```python
    # --- medição -------------------------------------------------------------

    def iniciar_medicao(self) -> int:
        """Começa uma medição e devolve o ticket que a identifica.

        O ticket existe porque a medição roda numa task de background que leva
        segundos, e o apresentador pode resetar a sala no meio. Sem ele, a
        resposta atrasada de uma rodada que já acabou entra na sala nova — com
        jogadores novos chutando contra a altura velha, o ranking fica
        plausível e falso, que é pior que um erro visível na tela.
        """
        if self.estado is not Estado.AGUARDANDO:
            raise ErroDeJogo("Já tem uma medição em andamento.")
        if self.quantos_chutaram() == 0:
            raise ErroDeJogo("Ninguém chutou ainda.")
        self._limpar_resultado()
        self.erro = None
        self._medicao += 1
        self.estado = Estado.MEDINDO
        return self._medicao

    def concluir_medicao(
        self,
        ticket: int,
        altura_cm: float,
        margem_cm: float | None,
        categoria: str,
        imagem_b64: str | None,
    ) -> bool:
        """Guarda o resultado e vai para REVELANDO. `False` se obsoleto.

        Devolve `bool` em vez de levantar `ErroDeJogo`: quem chama é uma task
        de background, não um visitante. Exceção ali vira "Task exception was
        never retrieved" no log, sem ninguém para ler a mensagem.
        """
        if ticket != self._medicao or self.estado is not Estado.MEDINDO:
            return False
        _exigir_numero_finito(altura_cm, "altura_cm")
        if margem_cm is not None:
            _exigir_numero_finito(margem_cm, "margem_cm")
        self.altura_cm = float(altura_cm)
        self.margem_cm = margem_cm
        self.categoria = categoria
        self.imagem_b64 = imagem_b64
        self.estado = Estado.REVELANDO
        return True

    def revelacao_terminou(self, ticket: int) -> bool:
        """Fecha a revelação. `False` se obsoleto."""
        if ticket != self._medicao or self.estado is not Estado.REVELANDO:
            return False
        self.estado = Estado.RESULTADO
        return True

    def falhar_medicao(self, ticket: int, motivo: str) -> bool:
        """Volta para AGUARDANDO preservando os chutes. `False` se obsoleto.

        Preservar é regra, não detalhe: o grupo não vai digitar tudo de novo
        porque o cabo da câmera estava solto.
        """
        if ticket != self._medicao or self.estado is not Estado.MEDINDO:
            return False
        self.erro = motivo
        self.estado = Estado.AGUARDANDO
        return True

    def _limpar_resultado(self) -> None:
        """Apaga o resultado da rodada anterior.

        Sem isso, a sala carrega altura e imagem velhas para a rodada nova, e o
        payload de broadcast as manda para o palco fora de hora.
        """
        self.altura_cm = None
        self.margem_cm = None
        self.categoria = None
        self.imagem_b64 = None

    # --- ranking -------------------------------------------------------------

    def ranking(self) -> list[dict]:
        """Classificação da rodada, da menor para a maior distância da medida.

        Quem entrou e não chutou fica de fora. Empate resolve por quem mandou
        o chute primeiro (`ordem_do_chute`).

        O erro é arredondado ANTES de ordenar, e o mesmo valor arredondado vai
        para a tela. Isso não é cosmético: medida 12,3 com chutes de 13,0 e
        11,6 dá erros 0.6999999999999993 e 0.7000000000000011; o palco mostra
        "0,7 cm" nos dois, e ordenar pelo valor cru escolheria o vencedor por
        uma diferença no último bit. A plateia veria um empate e um vencedor
        decidido por motivo invisível, e o desempate por ordem de chegada nunca
        se aplicaria.

        Vazio fora de REVELANDO e RESULTADO: classificação só existe depois de
        uma medição válida, e amarrar isso ao estado é mais firme do que
        depender de `altura_cm` estar limpa.
        """
        if self.estado not in (Estado.REVELANDO, Estado.RESULTADO):
            return []
        if self.altura_cm is None:
            return []
        com_chute = [j for j in self.jogadores if j.chute_cm is not None]
        ordenados = sorted(
            com_chute,
            key=lambda j: (self._erro_arredondado(j), j.ordem_do_chute),
        )
        return [
            {
                "posicao": i + 1,
                "id": j.id,
                "nome": j.nome,
                "chute_cm": j.chute_cm,
                "erro_cm": self._erro_arredondado(j),
            }
            for i, j in enumerate(ordenados)
        ]

    def _erro_arredondado(self, jogador: Jogador) -> float:
        """Distância entre chute e medida, já arredondada. Veja `ranking`."""
        return round(abs(jogador.chute_cm - self.altura_cm), 1)
```

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_jogo_sala.py -v`
Expected: PASS em todos (**56 testes**).

- [ ] **Step 5: Commit**

```bash
git add jogo/sala.py tests/test_jogo_sala.py
git commit -m "feat(jogo): medicao com ticket, ranking por erro arredondado e falha que preserva chutes"
```

---

## Task 4: Nova rodada

**Files:**
- Modify: `jogo/sala.py`
- Test: `tests/test_jogo_sala.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_jogo_sala.py`:

```python
def test_nova_rodada_limpa_tudo_e_reabre():
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.definir_trava(True)
    ticket = sala.iniciar_medicao()
    sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", "iVBOR")
    sala.revelacao_terminou(ticket)

    sala.nova_rodada()

    assert sala.estado is Estado.AGUARDANDO
    assert sala.jogadores == []
    assert sala.altura_cm is None
    assert sala.margem_cm is None
    assert sala.categoria is None
    assert sala.imagem_b64 is None
    assert sala.erro is None
    assert sala.ranking() == []
    # Reabrir é proposital: esquecer a sala travada entre dois grupos deixa o
    # grupo seguinte sem entrar e sem saber por quê.
    assert sala.aberta is True


@pytest.mark.parametrize("estado_antes", list(Estado))
def test_nova_rodada_funciona_de_qualquer_estado(estado_antes):
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    sala.estado = estado_antes  # força o estado: é a válvula de escape do host
    sala.nova_rodada()
    assert sala.estado is Estado.AGUARDANDO


def test_nova_rodada_permite_entrar_de_novo_com_o_mesmo_nome():
    sala, _ = _sala_com("Ana")
    sala.nova_rodada()
    assert sala.entrar("Ana").nome == "Ana"


def test_nova_rodada_descarta_a_medicao_em_voo():
    """A corrida real da feira: grupo vai embora durante a medição."""
    sala, (id_ana,) = _sala_com("Ana")
    sala.chutar_por_id(id_ana, 10.0)
    ticket = sala.iniciar_medicao()

    sala.nova_rodada()
    id_bruno = sala.entrar("Bruno").id
    sala.chutar_por_id(id_bruno, 50.0)

    # A câmera responde agora, com a medida do grupo que já foi embora.
    assert sala.concluir_medicao(ticket, 17.5, 0.4, "ALTA", None) is False
    assert sala.estado is Estado.AGUARDANDO
    assert sala.altura_cm is None
    # O Bruno não pode ser coroado contra uma medida que não é dele.
    assert sala.ranking() == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_sala.py -k nova_rodada -v`
Expected: FAIL — `AttributeError: 'Sala' object has no attribute 'nova_rodada'`

- [ ] **Step 3: Implementar**

Em `jogo/sala.py`, acrescente dentro de `Sala`, abaixo de `falhar_medicao`:

```python
    def nova_rodada(self) -> None:
        """Zera a sala. Vale de qualquer estado: é a válvula de escape do host."""
        self.jogadores = []
        self._limpar_resultado()
        self.erro = None
        self._proxima_ordem = 0
        # Invalida a medição em voo. Sem isto, a resposta da câmera de uma
        # rodada que o apresentador acabou de resetar entraria na sala nova —
        # com jogadores novos chutando contra a altura velha, o ranking fica
        # plausível e falso.
        self._medicao += 1
        self.aberta = True
        self.estado = Estado.AGUARDANDO
```

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_jogo_sala.py -v`
Expected: PASS em todos (63 testes).

- [ ] **Step 5: Commit**

```bash
git add jogo/sala.py tests/test_jogo_sala.py
git commit -m "feat(jogo): nova rodada de qualquer estado, reabrindo a sala"
```

---

## Task 5: A costura da medição

**Files:**
- Create: `jogo/medicao.py`
- Modify: `requirements-dev.txt`
- Create: `pytest.ini`
- Test: `tests/test_jogo_medicao.py`

A ponte é um WebSocket que vive no servidor. Quem pede a medição manda a ordem
por ele e **espera a resposta chegar por outro caminho** — o mesmo socket, lido
por uma task separada. `Medidor` resolve isso com um `asyncio.Future`: `medir()`
cria o future e aguarda; `entregar_resultado()` o completa.

- [ ] **Step 1: Instalar o plugin de asyncio do pytest**

```bash
pip install pytest-asyncio
```

Acrescente ao fim de `requirements-dev.txt`:

```
pytest-asyncio
```

Crie `pytest.ini` na raiz:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: Escrever os testes que falham**

Crie `tests/test_jogo_medicao.py`:

```python
"""A costura entre o jogo e a ponte da câmera.

Sem webcam e sem WebSocket real: o canal da ponte é falsificado por uma classe
que só guarda o que foi enviado.
"""
import asyncio

import pytest

from jogo.medicao import ErroDeMedicao, Medidor


class CanalFalso:
    """Faz o papel do WebSocket da ponte: guarda as ordens enviadas."""

    def __init__(self):
        self.ordens = []

    async def send_json(self, dados):
        self.ordens.append(dados)


async def test_medir_sem_ponte_conectada_falha_na_hora():
    medidor = Medidor()
    assert medidor.conectado is False
    with pytest.raises(ErroDeMedicao, match="ponte"):
        await medidor.medir()


async def test_medir_manda_a_ordem_e_devolve_o_resultado():
    medidor = Medidor()
    canal = CanalFalso()
    medidor.conectar(canal)
    assert medidor.conectado is True

    async def responder():
        while not canal.ordens:  # espera a ordem sair
            await asyncio.sleep(0)
        medidor.entregar_resultado(
            {"altura_cm": 17.5, "margem_cm": 0.4, "categoria": "ALTA",
             "imagem_b64": "iVBOR"}
        )

    asyncio.create_task(responder())
    resultado = await medidor.medir()

    assert canal.ordens == [{"cmd": "medir"}]
    assert resultado["altura_cm"] == 17.5
    assert resultado["categoria"] == "ALTA"


async def test_medir_propaga_erro_reportado_pela_ponte():
    medidor = Medidor()
    canal = CanalFalso()
    medidor.conectar(canal)

    async def responder():
        while not canal.ordens:
            await asyncio.sleep(0)
        medidor.entregar_erro("A câmera não respondeu.")

    asyncio.create_task(responder())
    with pytest.raises(ErroDeMedicao, match="câmera não respondeu"):
        await medidor.medir()


async def test_medir_estoura_timeout_se_a_ponte_emudecer():
    medidor = Medidor(timeout_s=0.05)
    medidor.conectar(CanalFalso())
    with pytest.raises(ErroDeMedicao, match="demorou"):
        await medidor.medir()


async def test_desconectar_no_meio_da_medicao_falha_a_espera():
    medidor = Medidor()
    canal = CanalFalso()
    medidor.conectar(canal)

    async def derrubar():
        while not canal.ordens:
            await asyncio.sleep(0)
        medidor.desconectar(canal)

    asyncio.create_task(derrubar())
    with pytest.raises(ErroDeMedicao, match="ponte"):
        await medidor.medir()


async def test_segunda_ponte_e_recusada():
    medidor = Medidor()
    primeira = CanalFalso()
    medidor.conectar(primeira)
    with pytest.raises(ErroDeMedicao, match="outra ponte"):
        medidor.conectar(CanalFalso())
    # A primeira continua valendo: duas câmeras disputando a ordem é pior.
    assert medidor.canal is primeira


async def test_medir_recusa_medicao_concorrente():
    medidor = Medidor()
    canal = CanalFalso()
    medidor.conectar(canal)

    async def segunda_chamada():
        while not canal.ordens:  # espera a primeira ordem sair
            await asyncio.sleep(0)
        with pytest.raises(ErroDeMedicao, match="em andamento"):
            await medidor.medir()
        medidor.entregar_resultado({"altura_cm": 17.5})

    asyncio.create_task(segunda_chamada())
    resultado = await medidor.medir()
    assert resultado["altura_cm"] == 17.5
    # Uma ordem só saiu: a segunda nem chegou ao canal.
    assert canal.ordens == [{"cmd": "medir"}]


async def test_desconectar_canal_antigo_nao_derruba_o_atual():
    medidor = Medidor()
    antigo = CanalFalso()
    medidor.conectar(antigo)
    medidor.desconectar(antigo)
    novo = CanalFalso()
    medidor.conectar(novo)
    medidor.desconectar(antigo)  # chegou atrasado
    assert medidor.conectado is True
    assert medidor.canal is novo
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_medicao.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jogo.medicao'`

- [ ] **Step 4: Implementar**

Crie `jogo/medicao.py`:

```python
"""Costura entre o jogo e a ponte que opera a câmera.

A ordem de medir sai por um canal (o WebSocket da ponte) e a resposta volta
por uma task diferente, que está lendo esse mesmo socket. Por isso `medir()`
cria um `Future` e aguarda, e `entregar_resultado()` o completa.

Uma implementação só, de propósito. A costura existe para que os testes
possam falsificar a medição e rodar sem webcam — não para abrir espaço a uma
segunda fonte hipotética.
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

# 30s cobre folgado os ~3s do pipeline mais a ida e volta pela internet. Acima
# disso é ponte muda, não ponte lenta.
TIMEOUT_PADRAO_S = 30.0


class Canal(Protocol):
    """O mínimo que a ponte precisa oferecer. Um WebSocket do Starlette serve."""

    async def send_json(self, dados: Any) -> None: ...


class ErroDeMedicao(Exception):
    """Medição não aconteceu. A mensagem é mostrada no palco."""


class Medidor:
    def __init__(self, timeout_s: float = TIMEOUT_PADRAO_S):
        self.canal: Canal | None = None
        self._timeout_s = timeout_s
        self._esperando: asyncio.Future | None = None

    @property
    def conectado(self) -> bool:
        return self.canal is not None

    # --- ciclo de vida da ponte ---------------------------------------------

    def conectar(self, canal: Canal) -> None:
        if self.canal is not None:
            raise ErroDeMedicao(
                "Já existe outra ponte conectada. Feche a outra antes."
            )
        self.canal = canal

    def desconectar(self, canal: Canal) -> None:
        """Ignora canal que não é o atual: desconexão atrasada não derruba o novo."""
        if self.canal is not canal:
            return
        self.canal = None
        self._falhar_espera("A ponte da câmera caiu no meio da medição.")

    # --- medição -------------------------------------------------------------

    async def medir(self) -> dict:
        if self.canal is None:
            raise ErroDeMedicao("A ponte da câmera não está conectada.")
        if self._esperando is not None and not self._esperando.done():
            # Sem isto, a segunda chamada sobrescreve o future da primeira, que
            # fica órfã esperando até estourar o timeout de 30s. A ponte também
            # processa uma ordem por vez, então a segunda só atrapalharia.
            raise ErroDeMedicao("Já existe uma medição em andamento.")
        laco = asyncio.get_running_loop()
        self._esperando = laco.create_future()
        await self.canal.send_json({"cmd": "medir"})
        try:
            return await asyncio.wait_for(self._esperando, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            raise ErroDeMedicao("A câmera demorou demais para responder.") from None
        finally:
            self._esperando = None

    def entregar_resultado(self, resultado: dict) -> None:
        if self._esperando is not None and not self._esperando.done():
            self._esperando.set_result(resultado)

    def entregar_erro(self, motivo: str) -> None:
        self._falhar_espera(motivo)

    def _falhar_espera(self, motivo: str) -> None:
        if self._esperando is not None and not self._esperando.done():
            self._esperando.set_exception(ErroDeMedicao(motivo))
```

- [ ] **Step 5: Rodar os testes**

Run: `python -m pytest tests/test_jogo_medicao.py -v`
Expected: PASS nos 8 testes.

- [ ] **Step 6: Commit**

```bash
git add jogo/medicao.py tests/test_jogo_medicao.py requirements-dev.txt pytest.ini
git commit -m "feat(jogo): costura da medicao com timeout e ponte unica"
```

---

## Task 6: App, tokens e QR

**Files:**
- Create: `jogo/main.py`
- Create: `jogo/templates/palco.html`
- Create: `jogo/templates/controle.html`
- Create: `jogo/static/comum.css`
- Create: `requirements-jogo.txt`
- Test: `tests/test_jogo_api.py`

- [ ] **Step 1: Criar o requirements e instalar**

Crie `requirements-jogo.txt`:

```
fastapi
uvicorn[standard]
qrcode
requests
python-dotenv
```

```bash
pip install -r requirements-jogo.txt
```

- [ ] **Step 2: Escrever os testes que falham**

Crie `tests/test_jogo_api.py`:

```python
"""Rotas e WebSockets do jogo da feira.

Nenhuma fixture de `conftest.py` é usada: o jogo não tem banco. Os tokens são
injetados por `monkeypatch.setenv` e lidos a cada requisição, então não é
preciso recarregar o módulo entre casos.
"""
import pytest
from fastapi.testclient import TestClient

HOST_TOKEN = "token-de-host-de-teste"
PONTE_TOKEN = "token-de-ponte-de-teste"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("HOST_TOKEN", HOST_TOKEN)
    monkeypatch.setenv("PONTE_TOKEN", PONTE_TOKEN)
    from jogo.main import app, medidor, sala

    # Estado global do processo: zera entre testes para não vazar jogador de um
    # caso para o outro.
    sala.nova_rodada()
    medidor.canal = None
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_raiz_serve_a_tela_do_controle(client):
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_host_sem_token_responde_403(client):
    assert client.get("/host").status_code == 403


def test_host_com_token_errado_responde_403(client):
    assert client.get("/host?token=errado").status_code == 403


def test_host_com_token_certo_serve_a_tela_do_palco(client):
    resposta = client.get(f"/host?token={HOST_TOKEN}")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_host_responde_403_se_o_token_nao_esta_configurado(client, monkeypatch):
    monkeypatch.delenv("HOST_TOKEN")
    assert client.get(f"/host?token={HOST_TOKEN}").status_code == 403


def test_qr_devolve_svg(client):
    resposta = client.get("/qr.svg")
    assert resposta.status_code == 200
    assert "svg" in resposta.headers["content-type"]
    assert b"<svg" in resposta.content


def test_qr_usa_a_url_publica_configurada(client, monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://exemplo.test/")
    assert client.get("/qr.svg").status_code == 200


def test_saude_responde_sem_token(client):
    resposta = client.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jogo.main'`

- [ ] **Step 4: Criar os dois templates mínimos**

Eles ganham corpo nas Tasks 10 e 11. Aqui só precisam existir para as rotas
responderem HTML.

Crie `jogo/templates/controle.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grama Webcam</title>
</head>
<body><main id="app">carregando…</main></body>
</html>
```

Crie `jogo/templates/palco.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grama Webcam — palco</title>
</head>
<body><main id="app">carregando…</main></body>
</html>
```

- [ ] **Step 5: Criar a pasta de estáticos**

`StaticFiles` estoura no import se a pasta não existir.

```bash
mkdir jogo/static
python -c "open('jogo/static/comum.css','w').close()"
```

- [ ] **Step 6: Implementar `jogo/main.py`**

```python
"""App do jogo da feira: rotas, WebSockets e broadcast.

Cola, sem regra de negócio. A regra está em `jogo/sala.py`.

Os tokens são lidos a cada requisição, e não no import do módulo como em
`api/main.py`: aqui os testes exercitam token certo, errado e ausente, e
recarregar o módulo a cada caso seria frágil.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from jogo.medicao import Medidor
from jogo.sala import Sala

PASTA = Path(__file__).parent

app = FastAPI(title="Grama Webcam — jogo da feira", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")

# Estado do processo. Uma sala só, um medidor só: é um jogo por feira.
sala = Sala()
medidor = Medidor()


def _html(nome: str) -> HTMLResponse:
    return HTMLResponse((PASTA / "templates" / nome).read_text(encoding="utf-8"))


def _conferir_token_de_host(token: str | None) -> None:
    """403 sem token válido. Esconder o botão no CSS não é controle de acesso."""
    esperado = os.environ.get("HOST_TOKEN")
    if not esperado or token != esperado:
        raise HTTPException(status_code=403, detail="Token de host inválido.")


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def controle():
    return _html("controle.html")


@app.get("/host", response_class=HTMLResponse)
def palco(token: str | None = None):
    _conferir_token_de_host(token)
    return _html("palco.html")


@app.get("/qr.svg")
def qr(request: Request):
    """QR da URL pública do jogo, gerado no servidor.

    Em Python e não com um `qrcode.js` de CDN: script de terceiro é
    exatamente o que falha quando a rede da feira oscila.
    """
    url = os.environ.get("JOGO_URL_PUBLICA") or str(request.base_url)
    imagem = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    imagem.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")
```

- [ ] **Step 7: Rodar os testes**

Run: `python -m pytest tests/test_jogo_api.py -v`
Expected: PASS nos 8 testes.

- [ ] **Step 8: Commit**

```bash
git add jogo/main.py jogo/templates jogo/static requirements-jogo.txt tests/test_jogo_api.py
git commit -m "feat(jogo): app com token de host e QR gerado no servidor"
```

---

## Task 7: WebSocket dos jogadores e broadcast

**Files:**
- Modify: `jogo/main.py`
- Test: `tests/test_jogo_api.py`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_jogo_api.py`:

```python
def _entrar(ws, nome):
    """Entra na sala e devolve o id. Consome o `voce` e o primeiro `estado`."""
    ws.send_json({"cmd": "entrar", "nome": nome})
    boas_vindas = ws.receive_json()
    ws.receive_json()  # estado transmitido depois da entrada
    return boas_vindas["id"]


def test_jogador_entra_e_recebe_o_proprio_id(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        boas_vindas = ws.receive_json()
        assert boas_vindas["tipo"] == "voce"
        assert boas_vindas["id"]
        assert boas_vindas["nome"] == "Ana"


def test_estado_chega_depois_de_entrar(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        ws.receive_json()  # voce
        estado = ws.receive_json()
        assert estado["tipo"] == "estado"
        assert estado["estado"] == "AGUARDANDO"
        assert len(estado["jogadores"]) == 1
        assert estado["jogadores"][0]["nome"] == "Ana"
        assert estado["jogadores"][0]["chutou"] is False


def test_nome_repetido_devolve_erro_sem_derrubar_o_socket(client):
    with client.websocket_connect("/ws/jogador") as primeiro:
        _entrar(primeiro, "Ana")
        with client.websocket_connect("/ws/jogador") as segundo:
            segundo.send_json({"cmd": "entrar", "nome": "Ana"})
            resposta = segundo.receive_json()
            assert resposta["tipo"] == "erro"
            assert "nome" in resposta["mensagem"]
            # O socket continua vivo: dá pra tentar outro nome.
            segundo.send_json({"cmd": "entrar", "nome": "Bruno"})
            assert segundo.receive_json()["tipo"] == "voce"


def test_chute_nao_vaza_o_valor_no_estado(client):
    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 15.5})
        estado = ws.receive_json()
        assert estado["jogadores"][0]["chutou"] is True
        assert estado["quantos_chutaram"] == 1
        # O valor não pode estar em lugar nenhum do payload: todos olham a mesma
        # tela grande e o último a chutar copiaria.
        assert "15.5" not in str(estado)


def test_chute_fora_da_faixa_devolve_erro(client):
    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 300})
        resposta = ws.receive_json()
        assert resposta["tipo"] == "erro"
        assert "0 e 200" in resposta["mensagem"]


def test_entrada_de_um_jogador_chega_no_palco(client):
    with client.websocket_connect("/ws/palco") as palco:
        palco.receive_json()  # estado inicial
        with client.websocket_connect("/ws/jogador") as jogador:
            jogador.send_json({"cmd": "entrar", "nome": "Ana"})
            jogador.receive_json()  # voce
            estado = palco.receive_json()
            assert [j["nome"] for j in estado["jogadores"]] == ["Ana"]


def test_jogador_reconecta_na_mesma_cadeira(client):
    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 15.5})
        ws.receive_json()

    # Celular bloqueou a tela e o socket caiu.
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "voltar", "id": id_ana})
        resposta = ws.receive_json()
        assert resposta["tipo"] == "voce"
        assert resposta["id"] == id_ana
        assert resposta["nome"] == "Ana"
        estado = ws.receive_json()
        # Não virou fantasma nem cadeira nova.
        assert len(estado["jogadores"]) == 1
        assert estado["quantos_chutaram"] == 1


def test_voltar_com_id_desconhecido_devolve_erro(client):
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "voltar", "id": "nao-existe"})
        assert ws.receive_json()["tipo"] == "erro"


@pytest.mark.parametrize("nome_torto", [None, 123, ["Ana"], {"a": 1}])
def test_entrar_com_nome_de_tipo_errado_nao_derruba_o_socket(client, nome_torto):
    """A URL é pública: o payload pode vir de qualquer cliente, não só do nosso.

    O `str(... or "")` do handler transforma qualquer coisa em texto, e daí a
    sala decide. O que não pode é a conexão morrer — um socket derrubado por
    payload torto deixaria o visitante com a tela travada sem explicação.
    """
    with client.websocket_connect("/ws/jogador") as ws:
        ws.send_json({"cmd": "entrar", "nome": nome_torto})
        resposta = ws.receive_json()
        assert resposta["tipo"] in ("voce", "erro")
        # `None` cai no `or ""` e vira nome vazio, que a sala recusa.
        if nome_torto is None:
            assert resposta["tipo"] == "erro"
        # O socket continua utilizável depois da recusa.
        ws.send_json({"cmd": "entrar", "nome": "Ana"})
        assert ws.receive_json()["tipo"] in ("voce", "erro")


def test_comando_de_host_pelo_socket_de_jogador_nao_faz_nada(client):
    from jogo.main import sala as sala_do_app

    with client.websocket_connect("/ws/jogador") as ws:
        id_ana = _entrar(ws, "Ana")
        ws.send_json({"cmd": "chutar", "id": id_ana, "valor_cm": 10.0})
        ws.receive_json()
        for comando in ({"cmd": "medir"}, {"cmd": "nova_rodada"},
                        {"cmd": "travar", "travada": True}):
            ws.send_json(comando)
            assert ws.receive_json()["tipo"] == "erro"
        assert sala_do_app.estado.value == "AGUARDANDO"
        assert sala_do_app.aberta is True
        assert len(sala_do_app.jogadores) == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_api.py -k jogador -v`
Expected: FAIL — a rota `/ws/jogador` não existe, o handshake é recusado

- [ ] **Step 3: Implementar**

Nos imports no topo de `jogo/main.py`, troque a linha de `Sala` e acrescente a
de WebSocket:

```python
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from jogo.sala import ErroDeJogo, Sala
```

E acrescente ao fim do arquivo:

```python
# --- broadcast ---------------------------------------------------------------

# Todos os clientes recebem o MESMO payload. Nenhum tem versão especial: é o que
# mantém o broadcast trivial e impede vazamento acidental de chute.
_clientes: set[WebSocket] = set()


def estado_atual() -> dict:
    return {
        "tipo": "estado",
        "estado": sala.estado.value,
        "aberta": sala.aberta,
        "ponte_conectada": medidor.conectado,
        "jogadores": [
            {"id": j.id, "nome": j.nome, "chutou": j.chute_cm is not None}
            for j in sala.jogadores
        ],
        "quantos_chutaram": sala.quantos_chutaram(),
        "altura_cm": sala.altura_cm,
        "margem_cm": sala.margem_cm,
        "categoria": sala.categoria,
        "imagem_b64": sala.imagem_b64,
        "erro": sala.erro,
        "ranking": sala.ranking(),
    }


async def transmitir() -> None:
    payload = estado_atual()
    for cliente in list(_clientes):
        try:
            await cliente.send_json(payload)
        except Exception:
            # Socket morto sai daqui; o `finally` do handler também remove, e
            # descartar duas vezes de um set não custa nada.
            _clientes.discard(cliente)


# --- WebSocket dos jogadores -------------------------------------------------


@app.websocket("/ws/jogador")
async def ws_jogador(ws: WebSocket):
    await ws.accept()
    _clientes.add(ws)
    try:
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("cmd")
            try:
                if cmd == "entrar":
                    # `or ""` e não um default no get: um cliente que manda
                    # "nome": null explicitamente faria str(None) == "None" e
                    # entraria na sala com esse nome.
                    jogador = sala.entrar(str(msg.get("nome") or ""))
                    await ws.send_json(
                        {"tipo": "voce", "id": jogador.id, "nome": jogador.nome}
                    )
                elif cmd == "voltar":
                    jogador = sala.jogador(str(msg.get("id", "")))
                    await ws.send_json(
                        {"tipo": "voce", "id": jogador.id, "nome": jogador.nome}
                    )
                elif cmd == "chutar":
                    sala.chutar_por_id(
                        str(msg.get("id", "")), float(msg.get("valor_cm"))
                    )
                else:
                    # Comandos de host não existem neste socket: mandar na mão
                    # não faz nada.
                    raise ErroDeJogo("Comando desconhecido.")
            except ErroDeJogo as e:
                await ws.send_json({"tipo": "erro", "mensagem": str(e)})
                continue
            except (TypeError, ValueError):
                await ws.send_json({"tipo": "erro", "mensagem": "Digite um número."})
                continue
            await transmitir()
    except WebSocketDisconnect:
        pass
    finally:
        _clientes.discard(ws)


# --- WebSocket do palco ------------------------------------------------------


@app.websocket("/ws/palco")
async def ws_palco(ws: WebSocket):
    """Palco sem token: só observa. Os comandos vivem em `/ws/host`."""
    await ws.accept()
    _clientes.add(ws)
    await ws.send_json(estado_atual())
    try:
        while True:
            await ws.receive_json()
    except WebSocketDisconnect:
        pass
    finally:
        _clientes.discard(ws)
```

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_jogo_api.py -v`
Expected: PASS nos 17 testes.

- [ ] **Step 5: Commit**

```bash
git add jogo/main.py tests/test_jogo_api.py
git commit -m "feat(jogo): websocket de jogador e palco com broadcast de estado"
```

---

## Task 8: WebSocket da ponte e comandos de host

**Files:**
- Modify: `jogo/main.py`
- Test: `tests/test_jogo_api.py`

Esta task termina com a suíte **vermelha de propósito**: ela importa
`jogo/envio.py`, que a Task 9 cria. Está sinalizado no Step 4.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_jogo_api.py`:

```python
def _jogador_que_chutou(client, nome="Ana", valor=16.0):
    """Abre um socket de jogador, entra, chuta e devolve (socket, id).

    Devolve o socket aberto em vez de usar `with`: aninhar mais um nível de
    contexto dentro dos testes de host deixaria a leitura ilegível.
    """
    ws = client.websocket_connect("/ws/jogador").__enter__()
    ws.send_json({"cmd": "entrar", "nome": nome})
    id_jogador = ws.receive_json()["id"]
    ws.receive_json()
    ws.send_json({"cmd": "chutar", "id": id_jogador, "valor_cm": valor})
    ws.receive_json()
    return ws, id_jogador


def test_ponte_sem_token_e_recusada(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ponte") as ws:
            ws.receive_json()


def test_ponte_conectada_aparece_no_estado(client):
    with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}"):
        with client.websocket_connect("/ws/palco") as palco:
            assert palco.receive_json()["ponte_conectada"] is True


def test_segunda_ponte_e_recusada_com_mensagem(client):
    with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}"):
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as segunda:
            resposta = segunda.receive_json()
            assert resposta["tipo"] == "erro"
            assert "outra ponte" in resposta["mensagem"]


def test_host_sem_token_no_socket_e_recusado(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/host") as ws:
            ws.receive_json()


def test_medir_sem_ponte_devolve_erro_ao_host(client):
    ws_jogador, _ = _jogador_que_chutou(client)
    try:
        with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
            host.receive_json()  # estado inicial
            host.send_json({"cmd": "medir"})
            resposta = host.receive_json()
            assert resposta["tipo"] == "erro"
            assert "ponte" in resposta["mensagem"]
    finally:
        ws_jogador.close()


def test_medir_percorre_medindo_revelando_resultado(client, monkeypatch):
    monkeypatch.setenv("DURACAO_REVELACAO_S", "0.05")
    ws_jogador, _ = _jogador_que_chutou(client, "Ana", 16.0)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()  # estado inicial
                host.send_json({"cmd": "medir"})

                assert host.receive_json()["estado"] == "MEDINDO"
                assert ponte.receive_json() == {"cmd": "medir"}

                ponte.send_json({
                    "tipo": "resultado", "altura_cm": 17.5, "margem_cm": 0.4,
                    "categoria": "ALTA", "imagem_b64": "iVBOR",
                })

                revelando = host.receive_json()
                assert revelando["estado"] == "REVELANDO"
                assert revelando["altura_cm"] == 17.5

                resultado = host.receive_json()
                assert resultado["estado"] == "RESULTADO"
                assert resultado["ranking"][0]["nome"] == "Ana"
                assert resultado["ranking"][0]["erro_cm"] == 1.5
    finally:
        ws_jogador.close()


def test_erro_da_ponte_volta_para_aguardando_preservando_chutes(client):
    ws_jogador, _ = _jogador_que_chutou(client, "Ana", 16.0)
    try:
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}") as ponte:
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                host.receive_json()   # MEDINDO
                ponte.receive_json()  # a ordem
                ponte.send_json({
                    "tipo": "erro", "mensagem": "A câmera não respondeu.",
                })
                estado = host.receive_json()
                assert estado["estado"] == "AGUARDANDO"
                assert estado["erro"] == "A câmera não respondeu."
                assert estado["quantos_chutaram"] == 1
    finally:
        ws_jogador.close()


def test_medir_sem_ninguem_ter_chutado_devolve_erro(client):
    with client.websocket_connect("/ws/jogador") as jogador:
        _entrar(jogador, "Ana")
        with client.websocket_connect(f"/ws/ponte?token={PONTE_TOKEN}"):
            jogador.receive_json()  # estado com a ponte ligada
            with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
                host.receive_json()
                host.send_json({"cmd": "medir"})
                resposta = host.receive_json()
                assert resposta["tipo"] == "erro"
                assert "chutou" in resposta["mensagem"]


def test_host_trava_e_destrava_a_sala(client):
    with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
        host.receive_json()
        host.send_json({"cmd": "travar", "travada": True})
        assert host.receive_json()["aberta"] is False
        host.send_json({"cmd": "travar", "travada": False})
        assert host.receive_json()["aberta"] is True


def test_host_nova_rodada_limpa_a_sala(client):
    ws_jogador, _ = _jogador_que_chutou(client)
    try:
        with client.websocket_connect(f"/ws/host?token={HOST_TOKEN}") as host:
            host.receive_json()
            host.send_json({"cmd": "nova_rodada"})
            estado = host.receive_json()
            assert estado["jogadores"] == []
            assert estado["estado"] == "AGUARDANDO"
    finally:
        ws_jogador.close()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_api.py -k "ponte or host" -v`
Expected: FAIL — as rotas `/ws/ponte` e `/ws/host` não existem

- [ ] **Step 3: Implementar**

Acrescente aos imports no topo de `jogo/main.py` (a linha de `Medidor`
substitui a que já existia):

```python
import asyncio

from jogo.envio import enviar_em_background
from jogo.medicao import ErroDeMedicao, Medidor
```

E acrescente ao fim do arquivo:

```python
# --- revelação ---------------------------------------------------------------

# Cronometrada pelo servidor, não disparada pelo palco: um palco fechado ou
# travado deixaria todos os celulares presos em REVELANDO para sempre.
# 2,2s é a animação do contador; a sobra deixa o número parado um instante.
DURACAO_REVELACAO_S_PADRAO = 2.6


def _duracao_revelacao() -> float:
    return float(os.environ.get("DURACAO_REVELACAO_S", DURACAO_REVELACAO_S_PADRAO))


# O asyncio só guarda referência fraca para tasks soltas, e uma task coletada
# no meio da medição morre em silêncio, deixando a sala presa em MEDINDO.
_tarefas_em_voo: set[asyncio.Task] = set()


async def _medir_e_revelar(ticket: int) -> None:
    """Pede a medição, revela e fecha. Cada passo é descartável por `ticket`.

    O ticket vem do `iniciar_medicao` e identifica a rodada. Se o apresentador
    resetar a sala no meio, a sala recusa tudo que chegar com ticket velho e
    esta task some sem efeito — é o que impede a resposta de uma rodada que já
    acabou de coroar um vencedor contra uma medida que não é dele.
    """
    try:
        resultado = await medidor.medir()
        # Dentro do try de propósito: um payload sem `altura_cm` levantaria
        # KeyError aqui, e fora do try isso deixaria a sala presa em MEDINDO
        # para sempre, com só o "nova rodada" como escape.
        altura = resultado["altura_cm"]
    except ErroDeMedicao as e:
        sala.falhar_medicao(ticket, str(e))
        await transmitir()
        return
    except Exception as e:
        sala.falhar_medicao(ticket, f"Falha inesperada na medição: {e}")
        await transmitir()
        return

    try:
        aceito = sala.concluir_medicao(
            ticket,
            altura_cm=altura,
            margem_cm=resultado.get("margem_cm"),
            categoria=resultado.get("categoria", ""),
            imagem_b64=resultado.get("imagem_b64"),
        )
    except ValueError as e:
        # A sala recusa NaN, infinito e negativo: seriam serializados como
        # tokens inválidos de JSON e derrubariam todos os clientes de uma vez.
        sala.falhar_medicao(ticket, f"Medição inválida: {e}")
        await transmitir()
        return

    # A grama foi medida de verdade, então o dado vai pra API mesmo quando a
    # rodada já acabou — a API guarda leitura bruta, não resultado de jogo.
    enviar_em_background(resultado)
    if not aceito:
        return  # rodada obsoleta: sem transmitir e sem dormir a animação

    await transmitir()
    await asyncio.sleep(_duracao_revelacao())
    sala.revelacao_terminou(ticket)
    await transmitir()


# --- WebSocket do host -------------------------------------------------------


@app.websocket("/ws/host")
async def ws_host(ws: WebSocket, token: str | None = None):
    esperado = os.environ.get("HOST_TOKEN")
    if not esperado or token != esperado:
        await ws.close(code=1008)
        return
    await ws.accept()
    _clientes.add(ws)
    await ws.send_json(estado_atual())
    try:
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("cmd")
            try:
                if cmd == "medir":
                    if not medidor.conectado:
                        raise ErroDeJogo("A ponte da câmera não está conectada.")
                    ticket = sala.iniciar_medicao()
                    await transmitir()
                    # Task separada: o handler precisa voltar a ler o socket
                    # enquanto a medição corre. A referência fica no set porque
                    # o asyncio não segura task solta.
                    tarefa = asyncio.create_task(_medir_e_revelar(ticket))
                    _tarefas_em_voo.add(tarefa)
                    tarefa.add_done_callback(_tarefas_em_voo.discard)
                    continue
                if cmd == "nova_rodada":
                    sala.nova_rodada()
                elif cmd == "travar":
                    sala.definir_trava(bool(msg.get("travada")))
                else:
                    raise ErroDeJogo("Comando desconhecido.")
            except ErroDeJogo as e:
                await ws.send_json({"tipo": "erro", "mensagem": str(e)})
                continue
            await transmitir()
    except WebSocketDisconnect:
        pass
    finally:
        _clientes.discard(ws)


# --- WebSocket da ponte ------------------------------------------------------


@app.websocket("/ws/ponte")
async def ws_ponte(ws: WebSocket, token: str | None = None):
    esperado = os.environ.get("PONTE_TOKEN")
    if not esperado or token != esperado:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        medidor.conectar(ws)
    except ErroDeMedicao as e:
        await ws.send_json({"tipo": "erro", "mensagem": str(e)})
        await ws.close(code=1008)
        return
    await transmitir()  # acende o semáforo no palco
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("tipo") == "resultado":
                medidor.entregar_resultado(msg)
            elif msg.get("tipo") == "erro":
                medidor.entregar_erro(str(msg.get("mensagem", "Falha na câmera.")))
    except WebSocketDisconnect:
        pass
    finally:
        medidor.desconectar(ws)
        await transmitir()  # apaga o semáforo
```

- [ ] **Step 4: Rodar e ver falhar no import**

Run: `python -m pytest tests/test_jogo_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jogo.envio'`. É o
esperado: a Task 9 cria esse módulo e fecha o ciclo.

- [ ] **Step 5: Commit**

```bash
git add jogo/main.py tests/test_jogo_api.py
git commit -m "feat(jogo): websocket da ponte e comandos de host com token"
```

---

## Task 9: Envio para a API de produção

**Files:**
- Create: `jogo/envio.py`
- Test: `tests/test_jogo_envio.py`

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_jogo_envio.py`:

```python
"""Envio da medição da feira para a API de produção."""
import jogo.envio as envio


class RespostaFalsa:
    status_code = 200


def test_monta_o_payload_com_a_regiao_da_feira():
    payload = envio.montar_payload({"altura_cm": 17.5, "categoria": "ALTA"})
    # Dezenas de medições de feira não podem entrar como se fossem da rodovia.
    assert payload["regiao"] == "Feira de Ciências"
    assert payload["altura_cm"] == 17.5
    assert payload["nivel_risco"] == "ALTA"


def test_traduz_media_acentuada_para_o_enum_da_api():
    payload = envio.montar_payload({"altura_cm": 5.0, "categoria": "MÉDIA"})
    assert payload["nivel_risco"] == "MEDIA"


def test_inclui_clima_quando_a_ponte_mandou():
    payload = envio.montar_payload({
        "altura_cm": 5.0, "categoria": "BAIXA",
        "temperatura_c": 25.7, "clima": "Nublado",
    })
    assert payload["temperatura_c"] == 25.7
    assert payload["clima"] == "Nublado"


def test_omite_clima_quando_nao_veio():
    payload = envio.montar_payload({"altura_cm": 5.0, "categoria": "BAIXA"})
    assert "temperatura_c" not in payload
    assert "clima" not in payload


def test_altura_none_vai_como_zero():
    payload = envio.montar_payload({"altura_cm": None, "categoria": "AUSENTE"})
    assert payload["altura_cm"] == 0.0


def test_enviar_faz_post_com_a_chave_de_escrita(monkeypatch):
    monkeypatch.setenv("API_URL", "https://api.test")
    monkeypatch.setenv("API_KEY_WRITE", "chave")
    chamadas = []

    def post_falso(url, json, headers, timeout):
        chamadas.append((url, json, headers, timeout))
        return RespostaFalsa()

    monkeypatch.setattr(envio.requests, "post", post_falso)
    envio.enviar({"altura_cm": 17.5, "categoria": "ALTA"})

    url, corpo, headers, _timeout = chamadas[0]
    assert url == "https://api.test/leituras"
    assert headers["X-API-Key"] == "chave"
    assert corpo["regiao"] == "Feira de Ciências"


def test_enviar_sem_chave_nao_faz_post(monkeypatch):
    monkeypatch.delenv("API_KEY_WRITE", raising=False)
    chamadas = []

    def post_falso(*args, **kwargs):
        chamadas.append(1)
        return RespostaFalsa()

    monkeypatch.setattr(envio.requests, "post", post_falso)
    envio.enviar({"altura_cm": 17.5, "categoria": "ALTA"})
    assert chamadas == []


def test_enviar_engole_erro_de_rede(monkeypatch):
    monkeypatch.setenv("API_KEY_WRITE", "chave")

    def explodir(*args, **kwargs):
        raise envio.requests.RequestException("sem rede")

    monkeypatch.setattr(envio.requests, "post", explodir)
    # O jogo nunca pode cair por causa da API de produção.
    envio.enviar({"altura_cm": 17.5, "categoria": "ALTA"})
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_envio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jogo.envio'`

- [ ] **Step 3: Implementar**

Crie `jogo/envio.py`:

```python
"""POST da medição da feira para a API de produção.

Em background e silencioso: o jogo revela o valor na hora e nunca espera a
rede. Falha de envio não é problema do visitante.

A região é fixa em "Feira de Ciências" e não vem da calibração: um dia de
feira são dezenas de medições, e entrar como "Rod. Anchieta" contaminaria a
série temporal da rodovia com dado que não é dela.
"""
from __future__ import annotations

import os
import sys
import threading

import requests

REGIAO_DA_FEIRA = "Feira de Ciências"
TIMEOUT_S = 15


def montar_payload(resultado: dict) -> dict:
    altura = resultado.get("altura_cm")
    payload = {
        "regiao": REGIAO_DA_FEIRA,
        "altura_cm": altura if altura is not None else 0.0,
        # A API aceita MEDIA sem acento; o pipeline produz "MÉDIA".
        "nivel_risco": str(resultado.get("categoria", "")).replace("MÉDIA", "MEDIA"),
    }
    if resultado.get("temperatura_c") is not None:
        payload["temperatura_c"] = resultado["temperatura_c"]
    if resultado.get("clima"):
        payload["clima"] = resultado["clima"]
    return payload


def enviar(resultado: dict) -> None:
    chave = os.environ.get("API_KEY_WRITE")
    if not chave:
        print("AVISO: API_KEY_WRITE ausente, medição da feira não enviada",
              file=sys.stderr)
        return
    base = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
    try:
        resposta = requests.post(
            f"{base}/leituras",
            json=montar_payload(resultado),
            headers={"X-API-Key": chave},
            timeout=TIMEOUT_S,
        )
        if resposta.status_code >= 400:
            print(f"AVISO: API respondeu {resposta.status_code}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"AVISO: envio para a API falhou ({e})", file=sys.stderr)


def enviar_em_background(resultado: dict) -> None:
    """Dispara e esquece. `requests` é síncrono e travaria o event loop."""
    threading.Thread(target=enviar, args=(resultado,), daemon=True).start()
```

- [ ] **Step 4: Rodar a suíte do jogo inteira**

Run: `python -m pytest tests/test_jogo_sala.py tests/test_jogo_medicao.py tests/test_jogo_envio.py tests/test_jogo_api.py -v`
Expected: PASS em tudo — 63 da sala, 8 da medição, 8 do envio, 28 da API.

- [ ] **Step 5: Commit**

```bash
git add jogo/envio.py tests/test_jogo_envio.py
git commit -m "feat(jogo): envio da medicao da feira em background"
```

---

## Task 10: Tela do celular

**Files:**
- Modify: `jogo/templates/controle.html`
- Modify: `jogo/static/comum.css`
- Create: `jogo/static/controle.css`
- Create: `jogo/static/controle.js`

Frontend não entra em TDD aqui: não há harness de navegador no repositório, e
montar um para duas telas de feira seria desproporcional. A verificação é
manual, com passos e observações explícitas no Step 5.

- [ ] **Step 1: Escrever a paleta compartilhada**

Substitua o conteúdo de `jogo/static/comum.css`:

```css
/* Mesma paleta de scripts/gerar_orcamento_pdf.py, para o jogo não parecer
   anexo de outro projeto. Branco manda, verde pontua. */
:root {
  --verde-escuro: #1B5E20;
  --verde-medio: #2E7D32;
  --verde-claro: #E8F5E9;
  --branco: #FFFFFF;
  --cinza-texto: #212121;
  --cinza-sec: #616161;
  --raio: 12px;
  --sombra: 0 2px 8px rgba(0, 0, 0, 0.08);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  /* Font stack do sistema, sem Google Fonts: um <link> de fonte que não
     carrega faz o layout virar outro no meio da apresentação. */
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--cinza-texto);
  background: var(--branco);
}

button {
  font: inherit;
  cursor: pointer;
  border: none;
  border-radius: var(--raio);
  background: var(--verde-escuro);
  color: var(--branco);
  padding: 16px 24px;
  font-weight: 600;
}

button:disabled { background: var(--cinza-sec); cursor: not-allowed; }

.oculto { display: none !important; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Escrever o HTML do controle**

Substitua `jogo/templates/controle.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grama Webcam</title>
  <link rel="stylesheet" href="/static/comum.css">
  <link rel="stylesheet" href="/static/controle.css">
</head>
<body>
  <main class="tela">
    <h1 class="marca">Grama Webcam</h1>

    <section id="tela-entrada" class="cartao">
      <p class="pergunta">Quanto mede essa grama?</p>
      <label for="nome">Seu nome</label>
      <input id="nome" type="text" maxlength="20" autocomplete="off" placeholder="Ana">
      <button id="botao-entrar">Entrar no jogo</button>
    </section>

    <section id="tela-chute" class="cartao oculto">
      <p class="ola">Oi, <strong id="meu-nome"></strong>!</p>
      <label for="chute">Seu chute, em centímetros</label>
      <input id="chute" type="number" inputmode="decimal" min="0" max="200"
             step="0.1" placeholder="15,0">
      <button id="botao-chutar">Mandar chute</button>
      <p id="confirmacao" class="confirmacao oculto"></p>
    </section>

    <section id="tela-espera" class="cartao oculto">
      <p id="texto-espera" class="olhe">Olha pra tela grande!</p>
    </section>

    <section id="tela-resultado" class="cartao oculto">
      <p id="posicao" class="posicao"></p>
      <dl class="placar">
        <dt>Seu chute</dt><dd id="meu-chute"></dd>
        <dt>Valor real</dt><dd id="valor-real"></dd>
        <dt>Você errou por</dt><dd id="meu-erro"></dd>
      </dl>
    </section>

    <p id="aviso" class="aviso oculto"></p>
  </main>
  <script src="/static/controle.js"></script>
</body>
</html>
```

- [ ] **Step 3: Escrever o CSS do controle**

Crie `jogo/static/controle.css`:

```css
.tela { max-width: 420px; margin: 0 auto; padding: 24px 16px 40px; }

.marca {
  font-size: 1rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--verde-medio); margin: 0 0 24px;
}

.cartao {
  background: var(--verde-claro); border-radius: var(--raio);
  padding: 24px; box-shadow: var(--sombra);
}

.pergunta {
  font-size: 1.5rem; font-weight: 700; margin: 0 0 24px;
  color: var(--verde-escuro);
}

.ola { margin: 0 0 20px; }

label {
  display: block; font-size: 0.875rem; color: var(--cinza-sec);
  margin-bottom: 8px;
}

input {
  width: 100%; padding: 16px; font-size: 1.25rem; margin-bottom: 16px;
  border: 2px solid var(--branco); border-radius: var(--raio);
  background: var(--branco); color: var(--cinza-texto);
}

input:focus { outline: 2px solid var(--verde-medio); }

button { width: 100%; }

.confirmacao { margin: 16px 0 0; color: var(--verde-escuro); font-size: 0.9375rem; }

.olhe {
  font-size: 1.75rem; font-weight: 700; text-align: center; margin: 24px 0;
  color: var(--verde-escuro);
}

.posicao {
  font-size: 2rem; font-weight: 800; margin: 0 0 20px;
  color: var(--verde-escuro);
}

.placar { display: grid; grid-template-columns: auto auto; gap: 8px 16px; margin: 0; }
.placar dt { color: var(--cinza-sec); font-size: 0.9375rem; }
.placar dd { margin: 0; font-weight: 700; text-align: right; }

.aviso {
  margin-top: 16px; padding: 12px 16px; border-radius: var(--raio);
  background: #FFF3E0; color: #8D4E00; font-size: 0.9375rem;
}
```

- [ ] **Step 4: Escrever o JS do controle**

Crie `jogo/static/controle.js`:

```js
// Controle do celular. Guarda o próprio id no localStorage: o celular bloqueia
// a tela, o socket cai, e ao voltar o jogador precisa cair na mesma cadeira em
// vez de virar um fantasma na lista.
(function () {
  "use strict";

  var CHAVE_ID = "grama-jogo-id";
  var CHAVE_CHUTE = "grama-jogo-chute";
  var ESPERA_RECONEXAO_MS = 1500;

  var el = function (id) { return document.getElementById(id); };

  var TELAS = ["tela-entrada", "tela-chute", "tela-espera", "tela-resultado"];
  function mostrar(id) {
    TELAS.forEach(function (t) {
      el(t).classList.toggle("oculto", t !== id);
    });
  }

  function avisar(texto) {
    el("aviso").textContent = texto || "";
    el("aviso").classList.toggle("oculto", !texto);
  }

  function cm(valor) {
    // Última linha de defesa: se um reset esvaziar a sala entre o broadcast e
    // o render, `toFixed` em null derrubaria a tela na frente do grupo. A sala
    // já impede isso, mas uma tela quebrada numa apresentação não tem segunda
    // chance, e o custo aqui é uma linha.
    if (typeof valor !== "number" || !isFinite(valor)) { return "—"; }
    return valor.toFixed(1).replace(".", ",") + " cm";
  }

  var meuId = localStorage.getItem(CHAVE_ID);
  var meuChute = localStorage.getItem(CHAVE_CHUTE);
  var ws = null;

  function conectar() {
    var protocolo = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(protocolo + "//" + location.host + "/ws/jogador");

    ws.onopen = function () {
      avisar("");
      if (meuId) { ws.send(JSON.stringify({ cmd: "voltar", id: meuId })); }
    };

    ws.onmessage = function (evento) {
      var msg = JSON.parse(evento.data);
      if (msg.tipo === "voce") {
        meuId = msg.id;
        localStorage.setItem(CHAVE_ID, meuId);
        el("meu-nome").textContent = msg.nome;
        mostrar("tela-chute");
        avisar("");
        return;
      }
      if (msg.tipo === "erro") { avisar(msg.mensagem); return; }
      if (msg.tipo === "estado") { aplicarEstado(msg); }
    };

    // O celular dorme e o socket cai. 1,5s é curto o bastante para a pessoa não
    // perceber e longo o bastante para não martelar o servidor.
    ws.onclose = function () {
      avisar("Reconectando…");
      setTimeout(conectar, ESPERA_RECONEXAO_MS);
    };
  }

  function aplicarEstado(estado) {
    var souJogador = estado.jogadores.some(function (j) { return j.id === meuId; });

    if (!souJogador) {
      // Saiu da sala (nova rodada, por exemplo): limpa e volta pra entrada.
      localStorage.removeItem(CHAVE_ID);
      localStorage.removeItem(CHAVE_CHUTE);
      meuId = null;
      meuChute = null;
      el("chute").value = "";
      el("confirmacao").classList.add("oculto");
      mostrar("tela-entrada");
      avisar(estado.aberta ? "" : "A sala está travada. Fale com o apresentador.");
      return;
    }

    if (estado.estado === "AGUARDANDO") {
      mostrar("tela-chute");
      if (meuChute) {
        el("chute").value = meuChute;
        el("confirmacao").textContent =
          "Chute enviado: " + meuChute.replace(".", ",") +
          " cm — pode mudar até a medição.";
        el("confirmacao").classList.remove("oculto");
      }
      avisar(estado.erro || "");
      return;
    }

    if (estado.estado === "MEDINDO" || estado.estado === "REVELANDO") {
      el("texto-espera").textContent = "Olha pra tela grande!";
      mostrar("tela-espera");
      avisar("");
      return;
    }

    if (estado.estado === "RESULTADO") {
      var minha = null;
      estado.ranking.forEach(function (linha) {
        if (linha.id === meuId) { minha = linha; }
      });
      if (!minha) {
        el("texto-espera").textContent = "Você não chutou nessa rodada!";
        mostrar("tela-espera");
        return;
      }
      el("posicao").textContent = minha.posicao + "º lugar";
      el("meu-chute").textContent = cm(minha.chute_cm);
      el("valor-real").textContent = cm(estado.altura_cm);
      el("meu-erro").textContent = cm(minha.erro_cm);
      mostrar("tela-resultado");
    }
  }

  el("botao-entrar").onclick = function () {
    var nome = el("nome").value.trim();
    if (!nome) { avisar("Digite um nome."); return; }
    ws.send(JSON.stringify({ cmd: "entrar", nome: nome }));
  };

  el("botao-chutar").onclick = function () {
    // Vírgula é o separador que o teclado brasileiro oferece no celular.
    var valor = parseFloat(el("chute").value.replace(",", "."));
    if (isNaN(valor)) { avisar("Digite um número."); return; }
    meuChute = valor.toFixed(1);
    localStorage.setItem(CHAVE_CHUTE, meuChute);
    ws.send(JSON.stringify({ cmd: "chutar", id: meuId, valor_cm: valor }));
  };

  conectar();
})();
```

- [ ] **Step 5: Verificar à mão**

```powershell
$env:HOST_TOKEN="abc"; $env:PONTE_TOKEN="def"; python -m uvicorn jogo.main:app --reload
```

Abra `http://localhost:8000` em duas abas e confirme, uma por uma:

1. Digitar "Ana" e entrar → aparece "Oi, Ana!" e o campo de chute.
2. Na outra aba, entrar como "Ana" → aviso "Esse nome já está em uso. Escolha outro."
3. Na outra aba, entrar como "Bruno" e mandar 15 → "Chute enviado: 15,0 cm — pode mudar até a medição."
4. Recarregar a aba do Bruno (F5) → volta direto para a tela de chute com 15,0 preenchido, **sem pedir o nome de novo**.
5. Mandar chute 300 → aviso "O chute tem que estar entre 0 e 200 cm."
6. Estreitar a janela para 375px de largura → nada corta e não aparece rolagem horizontal.

- [ ] **Step 6: Commit**

```bash
git add jogo/templates/controle.html jogo/static/comum.css jogo/static/controle.css jogo/static/controle.js
git commit -m "feat(jogo): tela do celular com reconexao na mesma cadeira"
```

---

## Task 11: Tela do palco

**Files:**
- Modify: `jogo/templates/palco.html`
- Create: `jogo/static/palco.css`
- Create: `jogo/static/palco.js`

- [ ] **Step 1: Escrever o HTML do palco**

Substitua `jogo/templates/palco.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grama Webcam — palco</title>
  <link rel="stylesheet" href="/static/comum.css">
  <link rel="stylesheet" href="/static/palco.css">
</head>
<body>
  <header class="barra">
    <h1 class="marca">Grama Webcam</h1>
    <p id="semaforo" class="semaforo">○ câmera offline</p>
  </header>

  <main class="palco">
    <section id="cena-aguardando" class="cena">
      <div class="coluna-qr">
        <img src="/qr.svg" alt="QR code para entrar no jogo" class="qr">
        <p class="legenda-qr">escaneia e entra</p>
      </div>
      <div class="coluna-jogo">
        <p class="pergunta">Quanto mede essa grama?</p>
        <ol id="cadeiras" class="cadeiras"></ol>
      </div>
    </section>

    <section id="cena-medindo" class="cena oculto">
      <p class="medindo">capturando…</p>
      <div class="pulso"></div>
    </section>

    <section id="cena-revelando" class="cena oculto">
      <div class="lamina-caixa"><div id="lamina" class="lamina"></div></div>
      <p id="contador" class="contador">0,0 cm</p>
    </section>

    <section id="cena-resultado" class="cena oculto">
      <p id="valor-final" class="valor-final"></p>
      <ol id="podio" class="podio"></ol>
      <img id="imagem-anotada" class="imagem-anotada oculto"
           alt="Como a câmera viu a grama">
    </section>
  </main>

  <footer class="controles">
    <button id="botao-medir">📷 Medir grama</button>
    <span id="contagem-chutes" class="contagem"></span>
    <button id="botao-travar" class="secundario">Travar sala</button>
    <button id="botao-nova" class="secundario">Nova rodada</button>
    <span id="aviso-host" class="aviso-host"></span>
  </footer>

  <script src="/static/palco.js"></script>
</body>
</html>
```

- [ ] **Step 2: Escrever o CSS do palco**

Crie `jogo/static/palco.css`:

```css
/* Alvo: 1366x768, a tela do notebook comum. */
body { display: flex; flex-direction: column; min-height: 100vh; }

.barra {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 32px; border-bottom: 1px solid var(--verde-claro);
}

.marca {
  font-size: 1.125rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--verde-medio); margin: 0;
}

.semaforo { margin: 0; font-size: 0.9375rem; color: var(--cinza-sec); font-weight: 600; }
.semaforo.ligado { color: var(--verde-medio); }

.palco {
  flex: 1; display: flex; align-items: center; justify-content: center;
  padding: 24px 32px;
}

.cena { width: 100%; max-width: 1100px; }

#cena-aguardando { display: flex; gap: 48px; align-items: center; }

.coluna-qr { text-align: center; flex-shrink: 0; }
.qr { width: 220px; height: 220px; display: block; }
.legenda-qr { color: var(--cinza-sec); margin: 12px 0 0; font-size: 0.9375rem; }

.coluna-jogo { flex: 1; }

.pergunta {
  font-size: 2.25rem; font-weight: 800; color: var(--verde-escuro);
  margin: 0 0 24px;
}

.cadeiras { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }

.cadeiras li {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px; border-radius: var(--raio);
  background: var(--branco); border: 2px solid var(--verde-claro);
  font-size: 1.125rem;
  /* Cadeira acendendo: é o feedback de que o toque no celular chegou. Sem
     isso a pessoa duvida e aperta de novo. */
  transition: background 300ms ease, border-color 300ms ease;
}

.cadeiras li.ocupada { background: var(--verde-claro); border-color: var(--verde-medio); }
.cadeiras li.vazia { color: var(--cinza-sec); }
.cadeiras li .marca-chute { font-weight: 700; color: var(--verde-escuro); }

.medindo {
  font-size: 2.5rem; font-weight: 800; text-align: center;
  color: var(--verde-escuro); margin: 0 0 24px;
}

.pulso {
  height: 8px; border-radius: 4px; background: var(--verde-claro);
  overflow: hidden; position: relative; max-width: 480px; margin: 0 auto;
}

.pulso::after {
  content: ""; position: absolute; inset: 0; width: 40%;
  background: var(--verde-medio); border-radius: 4px;
  animation: desliza 1.1s ease-in-out infinite;
}

@keyframes desliza {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(250%); }
}

#cena-revelando { display: flex; align-items: flex-end; justify-content: center; gap: 64px; }

/* A lâmina crescendo dá escala ao número: "17,5 cm" não significa nada sozinho. */
.lamina-caixa { height: 320px; width: 80px; display: flex; align-items: flex-end; }

.lamina {
  width: 100%; height: 0%;
  background: linear-gradient(to top, var(--verde-escuro), var(--verde-medio));
  border-radius: 40px 40px 4px 4px;
}

.contador {
  font-size: 7rem; font-weight: 800; color: var(--verde-escuro); margin: 0;
  font-variant-numeric: tabular-nums;
}

.valor-final {
  font-size: 3.5rem; font-weight: 800; color: var(--verde-escuro);
  margin: 0 0 24px; text-align: center;
}

.podio {
  list-style: none; margin: 0 auto 24px; padding: 0;
  display: grid; gap: 12px; max-width: 620px;
}

.podio li {
  display: flex; align-items: center; gap: 16px;
  padding: 16px 24px; border-radius: var(--raio);
  background: var(--verde-claro); font-size: 1.25rem;
  opacity: 0; transform: translateY(24px);
}

.podio li.entrou { animation: sobe 400ms ease-out forwards; }
@keyframes sobe { to { opacity: 1; transform: translateY(0); } }

.podio li.campeao {
  background: var(--verde-escuro); color: var(--branco);
  font-size: 1.75rem; font-weight: 800;
}

/* Overshoot é o que faz parecer comemoração, e não transição. */
.podio li.campeao.entrou { animation: comemora 600ms cubic-bezier(.34,1.56,.64,1) forwards; }
@keyframes comemora {
  0% { opacity: 0; transform: scale(0.8); }
  100% { opacity: 1; transform: scale(1); }
}

.podio li .pos { font-weight: 800; min-width: 2.5rem; }
.podio li .nome { flex: 1; }
.podio li .erro { color: var(--cinza-sec); font-size: 1rem; }
.podio li.campeao .erro { color: var(--verde-claro); }

.imagem-anotada {
  display: block; max-width: 480px; margin: 0 auto;
  border-radius: var(--raio); box-shadow: var(--sombra);
}

.controles {
  display: flex; align-items: center; gap: 16px;
  padding: 20px 32px; border-top: 1px solid var(--verde-claro);
}

.controles button { width: auto; }
.controles .secundario {
  background: var(--branco); color: var(--verde-escuro);
  border: 2px solid var(--verde-claro);
}

.contagem { color: var(--cinza-sec); }
.aviso-host { margin-left: auto; color: #8D4E00; }
```

- [ ] **Step 3: Escrever o JS do palco**

Crie `jogo/static/palco.js`:

```js
// Palco: a tela que o grupo olha junto. Só reage ao estado que o servidor
// transmite — não guarda jogo nenhum.
(function () {
  "use strict";

  var DURACAO_CONTADOR_MS = 2200;
  var MAX_CADEIRAS = 5;
  var ESCALA_LAMINA_CM = 30;   // 30 cm enche a lâmina; acima disso ela satura
  var INTERVALO_PODIO_MS = 300;
  var ESPERA_RECONEXAO_MS = 1500;

  var el = function (id) { return document.getElementById(id); };
  var token = new URLSearchParams(location.search).get("token") || "";
  var ws = null;
  var estadoAnterior = null;

  var CENAS = ["cena-aguardando", "cena-medindo", "cena-revelando", "cena-resultado"];
  function cena(id) {
    CENAS.forEach(function (c) { el(c).classList.toggle("oculto", c !== id); });
  }

  function cm(valor) {
    // Última linha de defesa: se um reset esvaziar a sala entre o broadcast e
    // o render, `toFixed` em null derrubaria a tela na frente do grupo. A sala
    // já impede isso, mas uma tela quebrada numa apresentação não tem segunda
    // chance, e o custo aqui é uma linha.
    if (typeof valor !== "number" || !isFinite(valor)) { return "—"; }
    return valor.toFixed(1).replace(".", ",") + " cm";
  }

  function conectar() {
    var protocolo = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(
      protocolo + "//" + location.host + "/ws/host?token=" + encodeURIComponent(token)
    );
    ws.onmessage = function (evento) {
      var msg = JSON.parse(evento.data);
      if (msg.tipo === "erro") { el("aviso-host").textContent = msg.mensagem; return; }
      if (msg.tipo === "estado") { aplicar(msg); }
    };
    ws.onclose = function () {
      el("aviso-host").textContent = "Conexão caiu. Reconectando…";
      setTimeout(conectar, ESPERA_RECONEXAO_MS);
    };
  }

  function aplicar(estado) {
    el("semaforo").textContent = estado.ponte_conectada
      ? "● câmera conectada" : "○ câmera offline";
    el("semaforo").classList.toggle("ligado", estado.ponte_conectada);

    el("botao-travar").textContent = estado.aberta ? "Travar sala" : "Abrir sala";
    el("contagem-chutes").textContent =
      estado.quantos_chutaram + "/" + estado.jogadores.length + " chutaram";

    el("botao-medir").disabled = !(
      estado.estado === "AGUARDANDO" &&
      estado.ponte_conectada &&
      estado.quantos_chutaram > 0
    );

    // Motivo escrito na tela: sem isso você clica em MEDIR com a ponte caída e
    // fica esperando um fantasma na frente do grupo.
    if (estado.erro) {
      el("aviso-host").textContent = estado.erro;
    } else if (!estado.ponte_conectada) {
      el("aviso-host").textContent = "A ponte da câmera não está conectada.";
    } else if (estado.estado === "AGUARDANDO" && estado.quantos_chutaram === 0) {
      el("aviso-host").textContent = "Ninguém chutou ainda.";
    } else {
      el("aviso-host").textContent = "";
    }

    desenharCadeiras(estado);

    var mudouDeEstado = !estadoAnterior || estadoAnterior.estado !== estado.estado;

    if (estado.estado === "AGUARDANDO") {
      cena("cena-aguardando");
    } else if (estado.estado === "MEDINDO") {
      cena("cena-medindo");
    } else if (estado.estado === "REVELANDO") {
      // Só reanima na transição: um broadcast extra não pode reiniciar a
      // contagem no meio.
      if (mudouDeEstado) { cena("cena-revelando"); animarContador(estado.altura_cm); }
    } else if (estado.estado === "RESULTADO") {
      if (mudouDeEstado) { cena("cena-resultado"); montarPodio(estado); }
    }

    estadoAnterior = estado;
  }

  function desenharCadeiras(estado) {
    var lista = el("cadeiras");
    lista.innerHTML = "";
    for (var i = 0; i < MAX_CADEIRAS; i++) {
      var jogador = estado.jogadores[i];
      var li = document.createElement("li");
      if (jogador) {
        li.className = "ocupada";
        var nome = document.createElement("span");
        nome.textContent = (i + 1) + "  " + jogador.nome;
        var marca = document.createElement("span");
        marca.className = "marca-chute";
        // Só "chutou", nunca o valor: todos olham esta tela.
        marca.textContent = jogador.chutou ? "✓ chutou" : "… pensando";
        li.appendChild(nome);
        li.appendChild(marca);
      } else {
        li.className = "vazia";
        li.textContent = (i + 1) + "  vaga livre";
      }
      lista.appendChild(li);
    }
  }

  function animarContador(alvoCm) {
    // requestAnimationFrame e não CSS: o TEXTO muda a cada frame, não só o
    // estilo. O ease-out desacelera no fim, onde mora o suspense.
    var inicio = null;
    var lamina = el("lamina");
    var contador = el("contador");

    function passo(agora) {
      if (inicio === null) { inicio = agora; }
      var t = Math.min((agora - inicio) / DURACAO_CONTADOR_MS, 1);
      var suave = 1 - Math.pow(1 - t, 3);
      var valor = alvoCm * suave;
      contador.textContent = cm(valor);
      lamina.style.height = Math.min(valor / ESCALA_LAMINA_CM, 1) * 100 + "%";
      if (t < 1) { requestAnimationFrame(passo); }
    }

    contador.textContent = cm(0);
    lamina.style.height = "0%";
    requestAnimationFrame(passo);
  }

  function montarPodio(estado) {
    el("valor-final").textContent = estado.margem_cm
      ? cm(estado.altura_cm) + "  ±" + cm(estado.margem_cm)
      : cm(estado.altura_cm);

    var podio = el("podio");
    podio.innerHTML = "";

    // Campeão primeiro, premiando o vencedor no pico da atenção. O intervalo
    // entre as entradas dá tempo da plateia ler cada nome.
    estado.ranking.slice(0, 3).forEach(function (linha, indice) {
      var li = document.createElement("li");
      if (indice === 0) { li.className = "campeao"; }

      var pos = document.createElement("span");
      pos.className = "pos";
      pos.textContent = linha.posicao + "º";

      var nome = document.createElement("span");
      nome.className = "nome";
      nome.textContent = linha.nome;

      var erro = document.createElement("span");
      erro.className = "erro";
      erro.textContent = "chutou " + cm(linha.chute_cm) +
        " · errou por " + cm(linha.erro_cm);

      li.appendChild(pos);
      li.appendChild(nome);
      li.appendChild(erro);
      podio.appendChild(li);

      setTimeout(function () { li.classList.add("entrou"); },
                 indice * INTERVALO_PODIO_MS);
    });

    var imagem = el("imagem-anotada");
    if (estado.imagem_b64) {
      imagem.src = "data:image/png;base64," + estado.imagem_b64;
      imagem.classList.remove("oculto");
    } else {
      imagem.classList.add("oculto");
    }
  }

  el("botao-medir").onclick = function () {
    ws.send(JSON.stringify({ cmd: "medir" }));
  };

  el("botao-nova").onclick = function () {
    ws.send(JSON.stringify({ cmd: "nova_rodada" }));
  };

  el("botao-travar").onclick = function () {
    ws.send(JSON.stringify({
      cmd: "travar",
      travada: el("botao-travar").textContent === "Travar sala",
    }));
  };

  conectar();
})();
```

- [ ] **Step 4: Criar uma ponte de mentira para verificar sem webcam**

Crie `scratch_ponte_falsa.py` na raiz. É arquivo temporário: **não comitar**.

```python
"""Ponte de mentira para verificar o palco sem webcam."""
import asyncio
import json

import websockets

URL = "ws://localhost:8000/ws/ponte?token=def"


async def principal():
    async with websockets.connect(URL) as ws:
        print("ponte falsa conectada")
        async for bruto in ws:
            if json.loads(bruto).get("cmd") == "medir":
                print("ordem recebida, respondendo 17.5")
                await asyncio.sleep(1.5)  # finge o tempo do pipeline
                await ws.send(json.dumps({
                    "tipo": "resultado", "altura_cm": 17.5, "margem_cm": 0.4,
                    "categoria": "ALTA", "imagem_b64": None,
                }))


asyncio.run(principal())
```

```bash
pip install websockets
```

- [ ] **Step 5: Verificar à mão**

Em dois terminais:

```powershell
# terminal 1
$env:HOST_TOKEN="abc"; $env:PONTE_TOKEN="def"; python -m uvicorn jogo.main:app

# terminal 2
python scratch_ponte_falsa.py
```

Abra `http://localhost:8000/host?token=abc` e confirme:

1. Com a ponte falsa **parada** → semáforo "○ câmera offline", MEDIR desabilitado, aviso "A ponte da câmera não está conectada."
2. Subindo a ponte falsa → semáforo vira "● câmera conectada".
3. Sem ninguém ter chutado → MEDIR desabilitado, aviso "Ninguém chutou ainda."
4. Entrar com duas abas de celular e chutar 16 e 19 → as cadeiras acendem com "✓ chutou", a contagem mostra "2/2 chutaram", MEDIR habilita.
5. Clicar MEDIR → cena "capturando…" com a barra deslizando; os celulares mostram "Olha pra tela grande!".
6. ~1,5s depois → o contador sobe de 0,0 até 17,5 cm desacelerando no fim, e a lâmina cresce junto.
7. ~2,6s depois → pódio com o campeão primeiro, em verde escuro e maior, e o 2º entrando 300ms depois.
8. Nos celulares → cartão pessoal com posição, chute, valor real e erro.
9. Clicar "Travar sala" → o texto vira "Abrir sala"; uma aba nova não consegue entrar.
10. Clicar "Nova rodada" → cadeiras voltam a "vaga livre", a sala reabre, e os celulares voltam à tela de nome.
11. Derrubar a ponte falsa (Ctrl+C) no meio de uma medição → o palco volta para `AGUARDANDO` com o aviso da falha e **os chutes continuam lá** (a contagem não zera).
12. Recarregar o palco (F5) → a sala continua exatamente como estava.

- [ ] **Step 6: Apagar o arquivo temporário e commitar**

```bash
rm scratch_ponte_falsa.py
git add jogo/templates/palco.html jogo/static/palco.css jogo/static/palco.js
git commit -m "feat(jogo): tela do palco com revelacao animada e podio"
```

---

## Task 12: A ponte

**Files:**
- Create: `jogo/ponte.py`
- Create: `requirements-ponte.txt`
- Test: `tests/test_jogo_ponte.py`

- [ ] **Step 1: Criar o requirements da ponte**

Crie `requirements-ponte.txt`:

```
-r requirements-station.txt
websockets
```

```bash
pip install -r requirements-ponte.txt
```

- [ ] **Step 2: Escrever os testes que falham**

Crie `tests/test_jogo_ponte.py`:

```python
"""A ponte que roda no notebook da feira.

Importar `jogo.ponte` puxa `medir_grama`, que importa `cv2` no topo. Em máquina
sem OpenCV a suíte pula estes testes em vez de falhar — é o mesmo motivo pelo
qual o serviço hospedado não instala `requirements-station.txt`.
"""
import json

import pytest

pytest.importorskip("cv2")

import numpy as np  # noqa: E402

from jogo import ponte  # noqa: E402

CALIBRACAO = {"px_por_cm": 17.5, "y_chao": 433}


def test_calibracao_ausente_impede_o_boot(tmp_path, monkeypatch):
    monkeypatch.setattr(ponte, "CALIBRATION_PATH", str(tmp_path / "nao-existe.json"))
    # Falhar às 8h é melhor que falhar no primeiro clique com cinco pessoas
    # esperando.
    with pytest.raises(SystemExit):
        ponte.carregar_calibracao_ou_sair()


def test_medir_usa_o_pipeline_e_devolve_o_payload(monkeypatch, tmp_path):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mascara = np.zeros((480, 640), dtype=np.uint8)
    mascara[300:433, :] = 255  # faixa verde começando 133px acima do chão

    chamadas = []

    monkeypatch.setattr(ponte.medir_grama, "capture_frames",
                        lambda n, i, b: chamadas.append("capture") or [frame] * n)
    monkeypatch.setattr(ponte.medir_grama, "apply_mask",
                        lambda f: chamadas.append("mask") or mascara)
    monkeypatch.setattr(ponte.medir_grama, "save_debug",
                        lambda *a, **k: chamadas.append("debug"))
    monkeypatch.setattr(ponte, "DEBUG_PATH", str(tmp_path / "debug.png"))
    monkeypatch.setattr(ponte, "ler_imagem_b64", lambda path: "iVBOR")

    payload = ponte.medir(CALIBRACAO)

    assert payload["tipo"] == "resultado"
    assert payload["altura_cm"] == pytest.approx(7.6, abs=0.1)
    assert payload["categoria"] == "ALTA"
    assert payload["imagem_b64"] == "iVBOR"
    assert chamadas.count("capture") == 1
    assert chamadas.count("debug") == 1


def test_medir_sem_verde_devolve_erro_em_vez_de_zero(monkeypatch, tmp_path):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    vazia = np.zeros((480, 640), dtype=np.uint8)

    monkeypatch.setattr(ponte.medir_grama, "capture_frames", lambda n, i, b: [frame] * n)
    monkeypatch.setattr(ponte.medir_grama, "apply_mask", lambda f: vazia)
    monkeypatch.setattr(ponte.medir_grama, "save_debug", lambda *a, **k: None)
    monkeypatch.setattr(ponte, "DEBUG_PATH", str(tmp_path / "debug.png"))

    payload = ponte.medir(CALIBRACAO)

    # Ranquear gente num 0,0 que foi erro de enquadramento deslegitima o sistema.
    assert payload["tipo"] == "erro"
    assert "grama" in payload["mensagem"].lower()


def test_medir_transforma_falha_de_camera_em_payload_de_erro(monkeypatch):
    def explodir(n, i, b):
        raise RuntimeError("camera nao abriu")

    monkeypatch.setattr(ponte.medir_grama, "capture_frames", explodir)
    payload = ponte.medir(CALIBRACAO)
    assert payload["tipo"] == "erro"
    assert "camera nao abriu" in payload["mensagem"]


def test_espera_do_backoff_cresce_e_tem_teto():
    assert ponte.espera_do_backoff(0) == 1
    assert ponte.espera_do_backoff(1) == 2
    assert ponte.espera_do_backoff(2) == 4
    assert ponte.espera_do_backoff(99) == ponte.BACKOFF_MAX_S


def test_url_do_websocket_usa_wss_em_https(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://jogo.test")
    monkeypatch.setenv("PONTE_TOKEN", "tok")
    assert ponte.url_do_websocket() == "wss://jogo.test/ws/ponte?token=tok"


def test_url_do_websocket_usa_ws_em_http(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "http://localhost:8000/")
    monkeypatch.setenv("PONTE_TOKEN", "tok")
    assert ponte.url_do_websocket() == "ws://localhost:8000/ws/ponte?token=tok"


def test_url_do_websocket_exige_token(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "http://localhost:8000")
    monkeypatch.delenv("PONTE_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        ponte.url_do_websocket()


def test_keep_alive_bate_na_saude(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://jogo.test")
    urls = []
    monkeypatch.setattr(ponte.requests, "get",
                        lambda url, timeout: urls.append(url))
    ponte.bater_no_keep_alive()
    assert urls == ["https://jogo.test/saude"]


def test_keep_alive_engole_erro_de_rede(monkeypatch):
    monkeypatch.setenv("JOGO_URL_PUBLICA", "https://jogo.test")

    def explodir(url, timeout):
        raise ponte.requests.RequestException("sem rede")

    monkeypatch.setattr(ponte.requests, "get", explodir)
    ponte.bater_no_keep_alive()  # não levanta


def test_processar_ignora_ordem_desconhecida():
    assert ponte.processar(json.dumps({"cmd": "sei-la"}), CALIBRACAO) is None


def test_processar_ignora_json_quebrado():
    assert ponte.processar("nao e json", CALIBRACAO) is None
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_jogo_ponte.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jogo.ponte'`

- [ ] **Step 4: Implementar**

Crie `jogo/ponte.py`:

```python
"""Ponte da câmera: roda no notebook da feira, ao lado da webcam.

Conecta PARA FORA, no serviço hospedado, e fica pendurada esperando a ordem de
medir. Conexão de saída dispensa IP público, redirecionamento de porta e
configuração de firewall — e dispensa que os celulares estejam nesta rede.

Não altera `medir_grama.py`: importa as funções do pipeline e as orquestra
headless, sem a janela de preview do OpenCV.

Uso:  python -m jogo.ponte
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys

import requests
import websockets
from dotenv import load_dotenv

import medir_grama

load_dotenv()

CALIBRATION_PATH = "calibration.json"
DEBUG_PATH = "debug/ultima_medicao.png"
BACKOFF_MAX_S = 30
KEEP_ALIVE_INTERVALO_S = 600


# --- configuração ------------------------------------------------------------


def carregar_calibracao_ou_sair() -> dict:
    """Sai com mensagem clara se não houver calibração nesta máquina.

    `px_por_cm` e `y_chao` são da câmera E da posição dela. Trazer o JSON de
    outra máquina produz altura torta, que é pior que erro: é número errado
    com cara de certo.
    """
    try:
        return medir_grama.load_calibration(CALIBRATION_PATH)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        print("Rode `python calibrar.py` NESTA máquina, com a câmera já fixada.",
              file=sys.stderr)
        raise SystemExit(1) from None


def url_do_websocket() -> str:
    base = os.environ.get("JOGO_URL_PUBLICA", "http://localhost:8000").rstrip("/")
    token = os.environ.get("PONTE_TOKEN")
    if not token:
        print("ERRO: PONTE_TOKEN não configurado. Veja .env.example.",
              file=sys.stderr)
        raise SystemExit(1)
    esquema = "wss" if base.startswith("https://") else "ws"
    host = base.split("://", 1)[1]
    return f"{esquema}://{host}/ws/ponte?token={token}"


def espera_do_backoff(tentativa: int) -> int:
    return min(2 ** tentativa, BACKOFF_MAX_S)


# --- medição -----------------------------------------------------------------


def ler_imagem_b64(path: str) -> str | None:
    """A imagem anotada viaja no payload. ~100-300 KB em base64 é aceitável."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def medir(calibracao: dict) -> dict:
    """Roda o pipeline headless e devolve o payload que o jogo espera."""
    y_chao = calibracao["y_chao"]
    px_por_cm = float(calibracao["px_por_cm"])
    try:
        frames = medir_grama.capture_frames(
            medir_grama.FRAME_COUNT,
            medir_grama.CAMERA_INDEX,
            medir_grama.CAMERA_BACKEND,
        )
        mascaras = [medir_grama.apply_mask(f) for f in frames]
        mascara = medir_grama.median_stack(mascaras)
        top_ys = medir_grama.measure_top_y(mascara, medir_grama.SAMPLE_COLS)
        alturas = [
            medir_grama.y_para_altura_cm(y, y_chao, px_por_cm) for y in top_ys
        ]
        nivel, categoria, mediana = medir_grama.classify_frame_cm(
            alturas, medir_grama.FAIXA_BAIXA_CM, medir_grama.FAIXA_MEDIA_CM,
        )
        margem = medir_grama.margem_erro_cm(alturas)
        medir_grama.save_debug(
            frames[-1], mascara, top_ys, alturas, mediana, margem,
            medir_grama.SAMPLE_COLS, y_chao, px_por_cm, categoria, DEBUG_PATH,
        )
    except Exception as e:  # câmera solta, driver, permissão
        return {"tipo": "erro", "mensagem": f"A câmera não respondeu: {e}"}

    if nivel == 0 or mediana is None:
        return {
            "tipo": "erro",
            "mensagem": "Não achei grama no quadro. Confira o enquadramento.",
        }

    return {
        "tipo": "resultado",
        "altura_cm": round(mediana, 1),
        "margem_cm": round(margem, 1) if margem is not None else None,
        "categoria": categoria,
        "imagem_b64": ler_imagem_b64(DEBUG_PATH),
    }


def processar(bruto: str, calibracao: dict) -> dict | None:
    """Traduz a mensagem recebida em payload de resposta, ou None se ignorada."""
    try:
        msg = json.loads(bruto)
    except json.JSONDecodeError:
        return None
    if msg.get("cmd") != "medir":
        return None
    return medir(calibracao)


# --- keep-alive --------------------------------------------------------------


def bater_no_keep_alive() -> None:
    """GET no /saude a cada 10min.

    O free tier da Render hiberna após ~15min de inatividade e demora ~50s para
    acordar. Não há garantia documentada de que um WebSocket pendurado conte
    como atividade, então o GET elimina a dúvida por um custo desprezível.
    """
    base = os.environ.get("JOGO_URL_PUBLICA", "http://localhost:8000").rstrip("/")
    try:
        requests.get(f"{base}/saude", timeout=10)
    except requests.RequestException:
        pass


async def laco_de_keep_alive() -> None:
    while True:
        await asyncio.sleep(KEEP_ALIVE_INTERVALO_S)
        await asyncio.to_thread(bater_no_keep_alive)


# --- loop principal ----------------------------------------------------------


async def servir(calibracao: dict) -> None:
    url = url_do_websocket()
    tentativa = 0
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("Ponte conectada. Esperando ordem de medir.")
                tentativa = 0
                async for bruto in ws:
                    # `to_thread` porque o pipeline é síncrono e leva ~3s: no
                    # event loop ele travaria os pings do WebSocket e a conexão
                    # cairia sozinha.
                    resposta = await asyncio.to_thread(processar, bruto, calibracao)
                    if resposta is not None:
                        await ws.send(json.dumps(resposta))
        except Exception as e:
            espera = espera_do_backoff(tentativa)
            print(f"Ponte caiu ({e}). Reconectando em {espera}s.", file=sys.stderr)
            await asyncio.sleep(espera)
            tentativa += 1


async def principal() -> None:
    calibracao = carregar_calibracao_ou_sair()
    print(f"Calibração: px_por_cm={calibracao['px_por_cm']:.2f} "
          f"y_chao={calibracao['y_chao']} regiao={calibracao.get('regiao')!r}")
    await asyncio.gather(servir(calibracao), laco_de_keep_alive())


if __name__ == "__main__":
    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        print("Ponte encerrada.")
```

- [ ] **Step 5: Rodar os testes**

Run: `python -m pytest tests/test_jogo_ponte.py -v`
Expected: PASS nos 12 testes (ou `skipped` na máquina sem `cv2`).

- [ ] **Step 6: Verificar com a câmera de verdade**

Em dois terminais:

```powershell
# terminal 1 — o jogo
$env:HOST_TOKEN="abc"; $env:PONTE_TOKEN="def"; python -m uvicorn jogo.main:app

# terminal 2 — a ponte
$env:PONTE_TOKEN="def"; $env:JOGO_URL_PUBLICA="http://localhost:8000"; python -m jogo.ponte
```

Confirme:

1. A ponte imprime a calibração carregada e "Ponte conectada".
2. O palco mostra "● câmera conectada".
3. Entrar por um celular ou aba, chutar, clicar MEDIR → a webcam acende, a medição leva ~3s, o contador sobe até um valor plausível.
4. O pódio mostra a **imagem anotada** com as colunas, a linha do chão e a régua em cm.
5. Matar a ponte (Ctrl+C) → o semáforo apaga e MEDIR desabilita.
6. Subir a ponte de novo → ela reconecta e o semáforo acende, sem mexer no palco.
7. Renomear `calibration.json` e tentar subir a ponte → ela se recusa, pedindo `calibrar.py`. Renomeie de volta.

- [ ] **Step 7: Commit**

```bash
git add jogo/ponte.py requirements-ponte.txt tests/test_jogo_ponte.py
git commit -m "feat(jogo): ponte da camera com reconexao e keep-alive"
```

---

## Task 13: Deploy e documentação

**Files:**
- Modify: `render.yaml`
- Modify: `.env.example`
- Create: `jogo/README.md`
- Modify: `README.md`

- [ ] **Step 1: Acrescentar o segundo serviço no `render.yaml`**

Acrescente ao fim de `render.yaml`, **dentro** da lista `services`, sem tocar no
serviço que já existe:

```yaml
  # Jogo da feira de ciências. Serviço separado de propósito: o jogo importa
  # código que a API não tem, e um deploy dele não pode derrubar a produção.
  # NÃO instala requirements-station.txt: quem fala com a câmera é a ponte, que
  # roda no notebook da feira.
  - type: web
    name: jogo-grama-webcam
    runtime: python
    region: oregon
    plan: free
    buildCommand: pip install -r requirements-jogo.txt
    startCommand: uvicorn jogo.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /saude
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.9"
      - key: HOST_TOKEN
        sync: false
      - key: PONTE_TOKEN
        sync: false
      # URL pública do próprio serviço, usada no QR code.
      - key: JOGO_URL_PUBLICA
        sync: false
      # A medição da feira é postada na API de produção como
      # regiao="Feira de Ciências".
      - key: API_URL
        sync: false
      - key: API_KEY_WRITE
        sync: false
```

- [ ] **Step 2: Documentar as variáveis novas no `.env.example`**

Acrescente ao fim de `.env.example`:

```bash
# --- Jogo da feira (jogo/) ---------------------------------------------------
# Gere cada token com:
#   python -c "import secrets; print(secrets.token_urlsafe(24))"
#
# HOST_TOKEN vai na URL que o apresentador abre: /host?token=...
# PONTE_TOKEN fica nesta máquina, lido por `python -m jogo.ponte`.
# São separados de propósito: ao mostrar a tela para alguém, o token do host
# aparece na barra de endereço, e esse segredo não deve dar controle da câmera.
HOST_TOKEN="troque-me-token-do-host"
PONTE_TOKEN="troque-me-token-da-ponte"

# URL pública do jogo. Entra no QR code e é o destino da ponte.
JOGO_URL_PUBLICA="https://jogo-grama-webcam.onrender.com"
```

- [ ] **Step 3: Escrever o README do jogo**

Crie `jogo/README.md`:

````markdown
# Jogo da feira de ciências

Jogo no formato Kahoot para apresentar o Grama Webcam. Até cinco visitantes
chutam pelo celular quanto mede a grama; o apresentador manda medir pela webcam
real; o valor sobe numa animação e quem chegou mais perto ganha.

## Como as peças se encaixam

```
VISITANTES (cada um no seu 5G)          ESTE SERVIÇO (Render)
  📱 📱 📱  ──── escaneiam o QR ────▶   sala, chutes, ranking
                                               ▲
                                               │ WebSocket de SAÍDA
                                     NOTEBOOK DA FEIRA
                                     python -m jogo.ponte
                                     (a webcam está aqui)
```

Quem abre a conexão é o notebook. Por isso não é preciso IP público, porta
liberada nem que os celulares estejam na mesma rede.

## Rodar local

```bash
pip install -r requirements-jogo.txt -r requirements-ponte.txt

# terminal 1 — o jogo
python -m uvicorn jogo.main:app --reload

# terminal 2 — a ponte (precisa de calibration.json nesta máquina)
python -m jogo.ponte
```

Palco: `http://localhost:8000/host?token=$HOST_TOKEN`
Controle: `http://localhost:8000`

## Roteiro de montagem na feira

1. Copiar o repositório para o notebook da feira.
2. `pip install -r requirements-ponte.txt`
3. Posicionar e **fixar** a câmera. Se ela encostar depois, recalibre.
4. `python calibrar.py` — nesta máquina, com a câmera no lugar final.
5. Conferir `PONTE_TOKEN` e `JOGO_URL_PUBLICA` no `.env`.
6. `python -m jogo.ponte` — deixar rodando o dia todo.
7. Abrir `/host?token=...` no notebook e apertar F11.
8. Confirmar o semáforo "● câmera conectada" no palco.
9. Testar uma rodada com o próprio celular **antes** do primeiro grupo.
10. Imprimir o QR do jogo. O palco também mostra o dele, gerado na hora.

O passo 4 não é opcional: `px_por_cm` e `y_chao` são da câmera **e** da posição
dela. Sem recalibrar nesta máquina, a altura sai torta.

## Operação durante a feira

| Situação | O que fazer |
|---|---|
| grupo novo chegando | "Nova rodada" — limpa jogadores e reabre a sala |
| os cinco já entraram | "Travar sala" — ninguém mais ocupa cadeira |
| semáforo apagado | a ponte caiu; ela reconecta sozinha, veja o terminal dela |
| medição falhou | clique MEDIR de novo; os chutes foram preservados |
| alguém travou no meio | "Nova rodada" funciona de qualquer estado |

## Testes

```bash
python -m pytest tests/test_jogo_sala.py tests/test_jogo_medicao.py \
                 tests/test_jogo_envio.py tests/test_jogo_api.py -v
python -m pytest tests/test_jogo_ponte.py -v   # pula sem cv2 instalado
```

A suíte roda sem webcam: `jogo/sala.py` não tem I/O e a medição é falsificada.
Só `tests/test_jogo_ponte.py` precisa de `cv2`, e ele é pulado onde não houver.
````

- [ ] **Step 4: Apontar o README principal para o jogo**

Em `README.md`, na seção `## 📁 Estrutura do repositório`, acrescente dentro do
bloco de código, logo depois do bloco de `api/`:

```
├── jogo/                      # jogo da feira de ciências (serviço separado)
│   ├── sala.py               # máquina de estado, zero I/O
│   ├── main.py               # rotas, WebSockets, tokens, QR
│   ├── ponte.py              # roda no notebook da feira, opera a câmera
│   └── README.md             # montagem e operação na feira
```

E na seção `### Curto prazo` do roadmap, troque a linha do keep-alive por:

```markdown
- [x] **Keep-alive do Render free** — a ponte do jogo da feira bate em `/saude` a cada 10min
```

- [ ] **Step 5: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: PASS em tudo — os ~190 testes que já existiam mais os ~62 novos.
Nenhum teste antigo deve mudar de resultado: este plano não toca em `api/`,
`medir_grama.py` nem `camera.py`.

- [ ] **Step 6: Commit**

```bash
git add render.yaml .env.example jogo/README.md README.md
git commit -m "docs(jogo): deploy na Render, variaveis e roteiro da feira"
```

- [ ] **Step 7: Deploy**

```bash
git push origin main
```

No dashboard da Render: criar o serviço `jogo-grama-webcam` a partir do
`render.yaml` e preencher os cinco segredos (`HOST_TOKEN`, `PONTE_TOKEN`,
`JOGO_URL_PUBLICA`, `API_URL`, `API_KEY_WRITE`).

Com o serviço no ar, confirme:

1. `GET https://jogo-grama-webcam.onrender.com/saude` → `{"status":"ok"}`
2. `GET /host` sem token → 403
3. A ponte local, com `JOGO_URL_PUBLICA` apontando para a Render, conecta e acende o semáforo.
4. Uma rodada completa pelo celular, no 4G, com a ponte rodando em casa.
5. `GET /leituras?regiao=Feira%20de%20Ci%C3%AAncias` na API de produção devolve a medição que acabou de acontecer.

---

## Auto-revisão do plano

**Cobertura do spec.** Percorri cada seção do spec contra as tasks:

| Requisito do spec | Task |
|---|---|
| app separada, não em `api/` | 6, 13 |
| Render e não Vercel | 13 |
| câmera no notebook, conexão de saída | 12 |
| `cv2` fora da nuvem | 6, 13 |
| costura fina da medição | 5 |
| ponte reconecta sozinha | 12 |
| keep-alive por HTTP | 12 |
| máquina de quatro estados | 1-4 |
| chutes escondidos até a revelação | 7 (`test_chute_nao_vaza_o_valor_no_estado`) |
| chute 0-200, uma decimal | 2 |
| nome vazio ou repetido recusado | 1 |
| ranking e empate por ordem | 3 |
| pódio com menos de 3 jogadores | 3 |
| servidor como fonte única | 7 |
| reconexão por `localStorage` | 7, 10 |
| host recarrega e a sala sobrevive | 7, 11 (verificação 12) |
| dois tokens separados | 6, 8 |
| host trava a sala | 4, 8, 11 |
| nova rodada de qualquer estado | 4 |
| POST com `regiao="Feira de Ciências"` | 9 |
| sem CDN, sem Google Fonts, QR no servidor | 6, 10 |
| grama ausente é falha, não resultado | 12 |
| palco: QR, cadeiras, semáforo, animações, imagem anotada | 11 |
| controle: três telas, "olha pra tela grande" | 10 |
| segunda ponte recusada | 5, 8 |
| timeout de 30s da ponte | 5 |
| chutes preservados em toda falha | 3, 8 (verificação 11.11) |
| roteiro de montagem | 13 |

Nenhuma lacuna. Dois acréscimos ao spec, ambos registrados no texto:
`jogo/envio.py` como módulo próprio, e a rota `/saude` — o spec não previa health
check, mas a Render exige um `healthCheckPath` e o keep-alive precisa de um
destino barato.

**Consistência de nomes.** `chutar_por_id`, `jogador`, `quantos_chutaram`,
`iniciar_medicao`, `concluir_medicao`, `revelacao_terminou`, `falhar_medicao`,
`nova_rodada`, `definir_trava`, `ranking` — cada um definido nas Tasks 1-4 e usado
com a mesma assinatura nas Tasks 7, 8 e nos testes. `Medidor.conectar`,
`desconectar`, `medir`, `entregar_resultado`, `entregar_erro`, `conectado`,
`canal` — definidos na Task 5, usados na 8. `enviar_em_background` definido na
Task 9 e importado na 8, que é por isso que a Task 8 fecha vermelha e a 9
resolve. O payload de estado tem as mesmas treze chaves na Task 7, nos testes da
Task 8 e nos dois JS das Tasks 10 e 11. Na ponte, `CALIBRATION_PATH`,
`DEBUG_PATH`, `ler_imagem_b64`, `medir`, `processar`, `espera_do_backoff`,
`url_do_websocket`, `bater_no_keep_alive` e `BACKOFF_MAX_S` são os mesmos nomes
nos testes e na implementação.

**Sequência.** A Task 8 termina com a suíte vermelha de propósito, por depender de
`jogo/envio.py`; está dito no Step 4 dela e resolvido na Task 9. A Task 1 termina
com um teste vermelho que a Task 2 resolve, e a Task 2 com dois que a Task 3
resolve — ambos sinalizados. Fora desses, cada task fecha verde.
