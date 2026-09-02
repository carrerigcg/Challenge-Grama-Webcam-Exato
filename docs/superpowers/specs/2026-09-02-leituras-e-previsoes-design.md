# Design: `/leituras` e `/previsoes`

**Data:** 2026-09-02
**Status:** aprovado

## Contexto

O consumidor externo desenhou um diagrama da arquitetura com três atores (monitoramento,
IA de previsão, app), uma API FastAPI autenticada por `X-API-Key` e dois armazenamentos:
Postgres para as leituras e storage de arquivos para as planilhas `.xlsx`.

Em 2026-08-27 o escopo tinha sido fechado sem `/previsoes` — gerar a planilha era
responsabilidade do consumidor externo, a partir do JSON. Em 2026-09-02 o usuário
reabriu: a API passa a implementar os quatro endpoints do diagrama.

O que já existe no repositório cobre metade do diagrama: autenticação por chave
(`api/main.py`, chaves separadas de escrita e leitura), Postgres no Neon e a tabela
`medicoes`. Falta o rename para `leituras` e a rota `/previsoes` inteira, com o
armazenamento dos arquivos.

## Escopo

Os quatro endpoints do diagrama:

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| POST | `/leituras` | escrita | grava uma medição |
| GET | `/leituras` | leitura | lista medições, com filtro `regiao` e `limit` |
| POST | `/previsoes` | escrita | recebe um `.xlsx` |
| GET | `/previsoes` | leitura | devolve o `.xlsx` mais recente |

**Fora de escopo:** o store-and-forward das estações do rodoanel. É um problema
independente, travado nas seis decisões pendentes da equipe.

## Decisões

### `/medicoes` vira `/leituras`, tabela junto

A rota e a tabela são renomeadas. Meio renomeado — rota nova sobre tabela velha — é
pior de manter do que os dois nomes coerentes.

O projeto não usa framework de migration: o schema nasce de `criar_schema()` com
`CREATE TABLE IF NOT EXISTS`, chamado no `lifespan` a cada boot. O rename entra no
mesmo lugar, como bloco `DO $$` idempotente que só age se `medicoes` existir e
`leituras` ainda não. Roda uma vez contra o Neon de produção e vira no-op para sempre.

O índice `idx_medicoes_regiao_criado_em` acompanha o rename da tabela; o Postgres o
mantém funcionando com o nome antigo, então ele é renomeado explicitamente para
`idx_leituras_regiao_criado_em`.

### `GET /leituras/{id}` fica

Já existe e é testado. O diagrama não mostra, mas apagar código que funciona não fazia
parte do pedido.

### `/medicoes` continua respondendo, como alias oculto

`medir_grama.py` faz POST em `/medicoes` e as estações no campo não se atualizam
sozinhas. Sem alias, o primeiro deploy quebra toda a captura até alguém atualizar
máquina por máquina. As rotas antigas ficam registradas com `include_in_schema=False`,
apontando para os mesmos handlers, e saem quando as estações estiverem atualizadas.

### Previsões vão como `bytea` no Neon, não em disco

O filesystem do Render no plano free é efêmero: o serviço hiberna após ~15 minutos sem
tráfego e o disco é recriado a cada deploy. Um arquivo salvo em `previsoes/` desaparece
sozinho — "storage de arquivos" no diagrama não pode ser disco local.

Bucket externo (R2, B2) resolveria, mas custa conta nova, credenciais e SDK, contra os
critérios de infra do projeto: 100% gratuito e sem lock-in.

No Postgres, um valor grande já é comprimido e guardado fora da linha pelo TOAST
automaticamente. Uma planilha de previsão tem poucos KB; os 0,5 GB do plano free do Neon
seguram milhares. De quebra, `scripts/backup.py` passa a cobrir as planilhas sem
trabalho extra.

### Previsão não tem `regiao`

O diagrama não mostra, e é o consumidor externo quem define o recorte da previsão. Se
depois vier "uma previsão por região", é uma coluna e um filtro de query.

## Schema

Tabela `leituras` — a `medicoes` de hoje, renomeada, sem mudança de colunas.

Tabela nova:

```sql
CREATE TABLE IF NOT EXISTS previsoes (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome_arquivo   TEXT NOT NULL,
    conteudo       BYTEA NOT NULL,
    tamanho_bytes  BIGINT NOT NULL,
    criado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_previsoes_criado_em
    ON previsoes (criado_em DESC);
```

O índice serve o caso principal do `GET`: pegar a mais recente.

## Contrato de `/previsoes`

### `POST /previsoes`

Upload `multipart/form-data`, campo `arquivo`. Exige a chave de escrita — quem publica é
a IA de previsão.

Validações:

- extensão `.xlsx` no nome do arquivo — senão `400`;
- corpo não vazio — senão `400`;
- teto de 10 MB — senão `413`, para ninguém entupir o banco gratuito.

Resposta `201` com o metadado, sem o conteúdo:

```json
{"id": 12, "nome_arquivo": "previsao-2026-09-02.xlsx", "tamanho_bytes": 8241, "criado_em": "2026-09-02T14:03:11Z"}
```

### `GET /previsoes`

Exige a chave de leitura. Sem parâmetro, devolve a previsão mais recente. Com `?id=N`,
devolve aquela — o `id` vem da resposta do POST.

Devolve os bytes do arquivo com `Content-Type`
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` e
`Content-Disposition: attachment; filename="<nome_arquivo>"`, para o app salvar direto.

`404` quando não existe nenhuma previsão, ou quando o `id` pedido não existe.

## Arquivos afetados

- `api/main.py` — rotas renomeadas, aliases ocultos, rotas e schemas de previsão
- `api/db.py` — rename idempotente, tabela `previsoes`
- `medir_grama.py` — passa a postar em `/leituras`
- `scripts/backup.py`, `scripts/seed_exemplos.py` — nome da tabela
- `tests/conftest.py` — `TRUNCATE` nas duas tabelas
- `tests/test_api.py`, `tests/test_db.py` — rotas renomeadas, cobertura de previsões
- `requirements-api.txt` — `python-multipart`, sem o qual o FastAPI não lê upload

## Testes

TDD: teste antes da implementação, em cada etapa.

Os testes de `/medicoes` que já existem são renomeados para `/leituras` — a cobertura
atual (auth, validação, filtro, limite, ordenação, 404) continua valendo.

Cobertura nova:

- `criar_schema` renomeia `medicoes` para `leituras` quando só a antiga existe;
- `criar_schema` é no-op quando `leituras` já existe (rodar duas vezes não quebra);
- os aliases `/medicoes` respondem igual às rotas novas;
- `POST /previsoes` grava o arquivo e devolve o metadado;
- `POST /previsoes` rejeita extensão errada, corpo vazio, arquivo acima de 10 MB, e
  chave de leitura;
- `GET /previsoes` devolve os bytes exatos da mais recente, com o header de download;
- `GET /previsoes?id=N` devolve a pedida, e `404` para id inexistente;
- `GET /previsoes` devolve `404` com a tabela vazia;
- `GET /previsoes` rejeita requisição sem chave.
