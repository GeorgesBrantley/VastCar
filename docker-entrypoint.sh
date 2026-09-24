#!/bin/sh
set -eu

database=/data/league.sqlite3
database_import=/data/league.import.sqlite3

# A database import must happen before Python opens SQLite. Removing the old
# WAL and shared-memory files prevents pages from the previous database from
# being replayed over the imported database after a restart.
if [ -f "$database_import" ]; then
    rm -f "$database" "$database-wal" "$database-shm"
    mv "$database_import" "$database"
fi

exec python server.py \
    --host 0.0.0.0 \
    --port 8080 \
    --db "$database"
