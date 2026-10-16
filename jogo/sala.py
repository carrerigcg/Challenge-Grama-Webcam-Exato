"""Máquina de estado da sala do jogo da feira. Zero I/O.

Este módulo não importa FastAPI, WebSocket, OpenCV nem `requests` — e não
deve passar a importar. É o que permite testar ranking, empates e sala cheia
sem webcam, sem rede e sem navegador.

Quem chama a medição é `jogo/main.py`; a sala só recebe o resultado pronto.
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
