"""O difusor: lock, timeout por cliente e serialização única.

Com sockets falsos e instância limpa por caso — é o motivo de o difusor ser
uma classe e não um set de módulo.
"""
import asyncio

import pytest

from jogo.difusor import Difusor

pytestmark = pytest.mark.asyncio


class ClienteFalso:
    def __init__(self):
        self.recebidos = []

    async def send_text(self, texto):
        self.recebidos.append(texto)


class ClienteMorto:
    async def send_text(self, texto):
        raise RuntimeError("socket fechado")


class ClienteLento:
    def __init__(self, demora):
        self.demora = demora
        self.recebidos = []

    async def send_text(self, texto):
        await asyncio.sleep(self.demora)
        self.recebidos.append(texto)


async def test_todos_recebem_o_mesmo_texto():
    difusor = Difusor(lambda: {"estado": "AGUARDANDO"})
    a, b = ClienteFalso(), ClienteFalso()
    difusor.adicionar(a)
    difusor.adicionar(b)
    await difusor.transmitir()
    assert a.recebidos == b.recebidos
    assert '"AGUARDANDO"' in a.recebidos[0]


async def test_socket_morto_sai_do_set_e_os_outros_recebem():
    difusor = Difusor(lambda: {"estado": "AGUARDANDO"})
    vivo, morto = ClienteFalso(), ClienteMorto()
    difusor.adicionar(vivo)
    difusor.adicionar(morto)
    await difusor.transmitir()
    assert len(vivo.recebidos) == 1
    assert difusor.quantos == 1


async def test_cliente_lento_nao_trava_o_grupo():
    """Celular com buffer cheio no 4G da feira não pode parar o broadcast."""
    difusor = Difusor(lambda: {"estado": "AGUARDANDO"}, timeout_s=0.02)
    rapido, lento = ClienteFalso(), ClienteLento(0.5)
    difusor.adicionar(rapido)
    difusor.adicionar(lento)
    await difusor.transmitir()
    assert len(rapido.recebidos) == 1
    assert lento.recebidos == []
    assert difusor.quantos == 1


async def test_payload_invalido_loga_e_nao_descarta_ninguem():
    """Payload inválido é bug nosso: descartar deixaria todos mudos sem rastro."""
    difusor = Difusor(lambda: {"altura_cm": float("nan")})
    a = ClienteFalso()
    difusor.adicionar(a)
    await difusor.transmitir()
    assert a.recebidos == []
    # O cliente continua no set: na próxima transmissão válida ele recebe.
    assert difusor.quantos == 1


class ClienteDecrescente:
    """Primeiro envio lento, segundo instantâneo.

    É o que discrimina o lock: sem ele, a segunda transmissão passa na frente
    da primeira e o cliente recebe o payload velho DEPOIS do novo. Com os dois
    envios na mesma demora, a ordem sai certa por acidente e o teste não prova
    nada — foi o defeito da primeira versão deste teste.
    """

    def __init__(self):
        self.demoras = [0.05, 0.0]
        self.recebidos = []

    async def send_text(self, texto):
        await asyncio.sleep(self.demoras.pop(0))
        self.recebidos.append(texto)


async def test_transmissoes_concorrentes_chegam_em_ordem():
    """Sem o lock, o payload velho chega DEPOIS do novo, e o celular fica com
    a tela de uma rodada que já passou."""
    estado = {"n": 0}
    difusor = Difusor(lambda: dict(estado))
    cliente = ClienteDecrescente()
    difusor.adicionar(cliente)

    estado["n"] = 1
    primeira = asyncio.create_task(difusor.transmitir())
    await asyncio.sleep(0)  # deixa a primeira montar e entrar no envio
    estado["n"] = 2
    segunda = asyncio.create_task(difusor.transmitir())
    await asyncio.gather(primeira, segunda)

    assert cliente.recebidos == ['{"n": 1}', '{"n": 2}']
