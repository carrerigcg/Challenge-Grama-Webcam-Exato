#!/usr/bin/env bash
# Baixa o banco de produção inteiro para um arquivo local.
#
# É a garantia prática de posse dos dados: o dump restaura em QUALQUER
# Postgres (outro provedor, sua máquina, um servidor seu), então a equipe
# nunca fica presa ao fornecedor.
#
# Requer pg_dump instalado (vem com o cliente do PostgreSQL).
# Uso:  bash scripts/backup.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "ERRO: .env não encontrado. Copie de .env.example." >&2
    exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERRO: DATABASE_URL não definida no .env" >&2
    exit 1
fi

mkdir -p backups
ARQUIVO="backups/medicoes-$(date +%Y-%m-%d-%H%M).sql"

pg_dump "$DATABASE_URL" --no-owner --no-acl > "$ARQUIVO"

echo "Backup salvo em $ARQUIVO ($(wc -l < "$ARQUIVO") linhas)"
echo "Para restaurar em outro Postgres:  psql \"\$NOVA_URL\" < $ARQUIVO"
