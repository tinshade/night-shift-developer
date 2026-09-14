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

Create or update the root `.env` file:

```env
GROQ_API_KEY=your-groq-api-key
GROQ_FREE_MODEL=openai/gpt-oss-120b
GROQ_CODE_MODEL=openai/gpt-oss-120b
GROQ_OPERATIONS_MODEL=openai/gpt-oss-20b

# Optional GitHub integration
GITHUB_PERSONAL_ACCESS_TOKEN=your-github-token
GITHUB_OWNER=your-github-owner
GITHUB_REPOSITORY=your-github-repository

# Optional Gmail notifications
GOOGLE_EMAIL_ID=sender@gmail.com
GOOGLE_APP_PASSWORD=your-gmail-app-password
REPAIR_NOTIFICATION_EMAIL=recipient@example.com
```

The code model is used for diagnosis and patches. The operations model is used for optional GitHub PR and email drafting.

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
- `GET /users/{id}`
- `POST /users/create`

View logs:

```bash
docker compose logs -f fastapi
docker compose logs -f worker
```

## Trigger a Test Error

The error generator can trigger a real application error manually:

```bash
docker compose exec error-generator python force-error.py --mode delete
docker compose exec error-generator python force-error.py --mode post
```

Both scenarios attempt to delete a nonexistent user, causing the API to write an `ERROR` record to Redis. The worker consumes the error stream and attempts isolated validation and repair.

The cron container also runs the generator automatically according to `mess-maker/crontab`.

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
	docker compose exec error-generator python force-error.py --mode delete
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
