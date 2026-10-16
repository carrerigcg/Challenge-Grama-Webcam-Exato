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
