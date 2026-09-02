"""API de medições de altura de grama."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from api import db

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada. Veja .env.example")

API_KEY_WRITE = os.environ.get("API_KEY_WRITE")
API_KEY_READ = os.environ.get("API_KEY_READ")
if not API_KEY_WRITE or not API_KEY_READ:
    raise RuntimeError(
        "API_KEY_WRITE e API_KEY_READ são obrigatórias. Veja .env.example"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = db.criar_pool(DATABASE_URL)
    pool.open()
    db.criar_schema(pool)
    app.state.pool = pool
    yield
    pool.close()


app = FastAPI(title="API Grama Webcam", lifespan=lifespan)


# --- Autenticação ------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def requer_escrita(api_key: str | None = Depends(api_key_header)) -> None:
    if api_key != API_KEY_WRITE:
        raise HTTPException(401, "API key de escrita inválida ou ausente")


def requer_leitura(api_key: str | None = Depends(api_key_header)) -> None:
    # A chave de escrita também lê — conveniente pras estações e pra debug.
    # O contrário não vale: quem só lê nunca escreve.
    if api_key not in (API_KEY_READ, API_KEY_WRITE):
        raise HTTPException(401, "API key inválida ou ausente")


# --- Schemas -----------------------------------------------------------------
class NivelRisco(str, Enum):
    AUSENTE = "AUSENTE"
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class MedicaoIn(BaseModel):
    # Sem default: cada estação precisa se identificar, senão leituras de
    # locais diferentes colidem numa região só.
    regiao: str = Field(min_length=1)
    altura_cm: float = Field(ge=0)
    nivel_risco: NivelRisco
    # Clima vem da estação (IP residencial, sem rate-limit compartilhado do
    # Render). Opcional: se a estação estiver offline pro Open-Meteo, a
    # medição salva mesmo assim.
    temperatura_c: float | None = None
    clima: str | None = None


class MedicaoOut(BaseModel):
    id: int
    regiao: str
    altura_cm: float
    nivel_risco: NivelRisco
    temperatura_c: float | None
    clima: str | None
    criado_em: datetime


# --- Endpoints ---------------------------------------------------------------
@app.get("/")
def raiz():
    return {"status": "ok", "mensagem": "API no ar"}


@app.post(
    "/medicoes",
    response_model=MedicaoOut,
    dependencies=[Depends(requer_escrita)],
)
def criar_medicao(medicao: MedicaoIn, request: Request):
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO leituras
                (regiao, altura_cm, nivel_risco, temperatura_c, clima)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                medicao.regiao,
                medicao.altura_cm,
                medicao.nivel_risco.value,
                medicao.temperatura_c,
                medicao.clima,
            ),
        ).fetchone()
    return row


@app.get(
    "/medicoes",
    response_model=list[MedicaoOut],
    dependencies=[Depends(requer_leitura)],
)
def listar_medicoes(
    request: Request,
    regiao: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    sql = "SELECT * FROM leituras"
    params: list = []
    if regiao:
        sql += " WHERE regiao = %s"
        params.append(regiao)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with request.app.state.pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


@app.get(
    "/medicoes/{medicao_id}",
    response_model=MedicaoOut,
    dependencies=[Depends(requer_leitura)],
)
def buscar_medicao(medicao_id: int, request: Request):
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT * FROM leituras WHERE id = %s", (medicao_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Medição não encontrada")
    return row
