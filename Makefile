.PHONY: help init-secrets up down build logs ps restart clean migrate seed ingest test eval eval-quick replay go-build go-run py-install py-run login

# Default goal
.DEFAULT_GOAL := help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

init-secrets: ## Generate JWT_SECRET + API_KEY and write them into .env
	@test -f .env || cp .env.example .env
	@JWT=$$(openssl rand -hex 32); \
	 KEY=$$(openssl rand -hex 24); \
	 if grep -q '^JWT_SECRET=' .env; then \
	    sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=$$JWT|" .env; \
	 else echo "JWT_SECRET=$$JWT" >> .env; fi; \
	 if grep -q '^API_KEY=' .env; then \
	    sed -i.bak "s|^API_KEY=.*|API_KEY=$$KEY|" .env; \
	 else echo "API_KEY=$$KEY" >> .env; fi; \
	 rm -f .env.bak; \
	 echo "Wrote JWT_SECRET (32 bytes hex) and API_KEY (24 bytes hex) to .env"

login: ## Log in as alice and print the JWT (requires running stack)
	@curl -s -X POST http://localhost:8080/auth/login \
	  -H 'Content-Type: application/json' \
	  -d '{"email":"alice@example.com","password":"alice-pass-2026"}'

# =============================================================================
# Docker Compose
# =============================================================================
up: ## Start the full stack (postgres, kafka, agents, observability)
	docker compose --env-file .env up -d --build

up-infra: ## Start only infrastructure (postgres, kafka, otel, prometheus, grafana)
	docker compose --env-file .env up -d postgres kafka otel-collector prometheus grafana

down: ## Stop and remove all containers
	docker compose down

down-clean: ## Stop containers and remove volumes (DESTRUCTIVE)
	docker compose down -v

build: ## Rebuild all service images
	docker compose build

logs: ## Tail logs from all services
	docker compose logs -f --tail=100

ps: ## Show container status
	docker compose ps

restart: ## Restart application services
	docker compose restart go-server python-agent shopify-mock stripe-mock

# =============================================================================
# Database
# =============================================================================
migrate: ## Apply database migrations
	docker compose exec -T postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB < db/migrations/001_init.sql
	docker compose exec -T postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB < db/migrations/002_pgvector.sql

seed: ## Load sample orders, users, returns
	docker compose exec -T postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB < db/seed/seed.sql

ingest: ## Ingest policy/FAQ documents into pgVector
	docker compose run --rm python-agent python -m db.ingest

# =============================================================================
# Local development (without docker)
# =============================================================================
go-build: ## Compile Go server binary
	cd go-server && go build -o bin/server ./cmd/server

go-run: ## Run Go server locally
	cd go-server && go run ./cmd/server

py-install: ## Install Python dependencies
	cd python-agent && pip install -r requirements.txt

py-run: ## Run Python agent service locally
	cd python-agent && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# =============================================================================
# Evaluation
# =============================================================================
eval: ## Run full evaluation harness against running stack
	docker compose run --rm python-agent python -m evaluation.runner --dataset all

eval-quick: ## Quick smoke eval (5 queries per category)
	docker compose run --rm python-agent python -m evaluation.runner --dataset all --limit 5

replay: ## Replay a stored conversation (usage: make replay SESSION=<session_id>)
	docker compose run --rm python-agent python -m evaluation.replay --session-id $(SESSION)

# =============================================================================
# Tests
# =============================================================================
test: test-go test-py ## Run all tests

test-go: ## Run Go unit tests
	cd go-server && go test ./...

test-py: ## Run Python unit tests
	cd python-agent && pytest -q

# =============================================================================
# Cleanup
# =============================================================================
clean: ## Remove build artifacts
	rm -rf go-server/bin python-agent/.pytest_cache python-agent/__pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} +
