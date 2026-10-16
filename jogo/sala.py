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
    _proxima_ordem: int = 0

    # --- entrada -------------------------------------------------------------

    def entrar(self, nome: str) -> Jogador:
        if self.estado is not Estado.AGUARDANDO:
            raise ErroDeJogo("Rodada em andamento. Espere a próxima.")
        if not self.aberta:
            raise ErroDeJogo("A sala está travada. Fale com o apresentador.")
        nome_limpo = nome.strip()
        if not nome_limpo:
            raise ErroDeJogo("Digite um nome.")
        if len(self.jogadores) >= MAX_JOGADORES:
            raise ErroDeJogo("Sala cheia. Espere a próxima rodada.")
        if any(j.nome.casefold() == nome_limpo.casefold() for j in self.jogadores):
            raise ErroDeJogo("Esse nome já está em uso. Escolha outro.")
        jogador = Jogador(id=secrets.token_urlsafe(8), nome=nome_limpo)
        self.jogadores.append(jogador)
        return jogador

    def definir_trava(self, travada: bool) -> None:
        self.aberta = not travada
