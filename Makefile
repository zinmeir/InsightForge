.DEFAULT_GOAL := help
COMPOSE := docker compose

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from the example if it doesn't exist
	@test -f .env || (cp .env.example .env && echo "created .env - review the secrets before sharing this instance")

up: ## Build and start the stack (waits until healthy)
	$(COMPOSE) up -d --build --wait

demo: ## Start the stack plus the traffic simulator
	$(COMPOSE) --profile demo up -d --build --wait

down: ## Stop everything (keeps data)
	$(COMPOSE) --profile demo down

clean: ## Stop everything and delete Elasticsearch data
	$(COMPOSE) --profile demo down -v

logs: ## Tail container logs
	$(COMPOSE) logs -f --tail 100

smoke: ## Run the end-to-end smoke test against the running stack
	./scripts/smoke_test.sh

test: ## Backend unit + API tests
	cd backend && pytest

lint: ## Lint and type-check the backend
	cd backend && ruff check . && mypy app

fmt: ## Auto-format the backend
	cd backend && ruff check --fix . && ruff format .

dev-backend: ## Run the API locally with reload (needs Elasticsearch on :9200)
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the Vite dev server (proxies /api to :8000)
	cd frontend && npm install && npm run dev

.PHONY: help env up demo down clean logs smoke test lint fmt dev-backend dev-frontend
