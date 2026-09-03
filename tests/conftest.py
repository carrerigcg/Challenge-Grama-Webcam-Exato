"""Fixtures compartilhadas dos testes de API.

NÃO rode duas suítes ao mesmo tempo contra a mesma branch do Neon. Os testes
de `test_db.py` dropam e recriam `leituras`/`medicoes`/`previsoes` de
propósito (é o único jeito de testar a migração de rename), então duas
execuções simultâneas se atropelam e falham com `UndefinedTable` em pontos
aleatórios — parecem bug do código, mas são corrida entre processos.

Pelo mesmo motivo, uma execução MORTA no meio (Ctrl+C num teste que já
dropou, processo derrubado) deixa o banco de teste sem alguma tabela: o
teardown de `test_db.py` não roda em processo morto. Para consertar:

    python -c "import sys; sys.path.insert(0,'.'); \
from dotenv import load_dotenv; load_dotenv('.env'); \
import os; from api import db; \
p=db.criar_pool(os.environ['DATABASE_URL_TEST']); p.open(); \
db.criar_schema(p); p.close()"
"""
import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

CHAVE_ESCRITA = "chave-de-escrita-teste"
CHAVE_LEITURA = "chave-de-leitura-teste"


@pytest.fixture(scope="session")
def _env_de_teste():
    """Aponta a API para a branch `test` do Neon antes de importar o app.

    Sem autouse de propósito: só quem pede o `client` depende de banco.
    Com autouse, o skip abaixo pularia a suíte inteira.
    """
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não configurada — veja .env.example")
    # Definir antes do import de api.main: load_dotenv() não sobrescreve
    # variáveis já presentes, então o .env de produção não vaza pro teste.
    os.environ["DATABASE_URL"] = url
    os.environ["API_KEY_WRITE"] = CHAVE_ESCRITA
    os.environ["API_KEY_READ"] = CHAVE_LEITURA
    return url


@pytest.fixture(scope="session")
def _cliente_da_sessao(_env_de_teste):
    """Abre o pool uma única vez.

    Session-scoped de propósito: conectar no Neon custa TCP + TLS + auth, e
    pagar isso por teste levava a suíte a mais de um minuto.
    """
    from api.main import app

    # O `with` é o que dispara o lifespan e abre o pool.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_cliente_da_sessao):
    """Tabela limpa a cada teste, reaproveitando a conexão da sessão."""
    with _cliente_da_sessao.app.state.pool.connection() as conn:
        conn.execute("TRUNCATE leituras, previsoes RESTART IDENTITY")
    return _cliente_da_sessao


@pytest.fixture
def headers_escrita():
    return {"X-API-Key": CHAVE_ESCRITA}


@pytest.fixture
def headers_leitura():
    return {"X-API-Key": CHAVE_LEITURA}
