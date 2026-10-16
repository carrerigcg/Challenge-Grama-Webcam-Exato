"""Máquina de estado da sala do jogo da feira. Zero I/O.

Este módulo não importa FastAPI, WebSocket, OpenCV nem `requests` — e não
deve passar a importar. É o que permite testar ranking, empates e sala cheia
sem webcam, sem rede e sem navegador.

Quem chama a medição é `jogo/main.py`; a sala só recebe o resultado pronto.

Contrato para quem consome esta classe:

- **Uma instância só, pela vida do processo.** Nunca reatribua `Sala()`: o
  ticket de medição recomeça em 0 e volta a colidir com o de uma task que
  ainda esteja em voo. Para zerar a sala, use `nova_rodada()`.
- **Converta o JSON na borda.** `entrar` espera `str` e `chutar_por_id` espera
  número; é o handler que faz `str(...)`, `float(...)` e captura
  `TypeError`/`ValueError`. A sala valida regra de jogo, não tipo de payload.
- **Capture `ValueError` de `concluir_medicao`.** Altura NaN, infinita ou
  negativa é recusada como invariante, e a sala fica em MEDINDO. Sem o
  `except` virando `falhar_medicao`, a rodada trava até o host resetar.
- **Passe o ticket adiante.** `iniciar_medicao` devolve o ticket que
  `concluir_medicao`, `revelacao_terminou` e `falhar_medicao` exigem. Elas
  devolvem `False` para chamada obsoleta, e isso é esperado, não erro.
"""
from __future__ import annotations

import math
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
    altura_cm: float | None = None
    margem_cm: float | None = None
    categoria: str | None = None
    imagem_b64: str | None = None
    erro: str | None = None
    # Identifica a medição em curso. Serve para descartar resposta atrasada de
    # uma rodada que já acabou. A `nova_rodada` da Task 4 também o incrementa,
    # invalidando tudo que estiver em voo.
    _medicao: int = field(default=0, init=False, repr=False, compare=False)
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
                "nome": j.nome,
                "chute_cm": j.chute_cm,
                "erro_cm": self._erro_arredondado(j),
            }
            for i, j in enumerate(ordenados)
        ]

    def _erro_arredondado(self, jogador: Jogador) -> float:
        """Distância entre chute e medida, já arredondada. Veja `ranking`."""
        return round(abs(jogador.chute_cm - self.altura_cm), 1)
