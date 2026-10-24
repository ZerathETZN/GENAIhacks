#!/bin/sh
# Runs once, on first start of an empty volume. Creates the read-only role Zetaris connects as.
# Tables created later by the admin user (load_postgres.py) are readable via default privileges.
set -eu

if [ -z "${PG_READER_PASSWORD:-}" ]; then
  echo "PG_READER_PASSWORD is empty: set it in .env (live mode)" >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE "$PG_READER_USER" LOGIN PASSWORD '$PG_READER_PASSWORD';
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO "$PG_READER_USER";
GRANT USAGE ON SCHEMA public TO "$PG_READER_USER";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "$PG_READER_USER";
ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public GRANT SELECT ON TABLES TO "$PG_READER_USER";
EOSQL
