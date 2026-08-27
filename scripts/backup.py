"""Baixa as medições de produção para arquivos locais.

É a garantia prática de posse dos dados: o CSV abre no Excel e o .sql
restaura em QUALQUER Postgres, então a equipe nunca fica presa ao
fornecedor de hospedagem.

Usa só o psycopg (já nas dependências) — não precisa do pg_dump instalado.

Uso:  python scripts/backup.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

COLUNAS = (
    "id",
    "regiao",
    "altura_cm",
    "nivel_risco",
    "temperatura_c",
    "clima",
    "criado_em",
)


def exportar(url: str, destino: Path) -> tuple[Path, Path, int]:
    """Grava <destino>.csv e <destino>.sql. Retorna (csv, sql, nº de linhas)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    csv_path = destino.with_suffix(".csv")
    sql_path = destino.with_suffix(".sql")

    with psycopg.connect(url) as conn:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            with conn.cursor().copy(
                "COPY medicoes TO STDOUT WITH (FORMAT csv, HEADER true)"
            ) as copy:
                for bloco in copy:
                    f.write(bytes(bloco).decode("utf-8"))

        linhas = conn.execute("SELECT * FROM medicoes ORDER BY id").fetchall()

    with sql_path.open("w", encoding="utf-8") as f:
        f.write("-- Backup de medicoes. Restaure com: psql \"$URL\" < este.sql\n")
        f.write(
            "CREATE TABLE IF NOT EXISTS medicoes (\n"
            "    id            BIGINT PRIMARY KEY,\n"
            "    regiao        TEXT NOT NULL,\n"
            "    altura_cm     DOUBLE PRECISION NOT NULL,\n"
            "    nivel_risco   TEXT NOT NULL,\n"
            "    temperatura_c DOUBLE PRECISION,\n"
            "    clima         TEXT,\n"
            "    criado_em     TIMESTAMPTZ NOT NULL\n"
            ");\n\n"
        )
        for linha in linhas:
            valores = ", ".join(_literal(v) for v in linha)
            f.write(
                f"INSERT INTO medicoes ({', '.join(COLUNAS)}) "
                f"VALUES ({valores});\n"
            )

    return csv_path, sql_path, len(linhas)


def _literal(valor) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)):
        return repr(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def main() -> int:
    load_dotenv(RAIZ / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERRO: DATABASE_URL não definida no .env", file=sys.stderr)
        return 1

    carimbo = datetime.now().strftime("%Y-%m-%d-%H%M")
    csv_path, sql_path, n = exportar(url, RAIZ / "backups" / f"medicoes-{carimbo}")

    print(f"{n} medições exportadas")
    print(f"  CSV: {csv_path.relative_to(RAIZ)}")
    print(f"  SQL: {sql_path.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
