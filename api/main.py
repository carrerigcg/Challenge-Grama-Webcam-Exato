import os
import sqlite3
from contextlib import contextmanager
from enum import Enum

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from api.clima import SP_LAT, SP_LON, buscar_clima

load_dotenv()

DB_PATH = "medicoes.db"

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    raise RuntimeError(
        "API_KEY não configurada. Crie um arquivo .env com API_KEY=sua_chave"
    )

app = FastAPI(title="API Grama Webcam")


# --- Autenticação ------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verificar_api_key(api_key: str | None = Depends(api_key_header)) -> None:
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida ou ausente")


# --- Banco de dados ----------------------------------------------------------
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def criar_tabela():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regiao TEXT NOT NULL,
                altura_cm REAL NOT NULL,
                nivel_risco TEXT NOT NULL,
                temperatura_c REAL,
                clima TEXT,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


# --- Schemas -----------------------------------------------------------------
class NivelRisco(str, Enum):
    AUSENTE = "AUSENTE"
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class MedicaoIn(BaseModel):
    regiao: str = "mato do matheus"
    altura_cm: float = Field(ge=0)
    nivel_risco: NivelRisco


class MedicaoOut(BaseModel):
    id: int
    regiao: str
    altura_cm: float
    nivel_risco: NivelRisco
    temperatura_c: float | None
    clima: str | None
    criado_em: str


# --- Endpoints ---------------------------------------------------------------
@app.get("/")
def raiz():
    return {"status": "ok", "mensagem": "API no ar"}


@app.post(
    "/medicoes",
    response_model=MedicaoOut,
    dependencies=[Depends(verificar_api_key)],
)
def criar_medicao(medicao: MedicaoIn):
    temperatura, clima = buscar_clima(SP_LAT, SP_LON)
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO medicoes (regiao, altura_cm, nivel_risco, temperatura_c, clima)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                medicao.regiao,
                medicao.altura_cm,
                medicao.nivel_risco.value,
                temperatura,
                clima,
            ),
        )
        novo_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM medicoes WHERE id = ?", (novo_id,)
        ).fetchone()
        return dict(row)


@app.get(
    "/medicoes",
    response_model=list[MedicaoOut],
    dependencies=[Depends(verificar_api_key)],
)
def listar_medicoes(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM medicoes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get(
    "/medicoes/{medicao_id}",
    response_model=MedicaoOut,
    dependencies=[Depends(verificar_api_key)],
)
def buscar_medicao(medicao_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM medicoes WHERE id = ?", (medicao_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Medição não encontrada")
        return dict(row)
