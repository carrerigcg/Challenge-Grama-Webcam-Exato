"""A costura entre o jogo e a ponte da câmera.

Sem webcam e sem WebSocket real: o canal da ponte é falsificado por uma classe
que só guarda o que foi enviado.
"""
import asyncio

import pytest

from jogo.medicao import ErroDeMedicao, Medidor

# Modo estrito do pytest-asyncio, marcado no módulo. A alternativa seria um
# `pytest.ini` com `asyncio_mode = auto`, mas ele valeria para o repositório
# inteiro (os ~190 testes síncronos da API inclusive) e teria precedência sobre
# um `pyproject.toml` futuro, silenciando config nova sem avisar.
pytestmark = pytest.mark.asyncio


class CanalFalso:
    """Faz o papel do WebSocket da ponte: guarda as ordens enviadas."""

    def __init__(self):
        self.ordens = []

    async def send_json(self, dados):
        self.ordens.append(dados)


async def esperar_ordem(canal: CanalFalso, giros: int = 10_000) -> dict:
    """Espera a ordem de medir aparecer no canal, com teto. Devolve a ordem.

    O teto existe porque `while not canal.ordens: await asyncio.sleep(0)` sem
    limite pendura a suíte para sempre se um bug impedir o envio — e suíte
    pendurada é pior que teste que falha, porque trava o CI sem dizer por quê.
    """
    for _ in range(giros):
        if canal.ordens:
            return canal.ordens[-1]
        await asyncio.sleep(0)
    raise AssertionError("a ordem de medir nunca saiu no canal")


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
        ordem = await esperar_ordem(canal)
        medidor.entregar_resultado(
            {"altura_cm": 17.5, "margem_cm": 0.4, "categoria": "ALTA",
             "imagem_b64": "iVBOR", "id": ordem["id"]}
        )

    asyncio.create_task(responder())
    resultado = await medidor.medir()

    assert canal.ordens == [{"cmd": "medir", "id": 1}]
    assert resultado["altura_cm"] == 17.5
    assert resultado["categoria"] == "ALTA"


async def test_medir_propaga_erro_reportado_pela_ponte():
    medidor = Medidor()
    canal = CanalFalso()
    medidor.conectar(canal)

    async def responder():
        await esperar_ordem(canal)
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
        await esperar_ordem(canal)
        medidor.desconectar(canal)

    asyncio.create_task(derrubar())
    with pytest.raises(ErroDeMedicao, match="ponte"):
        await medidor.medir()


async def test_ponte_nova_assume_o_lugar_da_antiga():
    """Reconexão depois de o Wi-Fi piscar não pode ficar travada esperando o
    servidor notar que o socket velho morreu."""
    medidor = Medidor()
    antiga = CanalFalso()
    assert medidor.conectar(antiga) is None

    nova = CanalFalso()
    # Devolve a antiga para o chamador fechar o socket.
    assert medidor.conectar(nova) is antiga
    assert medidor.canal is nova

    # O handler da ponte velha acorda depois e não pode derrubar a nova.
    medidor.desconectar(antiga)
    assert medidor.canal is nova

    async def responder():
        ordem = await esperar_ordem(nova)
        medidor.entregar_resultado({"altura_cm": 9.0, "id": ordem["id"]})

    asyncio.create_task(responder())
    assert (await medidor.medir())["altura_cm"] == 9.0


async def test_troca_de_ponte_falha_a_medicao_em_voo():
    medidor = Medidor()
    antiga = CanalFalso()
    medidor.conectar(antiga)

    async def trocar():
        await esperar_ordem(antiga)
        medidor.conectar(CanalFalso())

    asyncio.create_task(trocar())
    # A ordem foi para o socket velho; o notebook que reconectou não vai
    # responder a ela, então esta medição tem de falhar em vez de pendurar.
    with pytest.raises(ErroDeMedicao, match="reconectou"):
        await medidor.medir()


async def test_medir_recusa_medicao_concorrente():
    medidor = Medidor()
    canal = CanalFalso()
    medidor.conectar(canal)
    erro_da_segunda = []

    async def segunda_chamada():
        await esperar_ordem(canal)  # espera a primeira ordem sair
        try:
            await medidor.medir()
        except ErroDeMedicao as e:
            erro_da_segunda.append(str(e))
        # Completa a primeira medição em qualquer caso: se a asserção morasse
        # aqui dentro e falhasse, a exceção ficaria engolida na task, o
        # `entregar_resultado` não rodaria, e o teste só falharia 15s depois
        # com a mensagem errada ("demorou"). Asserção fica no corpo principal.
        ordem = canal.ordens[0]
        medidor.entregar_resultado({"altura_cm": 17.5, "id": ordem["id"]})

    asyncio.create_task(segunda_chamada())
    resultado = await medidor.medir()

    assert resultado["altura_cm"] == 17.5
    # Uma ordem só saiu: a segunda nem chegou ao canal.
    assert canal.ordens == [{"cmd": "medir", "id": 1}]
    assert erro_da_segunda and "em andamento" in erro_da_segunda[0]


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


async def test_canal_que_quebra_no_envio_nao_trava_o_medidor():
    """Socket que morre entre o `conectado` e o envio.

    Caso real de feira: o Wi-Fi pisca, o apresentador clica MEDIR, e o socket
    da ponte já está morto sem o servidor ter processado a desconexão.
    """
    class CanalQuebrado:
        async def send_json(self, dados):
            raise RuntimeError("socket já fechado")

    medidor = Medidor()
    quebrado = CanalQuebrado()
    medidor.conectar(quebrado)

    # A falha sai embrulhada, não como RuntimeError cru: quem chama precisa de
    # ErroDeMedicao para virar mensagem no palco.
    with pytest.raises(ErroDeMedicao, match="falar com a ponte"):
        await medidor.medir()

    # E o medidor aceita a medição seguinte. Sem limpar o `_esperando`, toda
    # chamada depois desta cairia na guarda de "medição em andamento".
    medidor.desconectar(quebrado)
    canal = CanalFalso()
    medidor.conectar(canal)

    async def responder():
        ordem = await esperar_ordem(canal)
        medidor.entregar_resultado({"altura_cm": 9.0, "id": ordem["id"]})

    asyncio.create_task(responder())
    resultado = await medidor.medir()
    assert resultado["altura_cm"] == 9.0


async def test_resposta_de_ordem_antiga_e_descartada():
    """O bug grave: a altura de uma rodada que já acabou revelada como se fosse
    da atual, sem erro nenhum."""
    medidor = Medidor(timeout_s=0.05)
    canal = CanalFalso()
    medidor.conectar(canal)

    # Medição 1 estoura o timeout sem resposta.
    with pytest.raises(ErroDeMedicao, match="demorou"):
        await medidor.medir()
    id_antigo = canal.ordens[0]["id"]

    # Medição 2 começa. A resposta atrasada da ordem 1 chega agora.
    async def responder():
        ordem = await esperar_ordem(canal)
        medidor.entregar_resultado({"altura_cm": 99.0, "id": id_antigo})
        medidor.entregar_resultado({"altura_cm": 9.0, "id": ordem["id"]})

    asyncio.create_task(responder())
    resultado = await medidor.medir()
    # A altura da ordem velha não pode vazar para esta medição.
    assert resultado["altura_cm"] == 9.0


async def test_erro_de_ordem_antiga_nao_derruba_a_medicao_atual():
    medidor = Medidor(timeout_s=0.05)
    canal = CanalFalso()
    medidor.conectar(canal)
    with pytest.raises(ErroDeMedicao, match="demorou"):
        await medidor.medir()
    id_antigo = canal.ordens[0]["id"]

    async def responder():
        ordem = await esperar_ordem(canal)
        medidor.entregar_erro("falha da ordem velha", id_antigo)
        medidor.entregar_resultado({"altura_cm": 9.0, "id": ordem["id"]})

    asyncio.create_task(responder())
    resultado = await medidor.medir()
    assert resultado["altura_cm"] == 9.0


async def test_entregar_sem_medicao_em_andamento_nao_faz_nada():
    medidor = Medidor()
    medidor.conectar(CanalFalso())
    # Não deve levantar nem deixar estado pendurado.
    medidor.entregar_resultado({"altura_cm": 17.5, "id": 1})
    medidor.entregar_erro("ninguém pediu nada")
    assert medidor._esperando is None
