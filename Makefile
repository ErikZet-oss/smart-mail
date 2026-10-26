# Smart Mail — common commands (see README "Vývoj")
.PHONY: up down logs test lint fmt types check tokens web-dev api-dev

up:            ## start the whole stack (web http://localhost:8080)
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f --tail=100

tokens:        ## copy design tokens into the web app (never edit web/src/styles/tokens.css by hand)
	python design/build_tokens.py && cp design/tokens.css web/src/styles/tokens.css

test:
	uv run pytest -q
	cd bridge && uv run pytest -q
	cd web && npm test
lint:
	uv run ruff check . && uv run ruff format --check .
	cd bridge && uv run ruff check . && uv run ruff format --check .
	cd web && npm run lint && npm run format:check
fmt:
	uv run ruff format . && uv run ruff check --fix .
	cd bridge && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format
types:
	uv run mypy
	cd bridge && uv run mypy
	cd web && npm run typecheck
check: lint types test   ## everything CI runs except docker compose

api-dev:
	uv run uvicorn app.main:app --reload --port 8000
web-dev:
	cd web && npm run dev
