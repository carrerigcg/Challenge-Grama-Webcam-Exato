"""Insere medições de exemplo no banco pra o consumidor externo testar GETs.

One-shot. Backdateia criado_em pra formar uma série temporal de ~4 semanas,
o que POST /leituras não permite (aquele grava now() sempre).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

# (dias_atras, hora_utc, regiao, altura_cm, nivel_risco, temperatura_c, clima)
# Alturas coerentes com as faixas de medir_grama.py:
#   BAIXA  <= 3.0
#   MEDIA  3.0 < h <= 7.0
#   ALTA   > 7.0
#   AUSENTE = sem grama detectada (altura 0.0)
EXEMPLOS = [
    # --- Rod. Anchieta: manutenção recente, grama volta a crescer ---
    (28, 14, "Rod. Anchieta",     8.4,  "ALTA",    19.2, "Nublado"),
    (26, 14, "Rod. Anchieta",     9.1,  "ALTA",    21.0, "Céu limpo"),
    (21, 14, "Rod. Anchieta",     0.0,  "AUSENTE", 18.5, "Chuva leve"),   # roçada
    (19, 14, "Rod. Anchieta",     0.6,  "BAIXA",   20.1, "Céu limpo"),
    (14, 14, "Rod. Anchieta",     1.9,  "BAIXA",   22.4, "Parcialmente nublado"),
    ( 7, 14, "Rod. Anchieta",     3.7,  "MEDIA",   24.8, "Céu limpo"),
    ( 2, 14, "Rod. Anchieta",     5.2,  "MEDIA",   None, None),          # Open-Meteo caiu
    ( 0, 14, "Rod. Anchieta",     6.1,  "MEDIA",   23.9, "Nublado"),

    # --- Rod. Imigrantes: grama alta há semanas, cliente atrasou roçada ---
    (27, 15, "Rod. Imigrantes",   7.8,  "ALTA",    18.7, "Chuva leve"),
    (20, 15, "Rod. Imigrantes",   9.3,  "ALTA",    20.4, "Nublado"),
    (13, 15, "Rod. Imigrantes",  10.6,  "ALTA",    None, None),
    ( 6, 15, "Rod. Imigrantes",  11.9,  "ALTA",    22.8, "Céu limpo"),
    ( 1, 15, "Rod. Imigrantes",  12.4,  "ALTA",    24.1, "Parcialmente nublado"),

    # --- Rod. Ayrton Senna: estável em faixa segura ---
    (25, 10, "Rod. Ayrton Senna", 2.1,  "BAIXA",   17.9, "Nublado"),
    (18, 10, "Rod. Ayrton Senna", 2.8,  "BAIXA",   19.6, "Céu limpo"),
    (11, 10, "Rod. Ayrton Senna", 3.4,  "MEDIA",   21.2, "Céu limpo"),
    ( 4, 10, "Rod. Ayrton Senna", 4.0,  "MEDIA",   22.7, "Parcialmente nublado"),
    ( 0, 10, "Rod. Ayrton Senna", 4.6,  "MEDIA",   23.3, "Nublado"),
]


def main() -> None:
    agora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    linhas = []
    for dias, hora, regiao, altura, nivel, temp, clima in EXEMPLOS:
        criado_em = (agora - timedelta(days=dias)).replace(hour=hora)
        linhas.append((regiao, altura, nivel, temp, clima, criado_em))

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO leituras
                    (regiao, altura_cm, nivel_risco, temperatura_c, clima, criado_em)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                linhas,
            )
    print(f"OK: {len(linhas)} medições inseridas")


if __name__ == "__main__":
    main()
