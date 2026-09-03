"""Baixa as medições de produção para arquivos locais.

É a garantia prática de posse dos dados: o CSV abre no Excel e o .sql
restaura em QUALQUER Postgres, então a equipe nunca fica presa ao
fornecedor de hospedagem.

Usa só o psycopg (já nas dependências) — não precisa do pg_dump instalado.

Uso:  python scripts/backup.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import tuple_row

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


def _tabela_leituras(conn) -> str:
    """Descobre se o banco está no nome novo (`leituras`) ou ainda no antigo
    (`medicoes`). Cenário raro mas real: restaurar um backup pré-rename num
    Postgres limpo e rodar este script antes de subir a API — a API é quem
    faz o rename via RENAME_SQL, então sem ela `leituras` não existe ainda.
    Prefere `leituras` se ambos existirem (transição no meio); aborta com
    mensagem clara se nenhum existir, em vez de deixar o COPY estourar
    UndefinedTable sem explicação."""
    # `tuple_row` explícito: `main()` chama com `psycopg.connect(url)` puro
    # (tuplas), mas os testes passam uma conexão do pool da API (dict_row).
    # Sem isto, `r[0]` estoura KeyError na chamada de teste.
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(%s)",
            (["leituras", "medicoes"],),
        )
        rows = cur.fetchall()
    nomes = {r[0] for r in rows}
    if "leituras" in nomes:
        return "leituras"
    if "medicoes" in nomes:
        return "medicoes"
    raise RuntimeError(
        "banco sem tabela de medições — não achou `leituras` nem `medicoes`"
    )


def exportar(url: str, destino: Path) -> tuple[Path, Path, int]:
    """Grava <destino>.csv e <destino>.sql. Retorna (csv, sql, nº de linhas).

    Lê da tabela que existir (`leituras` ou `medicoes`, veja
    `_tabela_leituras`); o .sql de saída SEMPRE escreve `leituras`, que é o
    nome canônico atual — restaurar num banco vazio recria já no schema novo,
    consistente com o que a API espera."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    csv_path = destino.with_suffix(".csv")
    sql_path = destino.with_suffix(".sql")

    with psycopg.connect(url) as conn:
        tabela = _tabela_leituras(conn)
        # f-string em SQL é seguro aqui: `_tabela_leituras` só retorna dois
        # literais controlados ("leituras" ou "medicoes"), nada vindo do
        # usuário.
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            with conn.cursor().copy(
                f"COPY {tabela} TO STDOUT WITH (FORMAT csv, HEADER true)"
            ) as copy:
                for bloco in copy:
                    f.write(bytes(bloco).decode("utf-8"))

        linhas = conn.execute(f"SELECT * FROM {tabela} ORDER BY id").fetchall()

    with sql_path.open("w", encoding="utf-8") as f:
        f.write("-- Backup de leituras. Restaure com: psql \"$URL\" < este.sql\n")
        f.write(
            "CREATE TABLE IF NOT EXISTS leituras (\n"
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
                f"INSERT INTO leituras ({', '.join(COLUNAS)}) "
                f"VALUES ({valores});\n"
            )

    return csv_path, sql_path, len(linhas)


def _literal(valor) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)):
        return repr(valor)
    return "'" + str(valor).replace("'", "''") + "'"


# `criar_previsao` (api/main.py) só recusa o que corromperia um header HTTP
# (aspas, barra invertida, controle, fora do Latin-1) — não tem por que saber
# de NTFS. `:` `*` `?` `<` `>` `|` passam por aquela validação tranquilos e
# ainda assim o Windows recusa como nome de arquivo, então "previsao:2026.xlsx"
# é um nome válido no banco e inválido em disco. Troca por "_" em vez de
# recusar: isto é backup, não upload — perder um caractere cosmético do nome
# é aceitável, abortar a exportação (ou a linha) não é.
_CARACTERES_INVALIDOS_ARQUIVO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _nome_seguro(nome: str) -> str:
    """Troca por `_` os caracteres que o Windows recusa em nome de arquivo."""
    nome = _CARACTERES_INVALIDOS_ARQUIVO.sub("_", nome)
    # Windows também recusa nome terminado em espaço ou ponto; troca por um
    # nome genérico só no caso degenerado de sobrar vazio (nome era só pontos
    # e espaços).
    return nome.rstrip(" .") or "previsao"


def exportar_previsoes(url: str, destino: Path) -> int:
    """Grava cada previsão como .xlsx dentro de <destino>/. Retorna quantas.

    Arquivo de verdade em vez de bytea codificado dentro de um INSERT: abre
    no Excel na hora, que é o ponto do backup. NÃO acrescente `previsoes` ao
    export .sql: `_literal` cai no `str(valor)` pra tipos desconhecidos, o que
    num `bytes` emite o repr do Python (`'b'PK\\x03\\x04''`) e gera um .sql que
    restaura dado corrompido sem erro nenhum.
    """
    destino.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url) as conn:
        linhas = conn.execute(
            "SELECT id, nome_arquivo, conteudo FROM previsoes ORDER BY id"
        ).fetchall()

    gravadas = 0
    for linha in linhas:
        id_, nome, conteudo = linha
        # Prefixo com o id: dois uploads podem ter o mesmo nome de arquivo,
        # e também sobrevive à sanitização acima colidir dois nomes distintos.
        caminho = destino / f"{id_:04d}-{_nome_seguro(nome)}"
        try:
            caminho.write_bytes(bytes(conteudo))
        except OSError as erro:
            # Defesa em profundidade: a sanitização acima já deveria bastar,
            # mas um SO tem mais reservas do que a lista de caracteres cobre
            # (nomes reservados tipo CON/NUL, caminho longo demais). Uma
            # previsão ilegível não pode derrubar as que vêm depois no laço.
            print(f"AVISO: previsão {id_} não pôde ser gravada ({erro})", file=sys.stderr)
            continue
        gravadas += 1
    return gravadas


def main() -> int:
    load_dotenv(RAIZ / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERRO: DATABASE_URL não definida no .env", file=sys.stderr)
        return 1

    carimbo = datetime.now().strftime("%Y-%m-%d-%H%M")
    csv_path, sql_path, n = exportar(url, RAIZ / "backups" / f"medicoes-{carimbo}")
    n_previsoes = exportar_previsoes(url, RAIZ / "backups" / f"previsoes-{carimbo}")

    print(f"{n} medições exportadas")
    print(f"  CSV: {csv_path.relative_to(RAIZ)}")
    print(f"  SQL: {sql_path.relative_to(RAIZ)}")
    print(f"{n_previsoes} previsões exportadas")
    if n_previsoes:
        print(f"  XLSX: backups/previsoes-{carimbo}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
