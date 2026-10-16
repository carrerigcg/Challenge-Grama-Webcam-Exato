"""Costura entre o jogo e a ponte que opera a câmera.

A ordem de medir sai por um canal (o WebSocket da ponte) e a resposta volta
por uma task diferente, que está lendo esse mesmo socket. Por isso `medir()`
cria um `Future` e aguarda, e `entregar_resultado()` o completa.

Cada ordem leva um `id`, e a ponte devolve o mesmo `id`. Sem isso, a resposta
atrasada de uma ordem que já estourou o timeout é entregue como resposta da
medição em curso, e o palco revela a altura de uma rodada que acabou — sem
erro nenhum, o que é pior que uma falha visível.

Uma implementação só, de propósito. A costura existe para que os testes
possam falsificar a medição e rodar sem webcam — não para abrir espaço a uma
segunda fonte hipotética.
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

# 15s dá cinco vezes a folga do pipeline (~3s) mais a ida e volta pela
# internet. Era 30s, e 30s de palco congelado é tempo demais na frente do
# grupo. Encurtar só é seguro porque o `id` faz a resposta atrasada ser
# descartada em vez de confundida com a medição seguinte.
TIMEOUT_PADRAO_S = 15.0


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
        self._ordem = 0
        self._ordem_esperada: int | None = None

    @property
    def conectado(self) -> bool:
        return self.canal is not None

    # --- ciclo de vida da ponte ---------------------------------------------

    def conectar(self, canal: Canal) -> Canal | None:
        """Registra a ponte e devolve a anterior, que o chamador deve fechar.

        Ponte nova assume o lugar da antiga em vez de ser recusada: na feira, a
        segunda conexão é quase sempre o mesmo notebook reconectando depois de
        o Wi-Fi piscar, e recusá-la travava a retomada até o servidor detectar
        o socket morto — dezenas de segundos com o palco mostrando "câmera
        offline".

        A medição em voo falha junto: o notebook que reconectou não vai
        responder a uma ordem que foi para o socket velho. É seguro porque
        `desconectar` ignora canal que não é o atual, então o handler da ponte
        velha, ao notar a queda, não derruba esta.
        """
        anterior = self.canal
        self.canal = canal
        if anterior is not None:
            self._falhar_espera("A ponte da câmera reconectou no meio da medição.")
        return anterior

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
            # fica órfã esperando até estourar o timeout. A ponte também
            # processa uma ordem por vez, então a segunda só atrapalharia.
            raise ErroDeMedicao("Já existe uma medição em andamento.")
        laco = asyncio.get_running_loop()
        self._ordem += 1
        ordem = self._ordem
        # O future vai numa variável LOCAL e é ela que o `wait_for` recebe.
        # Reler `self._esperando` depois de um await deixa outra medição apagar
        # este future: uma chamada que acorda tarde zera o atributo, e aí ou o
        # `wait_for` recebe None (TypeError cru) ou o resultado da medição nova
        # é descartado.
        futuro = self._esperando = laco.create_future()
        self._ordem_esperada = ordem
        try:
            try:
                await self.canal.send_json({"cmd": "medir", "id": ordem})
            except Exception as e:
                # Só o envio é embrulhado. Um `except` largo em volta do
                # `wait_for` também capturaria o ErroDeMedicao que a ponte
                # entrega pelo future, e re-embrulharia a mensagem do palco.
                raise ErroDeMedicao(f"Não deu para falar com a ponte: {e}") from None
            return await asyncio.wait_for(futuro, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            raise ErroDeMedicao("A câmera demorou demais para responder.") from None
        finally:
            # Só limpa se ainda for o nosso: outra medição pode já ter começado.
            if self._esperando is futuro:
                self._esperando = None
                self._ordem_esperada = None
            # Consome exceção que ninguém mais vai ler, senão o asyncio imprime
            # "Future exception was never retrieved" no log de produção.
            if futuro.done() and not futuro.cancelled():
                futuro.exception()

    def entregar_resultado(self, resultado: dict) -> None:
        """Completa a medição em curso, se a resposta for dela.

        Resposta sem o `id` esperado é descartada em silêncio: ou é de uma
        ordem que já estourou o timeout, ou é de uma ponte que não fala o
        protocolo. Nos dois casos, aceitá-la revelaria a altura errada.
        """
        if self._esperando is None or self._esperando.done():
            return
        if resultado.get("id") != self._ordem_esperada:
            return
        self._esperando.set_result(resultado)

    def entregar_erro(self, motivo: str, ordem: int | None = None) -> None:
        """Falha a medição em curso.

        `ordem` vem da ponte e é conferida. `None` significa falha local (a
        desconexão do socket, por exemplo), que sempre vale para o future atual.
        """
        if ordem is not None and ordem != self._ordem_esperada:
            return
        self._falhar_espera(motivo)

    def _falhar_espera(self, motivo: str) -> None:
        if self._esperando is not None and not self._esperando.done():
            self._esperando.set_exception(ErroDeMedicao(motivo))
