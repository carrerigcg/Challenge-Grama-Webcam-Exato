"""Reinicia `leituras` com 21 medições de crescimento contínuo pra demo.

Uma região só ("Rod. Anchieta"), 1 ponto a cada 4 dias durante ~12 semanas,
altura estritamente crescente (0.4 → 12.4 cm) atravessando BAIXA, MEDIA e
ALTA. Sem simulação de roçada — o ponto é dar ao consumidor externo uma
série limpa pra plotar e testar GETs.

DESTRUTIVO: TRUNCATE em `leituras` antes de inserir. Exige `--confirm-prod`
pra rodar; sem a flag, sai com erro. Isso mata o acidente clássico de
`python scripts/seed_exemplos.py` sem pensar contra o banco de produção.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

REGIAO = "Rod. Anchieta"
HORA_UTC = 14
N_PONTOS = 21
PASSO_DIAS = 4
ALTURA_INICIAL_CM = 0.4
PASSO_ALTURA_CM = 0.6

# Ciclo curto pra o consumidor externo ver os quatro valores possíveis de
# `clima` no dataset sem ter que rolar muito — não pretende ser meteorologia.
CLIMAS = ("Nublado", "Céu limpo", "Parcialmente nublado", "Chuva leve")


def _nivel_risco(altura_cm: float) -> str:
    # Faixas replicam medir_grama.py: BAIXA ≤ 3.0, MEDIA (3.0, 7.0], ALTA > 7.0.
    if altura_cm <= 3.0:
        return "BAIXA"
    if altura_cm <= 7.0:
        return "MEDIA"
    return "ALTA"


def _gerar_pontos() -> list[tuple[int, float, str, float, str]]:
    """21 tuplas (dias_atras, altura_cm, nivel_risco, temperatura_c, clima).

    dias_atras vai de (N-1)*passo até 0, então o ponto mais recente cai
    exatamente no dia de hoje — GET com filtro "últimos 7 dias" já pega
    algo sem precisar backdate manual."""
    pontos = []
    for i in range(N_PONTOS):
        dias_atras = (N_PONTOS - 1 - i) * PASSO_DIAS
        altura = round(ALTURA_INICIAL_CM + PASSO_ALTURA_CM * i, 1)
        # Temperatura ondula em torno de uma reta 18°C → 26°C ao longo dos
        # 21 pontos, simulando a transição de primavera pra verão em SP sem
        # forçar meteorologia real.
        temperatura = round(18.0 + 0.4 * i + (0.5 if i % 2 else -0.3), 1)
        pontos.append((dias_atras, altura, _nivel_risco(altura), temperatura, CLIMAS[i % 4]))
    return pontos


def main() -> int:
    if "--confirm-prod" not in sys.argv:
        print(
            "ERRO: este script APAGA tudo em `leituras` e insere 21 medições\n"
            "de demonstração. Passe --confirm-prod pra confirmar.",
            file=sys.stderr,
        )
        return 1

    agora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    linhas = []
    for dias, altura, risco, temp, clima in _gerar_pontos():
        criado_em = (agora - timedelta(days=dias)).replace(hour=HORA_UTC)
        linhas.append((REGIAO, altura, risco, temp, clima, criado_em))

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # TRUNCATE + RESTART IDENTITY: reseta a sequence pra `id` começar
            # em 1 na nova série (mais limpo pra demo do que continuar de
            # onde parou). O TRUNCATE requer privilégio de OWNER — o mesmo
            # papel que a API usa pra CREATE TABLE já tem, então funciona
            # tanto local quanto no Neon.
            cur.execute("TRUNCATE leituras RESTART IDENTITY")
            cur.executemany(
                """
                INSERT INTO leituras
                    (regiao, altura_cm, nivel_risco, temperatura_c, clima, criado_em)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                linhas,
            )
    print(f"OK: {len(linhas)} medições em '{REGIAO}' (12 semanas, 1 a cada 4 dias)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
