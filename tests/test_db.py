"""Testes da camada de banco."""
import os

import pytest
from dotenv import load_dotenv

from api import db

load_dotenv()


@pytest.fixture
def pool():
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não configurada — veja .env.example")
    p = db.criar_pool(url)
    p.open()
    yield p
    p.close()


def test_criar_schema_cria_tabela_medicoes(pool):
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute("SELECT to_regclass('public.medicoes') AS t").fetchone()
    assert row["t"] == "medicoes"


def test_criar_schema_e_idempotente(pool):
    db.criar_schema(pool)
    db.criar_schema(pool)  # rodar de novo não pode levantar
    with pool.connection() as conn:
        row = conn.execute("SELECT count(*) AS n FROM medicoes").fetchone()
    assert row["n"] >= 0


def test_criar_schema_cria_indice_por_regiao(pool):
    db.criar_schema(pool)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'medicoes' AND indexname = %s",
            ("idx_medicoes_regiao_criado_em",),
        ).fetchone()
    assert row is not None


def test_criar_pool_nao_conecta_antes_de_abrir():
    """open=False deixa quem chama decidir a hora de conectar (lifespan/fixture)."""
    p = db.criar_pool("postgresql://ninguem@localhost:1/inexistente")
    assert p.closed
