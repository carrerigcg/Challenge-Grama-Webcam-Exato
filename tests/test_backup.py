"""Testes de scripts/backup.py — a exportação de .xlsx de `previsoes`.

Roda contra DATABASE_URL_TEST, igual tests/test_db.py: nunca contra produção.
"""
import os

import pytest
from dotenv import load_dotenv

from api import db
from scripts.backup import _nome_seguro, _tabela_leituras, exportar_previsoes

load_dotenv()


@pytest.fixture
def pool():
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não configurada — veja .env.example")
    p = db.criar_pool(url)
    p.open()
    db.criar_schema(p)
    # TRUNCATE por teste, igual ao fixture `client` do conftest.py: estes
    # testes contam arquivos exportados, então presumem a tabela vazia. Sem
    # isto eles passam sozinhos e falham na suíte inteira — `test_api.py` roda
    # antes (ordem alfabética) e a última leitura dele sobrevive, virando um
    # `assert 2 == 1` que parece bug do backup e é sujeira de outro arquivo.
    with p.connection() as conn:
        conn.execute("TRUNCATE previsoes RESTART IDENTITY")
    yield p
    p.close()


def _url():
    return os.environ["DATABASE_URL_TEST"]


def _inserir(pool, nome, conteudo):
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO previsoes (nome_arquivo, conteudo) VALUES (%s, %s) "
            "RETURNING id",
            (nome, conteudo),
        ).fetchone()
    return row["id"]


def _remover(pool, *ids):
    with pool.connection() as conn:
        conn.execute("DELETE FROM previsoes WHERE id = ANY(%s)", (list(ids),))


def test_exportar_previsoes_grava_bytes_identicos_ao_banco(pool, tmp_path):
    """O ponto do .xlsx em disco em vez de bytea num INSERT: tem que abrir
    exatamente igual ao que foi salvo, byte a byte."""
    conteudo = b"PK\x03\x04\x00\xff\xfe conteudo binario de verdade \x00\x01"
    id_ = _inserir(pool, "relatorio.xlsx", conteudo)
    try:
        n = exportar_previsoes(_url(), tmp_path)
        assert n == 1
        arquivos = list(tmp_path.iterdir())
        assert len(arquivos) == 1
        assert arquivos[0].name == f"{id_:04d}-relatorio.xlsx"
        assert arquivos[0].read_bytes() == conteudo
    finally:
        _remover(pool, id_)


def test_exportar_previsoes_sanitiza_nome_invalido_no_windows(pool, tmp_path):
    """`:` passa a validação de criar_previsao (api/main.py) — não é aspas,
    CR/LF, barra ou fora do Latin-1 — mas o NTFS recusa como nome de arquivo.
    Sem sanitização, `Path.write_bytes` levantaria OSError e abortaria o
    laço inteiro, inclusive as previsões que viriam depois na exportação."""
    id_ = _inserir(pool, "previsao:2026.xlsx", b"conteudo qualquer")
    try:
        n = exportar_previsoes(_url(), tmp_path)
        assert n == 1
        arquivos = list(tmp_path.iterdir())
        assert len(arquivos) == 1
        assert ":" not in arquivos[0].name
        assert arquivos[0].read_bytes() == b"conteudo qualquer"
    finally:
        _remover(pool, id_)


def test_nome_seguro_troca_caracteres_proibidos_no_windows():
    """Unitário e direto na função de sanitização, sem depender do banco —
    cobre o conjunto inteiro de caracteres que o NTFS recusa (a API só
    barra um subconjunto deles: aspas, barra invertida e controle)."""
    assert _nome_seguro('a:b*c?d"e<f>g|h.xlsx') == "a_b_c_d_e_f_g_h.xlsx"


def test_exportar_previsoes_tabela_vazia_nao_gera_arquivo(pool, tmp_path):
    """Sem previsão nenhuma o backup não pode inventar arquivo nem levantar —
    o fixture já entrega a tabela vazia."""
    n = exportar_previsoes(_url(), tmp_path)
    assert n == 0
    assert list(tmp_path.iterdir()) == []


def test_tabela_leituras_escolhe_o_nome_novo_quando_existe(pool):
    """Cenário comum: banco já rodou o RENAME_SQL e está em `leituras`."""
    with pool.connection() as conn:
        assert _tabela_leituras(conn) == "leituras"


def test_tabela_leituras_cai_no_antigo_quando_so_medicoes_existe(pool):
    """Cenário raro mas real: restaurar backup pré-rename num Postgres limpo
    e rodar backup.py antes de subir a API — a API é quem faz o rename, sem
    ela `leituras` não existe ainda. O script tem que continuar funcionando."""
    with pool.connection() as conn:
        conn.execute("DROP TABLE leituras CASCADE")
        conn.execute(
            "CREATE TABLE medicoes ("
            "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
            "regiao TEXT NOT NULL, altura_cm DOUBLE PRECISION NOT NULL, "
            "nivel_risco TEXT NOT NULL, temperatura_c DOUBLE PRECISION, "
            "clima TEXT, criado_em TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        try:
            assert _tabela_leituras(conn) == "medicoes"
        finally:
            conn.execute("DROP TABLE medicoes")
    # Recria `leituras` pra não vazar tabela dropada pro próximo teste da
    # suíte, que pode ser em outro arquivo (test_db.py também mexe aqui).
    db.criar_schema(pool)


def test_tabela_leituras_erra_com_mensagem_clara_quando_nenhuma_existe(pool):
    """Sem `leituras` nem `medicoes` o COPY estouraria UndefinedTable sem
    explicar. A função tem que devolver mensagem que aponte a causa."""
    with pool.connection() as conn:
        conn.execute("DROP TABLE leituras CASCADE")
        try:
            with pytest.raises(RuntimeError, match="nem `medicoes`"):
                _tabela_leituras(conn)
        finally:
            pass
    db.criar_schema(pool)
