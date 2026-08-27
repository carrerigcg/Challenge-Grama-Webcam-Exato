"""Pool de conexões e schema do Postgres."""
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS medicoes (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    regiao        TEXT NOT NULL,
    altura_cm     DOUBLE PRECISION NOT NULL,
    nivel_risco   TEXT NOT NULL,
    temperatura_c DOUBLE PRECISION,
    clima         TEXT,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_medicoes_regiao_criado_em
    ON medicoes (regiao, criado_em DESC);
"""


def criar_pool(database_url: str) -> ConnectionPool:
    """Cria o pool fechado. Quem chama decide quando abrir (lifespan/fixture).

    Abrir/fechar conexão a cada request custa TCP + TLS + auth contra um
    Postgres remoto — caro o bastante pra valer o pool, ainda mais no plano
    gratuito, que limita conexões simultâneas.
    """
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
        open=False,
    )


def criar_schema(pool: ConnectionPool) -> None:
    """Cria tabela e índice se não existirem. Idempotente."""
    with pool.connection() as conn:
        conn.execute(SCHEMA_SQL)
