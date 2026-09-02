"""Testes dos endpoints da API."""


def _payload(regiao="mato do matheus", altura=5.2, risco="MEDIA", **extras):
    corpo = {"regiao": regiao, "altura_cm": altura, "nivel_risco": risco}
    corpo.update(extras)
    return corpo


# --- POST /leituras ----------------------------------------------------------
def test_post_persiste_clima_enviado_pela_estacao(client, headers_escrita):
    """API só armazena — clima vem da estação (o IP compartilhado do Render
    toma 429 do Open-Meteo, o IP residencial da estação não)."""
    r = client.post(
        "/leituras",
        json=_payload(temperatura_c=21.5, clima="Nublado"),
        headers=headers_escrita,
    )
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["id"] == 1
    assert corpo["regiao"] == "mato do matheus"
    assert corpo["altura_cm"] == 5.2
    assert corpo["temperatura_c"] == 21.5
    assert corpo["clima"] == "Nublado"


def test_post_sem_clima_persiste_null(client, headers_escrita):
    """Se a estação estiver offline pro Open-Meteo, a medição salva sem clima."""
    r = client.post("/leituras", json=_payload(), headers=headers_escrita)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["temperatura_c"] is None
    assert corpo["clima"] is None


def test_post_persiste_de_fato_no_banco(client, headers_escrita, headers_leitura):
    """Prova que o dado sobrevive fora da memória do processo."""
    client.post("/leituras", json=_payload(altura=7.7), headers=headers_escrita)
    with client.app.state.pool.connection() as conn:
        row = conn.execute("SELECT altura_cm FROM leituras").fetchone()
    assert row["altura_cm"] == 7.7


def test_post_sem_regiao_e_rejeitado(client, headers_escrita):
    corpo = _payload()
    del corpo["regiao"]
    r = client.post("/leituras", json=corpo, headers=headers_escrita)
    assert r.status_code == 422


def test_post_com_regiao_vazia_e_rejeitado(client, headers_escrita):
    r = client.post("/leituras", json=_payload(regiao=""), headers=headers_escrita)
    assert r.status_code == 422


def test_post_com_altura_negativa_e_rejeitado(client, headers_escrita):
    r = client.post("/leituras", json=_payload(altura=-1), headers=headers_escrita)
    assert r.status_code == 422


def test_post_com_nivel_invalido_e_rejeitado(client, headers_escrita):
    r = client.post(
        "/leituras", json=_payload(risco="ALTISSIMA"), headers=headers_escrita
    )
    assert r.status_code == 422


# --- Autenticação ------------------------------------------------------------
def test_post_com_chave_de_leitura_e_negado(client, headers_leitura):
    """O consumidor externo só lê: a chave dele não pode inserir dado falso."""
    r = client.post("/leituras", json=_payload(), headers=headers_leitura)
    assert r.status_code == 401


def test_post_sem_chave_e_negado(client):
    r = client.post("/leituras", json=_payload())
    assert r.status_code == 401


def test_get_sem_chave_e_negado(client):
    r = client.get("/leituras")
    assert r.status_code == 401


def test_get_com_chave_de_leitura_funciona(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_chave_de_escrita_tambem_le(client, headers_escrita):
    """Conveniência para as estações e para debug."""
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_escrita)
    assert r.status_code == 200


# --- GET /leituras -----------------------------------------------------------
def test_get_filtra_por_regiao(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(regiao="norte"), headers=headers_escrita)
    client.post("/leituras", json=_payload(regiao="sul"), headers=headers_escrita)
    r = client.get("/leituras", params={"regiao": "sul"}, headers=headers_leitura)
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo) == 1
    assert corpo[0]["regiao"] == "sul"


def test_get_sem_filtro_traz_todas_as_regioes(
    client, headers_escrita, headers_leitura
):
    client.post("/leituras", json=_payload(regiao="norte"), headers=headers_escrita)
    client.post("/leituras", json=_payload(regiao="sul"), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    assert len(r.json()) == 2


def test_get_ordena_do_mais_recente_para_o_mais_antigo(
    client, headers_escrita, headers_leitura
):
    client.post("/leituras", json=_payload(altura=1.0), headers=headers_escrita)
    client.post("/leituras", json=_payload(altura=2.0), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    assert [m["altura_cm"] for m in r.json()] == [2.0, 1.0]


def test_get_respeita_limit(client, headers_escrita, headers_leitura):
    for _ in range(3):
        client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", params={"limit": 2}, headers=headers_leitura)
    assert len(r.json()) == 2


def test_get_criado_em_vem_em_iso8601(client, headers_escrita, headers_leitura):
    """O consumidor parseia com pandas; ISO evita ambiguidade de formato."""
    from datetime import datetime

    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/leituras", headers=headers_leitura)
    datetime.fromisoformat(r.json()[0]["criado_em"])  # não pode levantar


# --- GET /leituras/{id} ------------------------------------------------------
def test_get_por_id_retorna_a_medicao(client, headers_escrita, headers_leitura):
    novo = client.post(
        "/leituras", json=_payload(), headers=headers_escrita
    ).json()
    r = client.get(f"/leituras/{novo['id']}", headers=headers_leitura)
    assert r.status_code == 200
    assert r.json()["id"] == novo["id"]


def test_get_por_id_inexistente_retorna_404(client, headers_leitura):
    r = client.get("/leituras/9999", headers=headers_leitura)
    assert r.status_code == 404


# --- Raiz --------------------------------------------------------------------
def test_raiz_nao_exige_chave(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --- Aliases de compatibilidade ----------------------------------------------
# As estações em campo (medir_grama.py) postam em /medicoes e não se atualizam
# sozinhas. Sem estes aliases, o primeiro deploy derruba toda a captura até
# alguém ir de máquina em máquina. Some quando as estações estiverem atualizadas.
def test_post_no_alias_medicoes_ainda_grava(client, headers_escrita):
    r = client.post("/medicoes", json=_payload(), headers=headers_escrita)
    assert r.status_code == 200
    assert r.json()["regiao"] == "mato do matheus"


def test_get_no_alias_medicoes_ainda_le(client, headers_escrita, headers_leitura):
    client.post("/leituras", json=_payload(), headers=headers_escrita)
    r = client.get("/medicoes", headers=headers_leitura)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_alias_medicoes_exige_chave(client):
    r = client.post("/medicoes", json=_payload())
    assert r.status_code == 401


def test_aliases_ficam_fora_da_documentacao(client):
    """Ninguém novo deve descobrir /medicoes e passar a depender dele."""
    caminhos = client.get("/openapi.json").json()["paths"]
    assert "/leituras" in caminhos
    assert "/medicoes" not in caminhos
