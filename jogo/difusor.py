"""Quem está conectado e o que eles recebem.

Separado do `main.py` porque a concorrência do broadcast mora aqui — um lock,
um timeout por cliente, uma serialização só — e isso precisa de teste com
socket falso e instância limpa por caso. A Task 8 multiplica os chamadores de
`transmitir`, e concorrência espalhada por handlers é o que não se testa
depois.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Protocol

# 2s por cliente. Celular com buffer TCP cheio no 4G da feira não pode travar
# o broadcast dos outros; quem estoura sai do set e volta na reconexão.
TIMEOUT_ENVIO_S = 2.0

_log = logging.getLogger(__name__)


class Cliente(Protocol):
    async def send_text(self, texto: str) -> None: ...


class Difusor:
    """Mantém o set de clientes e entrega o mesmo texto para todos."""

    def __init__(
        self, montar: Callable[[], dict], timeout_s: float = TIMEOUT_ENVIO_S
    ):
        self._montar = montar
        self._timeout_s = timeout_s
        self._clientes: set[Cliente] = set()
        # Serializa montagem e envio. Sem o lock, duas transmissões
        # concorrentes podem entregar o payload velho DEPOIS do novo, e um
        # celular fica com a tela de uma rodada que já passou.
        self._porta = asyncio.Lock()

    def adicionar(self, cliente: Cliente) -> None:
        self._clientes.add(cliente)

    def remover(self, cliente: Cliente) -> None:
        self._clientes.discard(cliente)

    @property
    def quantos(self) -> int:
        return len(self._clientes)

    async def transmitir(self) -> None:
        async with self._porta:
            try:
                # Uma serialização só. `allow_nan=False` faz NaN falhar aqui,
                # em vez de virar o token `NaN` que o JSON.parse de TODOS os
                # navegadores rejeita de uma vez.
                texto = json.dumps(self._montar(), allow_nan=False)
            except (TypeError, ValueError):
                # Payload inválido é bug nosso, não socket morto: loga e não
                # descarta ninguém. Descartar deixaria os cinco celulares
                # conectados e mudos, sem rastro nenhum.
                _log.exception("payload inválido; nada foi transmitido")
                return
            for cliente in list(self._clientes):
                try:
                    await asyncio.wait_for(
                        cliente.send_text(texto), timeout=self._timeout_s
                    )
                except Exception:
                    # Socket morto, ou lento demais para o grupo esperar. Sai
                    # do set; o `finally` do handler também remove, e descartar
                    # duas vezes de um set não custa nada.
                    self._clientes.discard(cliente)
