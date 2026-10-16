"""Máquina de estado da sala do jogo da feira.

Sem fixtures de banco de propósito: o jogo não tem persistência. A sala é um
dataclass em memória e estes testes são aritmética de estado, não integração.
"""
import pytest

from jogo.sala import MAX_JOGADORES, ErroDeJogo, Estado, Sala


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
        with pytest.raises(ErroDeJogo, match="nome"):
            sala.entrar(nome)


def test_entrar_corta_espacos_em_volta_do_nome():
    sala = Sala()
    assert sala.entrar("  Ana  ").nome == "Ana"


def test_entrar_recusa_nome_repetido_ignorando_caixa():
    sala = Sala()
    sala.entrar("Ana")
    with pytest.raises(ErroDeJogo, match="nome"):
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
    sala.chutar_por_id(sala.jogadores[0].id, 10.0)
    sala.iniciar_medicao()
    with pytest.raises(ErroDeJogo, match="andamento"):
        sala.entrar("Bruno")
