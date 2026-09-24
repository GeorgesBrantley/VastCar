# Vastcar Administration Guide

This is the operational runbook for developing and hosting Vastcar.

Production runs as the Fly app `vastcar` in the `ord` region. It must use exactly one Fly Machine because the web server, scheduler, accounts, and race results share one SQLite database. The production database lives on the `league_data` volume at `/data/league.sqlite3`.

## The three kinds of database

Keep these separate:

| Database | Location | Purpose |
| --- | --- | --- |
| Production | Fly volume: `/data/league.sqlite3` | The authoritative live league, accounts, bets, and results |
| Local development | `data/dev.sqlite3` | Safe testing; it may be reset or replaced at any time |
| Backups | `backups/vastcar-YYYY-MM-DD-HHMMSS.sqlite3` | Read-only recovery copies downloaded from production |

Never commit a database, backup, `.env` file, or secret. The `data/` and `backups/` directories are ignored by Git.

Once a production backup is started locally, the local scheduler may advance it according to the current time. It has become a development copy and must not be uploaded back to production as though it were still a pristine backup.

## Start and stop the local server

Vastcar requires Python 3.9 or newer and has no package dependencies.

Start a local development league from the repository root:

```sh
cd "/Users/georges/Documents/VastCar"
APP_SESSION_SECRET=local-development-only \
AUTH_COOKIE_SECURE=false \
python3 server.py --db data/dev.sqlite3
```

Open [http://localhost:8000](http://localhost:8000).

Stop it gracefully with `Ctrl+C` in the terminal running the server. A graceful stop closes SQLite and checkpoints its WAL. Before starting another copy, check that port 8000 is clear:

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Do not run two server processes against the same SQLite file.

### Refresh the local test database from production

First download a production backup using the procedure below. With the local server stopped, copy that backup to the development location:

```sh
cp backups/vastcar-YYYY-MM-DD-HHMMSS.sqlite3 data/dev.sqlite3
rm -f data/dev.sqlite3-wal data/dev.sqlite3-shm
```

Start the local server against `data/dev.sqlite3`. The file under `backups/` remains the untouched recovery copy.

For a completely fresh league, move the old development database aside and start the server again:

```sh
mv data/dev.sqlite3 data/dev.previous.sqlite3
python3 server.py --db data/dev.sqlite3
```

## Start, stop, and inspect production

Production should normally stay running so the scheduler advances even when no visitors are present.

Inspect it:

```sh
fly status --app vastcar
fly machine list --app vastcar
fly volumes list --app vastcar
fly logs --app vastcar --no-tail
```

Stop production for maintenance by copying the Machine ID from `fly machine list`:

```sh
fly machine stop MACHINE_ID --app vastcar
```

Start it again:

```sh
fly machine start MACHINE_ID --app vastcar
```

Restart without changing the deployed code:

```sh
fly apps restart vastcar
```

While stopped, the website is offline and no process runs. On restart, Vastcar deterministically catches up with races that became due during the outage.

Never scale production above one Machine:

```sh
fly scale count 1 --app vastcar
```

Multiple Machines would create multiple schedulers and cannot safely share this SQLite design.

## Develop and test a feature

Use a feature branch rather than editing production directly:

```sh
git switch -c feature/short-description
```

Recommended loop:

1. Work against `data/dev.sqlite3`, never the production database.
2. Run the automated tests:

   ```sh
   python3 -m unittest discover -s tests -v
   ```

3. Start the local server and test the feature at `http://localhost:8000`.
4. Test registration/login if authentication changed.
5. Check live races, the next-race grid, history, and a page refresh if league state changed.
6. Stop the local server with `Ctrl+C`.
7. Review and commit only code/configuration:

   ```sh
   git status --short
   git diff --check
   git add PATHS_YOU_CHANGED
   git commit -m "Describe the feature"
   git push -u origin feature/short-description
   ```

Open a pull request or review the branch diff, then merge it into `main` only after local verification.

Tests create temporary databases and do not touch `data/dev.sqlite3` or production.

## Back up production

Make an off-server backup at least weekly and immediately before any database, authentication, scheduling, or deployment change that could alter stored data.

Do not download `/data/league.sqlite3` directly while the server is running. SQLite may have committed pages in its WAL. Instead, use SQLite's online backup API to create a consistent snapshot.

### 1. Create a consistent backup on the Fly volume

Remove any incomplete temporary backup left by an earlier attempt:

```sh
fly ssh console --app vastcar -C "rm -f /data/admin-backup.sqlite3 /data/admin-backup.sqlite3-wal /data/admin-backup.sqlite3-shm"
```

Then create the backup:

```sh
fly ssh console --app vastcar -C "python -c 'import sqlite3; source=sqlite3.connect(\"/data/league.sqlite3\"); target=sqlite3.connect(\"/data/admin-backup.sqlite3\"); source.backup(target); target.close(); source.close()'"
```

### 2. Download it

```sh
mkdir -p backups
BACKUP_FILE="backups/vastcar-$(date +%Y-%m-%d-%H%M%S).sqlite3"
fly ssh sftp get /data/admin-backup.sqlite3 "$BACKUP_FILE" --app vastcar
```

### 3. Validate it

```sh
sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;"
```

The expected result is:

```text
ok
```

Optionally inspect its important counts:

```sh
sqlite3 "$BACKUP_FILE" "SELECT 'users', count(*) FROM users; SELECT 'completed races', count(*) FROM races WHERE completed=1;"
```

### 4. Remove the temporary server-side copy

Only after the download passes `integrity_check`:

```sh
fly ssh console --app vastcar -C "rm -f /data/admin-backup.sqlite3 /data/admin-backup.sqlite3-wal /data/admin-backup.sqlite3-shm"
```

Fly also takes automatic volume snapshots. The repository requests 14-day retention in `fly.toml`, but an existing volume may retain its original setting until explicitly updated. Check the volume ID and update it once if necessary:

```sh
fly volumes list --app vastcar
fly volumes update VOLUME_ID --snapshot-retention 14 --app vastcar
fly volumes snapshots list VOLUME_ID --app vastcar
```

Snapshots are a useful second layer, not a replacement for downloaded backups. Fly notes that automatic snapshots may not contain the latest data.

## Restore production from a backup

Restoring replaces the entire live database, including accounts, coins, bets, races, and results. First make a backup of the current production database even if it appears damaged.

Validate the selected backup locally:

```sh
sqlite3 backups/vastcar-YYYY-MM-DD-HHMMSS.sqlite3 "PRAGMA integrity_check;"
```

Upload it using the special import filename:

```sh
fly ssh sftp put \
  backups/vastcar-YYYY-MM-DD-HHMMSS.sqlite3 \
  /data/league.import.sqlite3 \
  --app vastcar
```

Restart production:

```sh
fly apps restart vastcar
```

At startup, `docker-entrypoint.sh` sees `league.import.sqlite3`, removes the old database plus its WAL/SHM files, moves the import into place, and only then starts Python. The import file is consumed once; ordinary restarts and deployments do not replace the database.

Verify the restore:

```sh
fly status --app vastcar
fly logs --app vastcar --no-tail
open https://vastcar.fly.dev
```

## Deploy a tested feature

Back up production first when the release touches SQLite schema, schedule generation, authentication, accounts, betting, elections, or race settlement.

There are two deployment paths. Use one for a given commit, not both.

### Manual deployment

This is the clearest option while actively developing:

```sh
git switch main
git pull --ff-only
python3 -m unittest discover -s tests -v
fly deploy --app vastcar --remote-only
```

The code image is replaced, but `/data` remains on the persistent volume.

Verify every deployment:

```sh
fly status --app vastcar
fly logs --app vastcar --no-tail
curl -f https://vastcar.fly.dev/api/state
```

Then open the website and perform a hard refresh.

### GitHub automatic deployment

`.github/workflows/fly-deploy.yml` deploys pushes to `main` or `master` once that workflow is committed and the GitHub repository has a `FLY_API_TOKEN` Actions secret.

With automatic deployment enabled, the flow is:

```text
feature branch → local tests → pull request/review → merge to main → GitHub deploys Fly
```

The current workflow deploys but does not run the Python test suite. Continue running tests locally before merging unless a test step is added to the workflow.

If automatic deployment is not configured, pushing to GitHub only stores the code; run the manual `fly deploy` command afterward.

## Roll back bad code

Do not restore the database merely to undo a frontend or Python code change.

Revert the bad Git commit, verify locally, and deploy the revert:

```sh
git revert BAD_COMMIT_SHA
python3 -m unittest discover -s tests -v
fly deploy --app vastcar --remote-only
```

Restore a database backup only when production data itself was incorrectly changed.

## Secrets and security

- `APP_SESSION_SECRET` belongs in Fly secrets, never Git:

  ```sh
  fly secrets list --app vastcar
  ```

- `AUTH_COOKIE_SECURE=true` is set in `fly.toml` for production HTTPS.
- Rotating `APP_SESSION_SECRET` logs everybody out.
- Never commit Fly access tokens or GitHub's `FLY_API_TOKEN`.
- Keep one production Machine and one attached `league_data` volume.
- Do not bake `data/` into the Docker image; it is intentionally excluded by `.dockerignore`.

## Expected cost

As of September 24, 2026, the configured `shared-cpu-1x` Machine with 256 MB RAM is approximately **$2.02–$2.24 per month**, depending on Fly's regional rate. The 1 GB volume is **$0.15 per month**. Snapshot storage is **$0.08/GB-month**, with the first 10 GB currently free. Light outbound traffic should be small but is usage-based.

Expect roughly **$2.20–$2.50 per month for Fly**, plus approximately **$10–$12 per year** for a typical `.com` domain. Prices can change; check [Fly resource pricing](https://fly.io/docs/about/pricing/) and the Fly billing dashboard.

## Quick health checklist

```sh
fly status --app vastcar
fly machine list --app vastcar
fly volumes list --app vastcar
fly logs --app vastcar --no-tail
curl -f https://vastcar.fly.dev/api/state
```

Healthy production means:

- exactly one Machine is started;
- `league_data` is attached to that Machine;
- the API returns HTTP 200;
- logs contain no repeating Python tracebacks or SQLite errors;
- the website shows `CIRCUIT ONLINE`.
