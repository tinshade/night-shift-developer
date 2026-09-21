# Night Shift Developer

Night Shift Developer is a proof-of-concept that watches application errors, deduplicates repeated failures, and lets a worker investigate them in an isolated environment. The worker can use Groq for code-repair suggestions, Docker for isolated validation, GitHub for pull requests, and Gmail for repair notifications.

The stack contains:

- FastAPI application with PostgreSQL-backed user data
- Redis log storage, streams, status indexes, and deduplication
- A Dockerized repair worker
- A cron-based error generator for end-to-end testing
- Optional Groq, GitHub, and Gmail integrations

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Git
- A Groq API key and an available Groq model for live repair testing
- Optional: GitHub token and Gmail app password for PR and email testing

Keep credentials in a local `.env` file. Never commit `.env` or include credentials in logs, prompts, or pull requests.

## Configuration

Two env files are needed. **`docker compose` refuses to start if
`dummy-api-server/.env` is missing**, so copy both:

```bash
cp .env.example .env
cp dummy-api-server/.env.example dummy-api-server/.env
```

Then put your Groq key in the root `.env`:

```env
GROQ_API_KEY=your-groq-api-key
```

Everything else has a working default. The database credentials live in the
**root** `.env` only - `docker-compose.yaml` injects them into both the
`postgres` and `fastapi` containers from the same variables, so they cannot
drift apart.

The code model diagnoses and patches. The operations model handles optional
GitHub PR and email drafting. GitHub and Gmail are off by default
(`ENABLE_GITHUB_REPAIR`, `ENABLE_EMAIL_NOTIFICATIONS`).

## Setup: Linux

From the repository root:

```bash
git clone <repository-url>
cd night-shift-developer
cp .env.example .env  # if an example file is provided
docker compose --profile worker build
```

If there is no `.env.example`, create `.env` manually using the configuration above. Ensure Docker is running and that the current user can run Docker commands, for example with `docker ps`.

## Setup: Windows

Install Docker Desktop and Git, then open PowerShell:

```powershell
git clone <repository-url>
Set-Location night-shift-developer
Copy-Item .env.example .env  # if an example file is provided
docker compose --profile worker build
```

If `.env.example` does not exist, create `.env` manually. Confirm Docker Desktop is running with:

```powershell
docker version
docker compose version
```

## Run the Stack

Start the application, databases, error generator, and repair worker:

```bash
docker compose --profile worker up -d --build
```

On Windows PowerShell, use the same command.

Check service status:

```bash
docker compose --profile worker ps
```

The FastAPI service is available at `http://localhost:8000`. Useful endpoints include:

- `GET /health`
- `GET /users/` - paginated, takes `limit` and `offset`
- `GET /users/{id}`
- `POST /users/create`
- `DELETE /users/{id}`
- `GET /logs/stats` - log counts by repair status
- `GET /docs` - interactive API docs

View logs:

```bash
docker compose logs -f fastapi
docker compose logs -f worker
```

## Seed a Bug and Watch It Get Fixed

The committed source is clean. Defects are injected on demand - see
[REPRODUCIBLE_BUGS.md](REPRODUCIBLE_BUGS.md) for the full catalogue.

```bash
# 1. break something (B1, B2, B3, B4, or random)
python mess-maker/seed_bugs.py --seed B1

# 2. rebuild the API so the change is live
docker compose up -d --build fastapi

# 3. confirm it reproduces
docker compose exec fastapi python -m pytest -q tests/test_api_contract.py
docker compose run --rm error-generator python force-error.py --bug B1

# 4. watch the worker pick it up
docker compose logs -f worker

# 5. put it back
python mess-maker/seed_bugs.py --revert all
```

`seed_bugs.py --status` shows what is currently broken. Seeding is idempotent
and refuses to touch a file that has drifted from the catalogue.

The cron container also runs the generator hourly per `mess-maker/crontab`,
using whichever bug `FORCE_ERROR_BUG` names.

## Validate the Installation

1. Confirm all core services are running:

	```bash
	docker compose --profile worker ps
	```

	PostgreSQL, Redis, and FastAPI should report healthy; the worker and error generator should be running.

2. Confirm the API responds:

	```bash
	curl http://localhost:8000/health
	```

	On Windows PowerShell:

	```powershell
	Invoke-RestMethod http://localhost:8000/health
	```

3. Trigger an error and inspect the worker:

	```bash
	python mess-maker/seed_bugs.py --seed B1
	docker compose up -d --build fastapi
	docker compose run --rm error-generator python force-error.py --bug B1
	docker compose logs --tail=100 worker
	```

4. Inspect Redis error events:

	```bash
	docker compose exec redis redis-cli XREVRANGE logs:errors + - COUNT 5
	```

	A fresh event should appear with a GUID. Its canonical `log:<guid>` record should move through `open`, `in_progress`, and finally `fixed` or `wontfix`.

5. Run the offline worker tests:

	```bash
	cd night-shift-worker-agent
	python -m pytest tests -q
	```

	The API contract suite needs Postgres and Redis, so run it in the container:

	```bash
	docker compose exec fastapi python -m pytest -q tests/test_api_contract.py
	```

	On Windows, use the project virtual environment if available:

	```powershell
	..\dummy-api-server\.venv\Scripts\python.exe -m pytest tests -q
	```

Live Groq, GitHub, and email integration tests are opt-in and are skipped by default. Enable them only when the required credentials and recipient configuration are present:

```bash
RUN_LIVE_INTEGRATION_TESTS=true python -m pytest tests/test_live_integrations.py -q
```

## Stop the Stack

```bash
docker compose --profile worker down
```

To remove named volumes as well, which deletes local PostgreSQL, Redis, and workspace data:

```bash
docker compose --profile worker down -v
```
