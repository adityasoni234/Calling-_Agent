# Everything in this stack is one `make` target away.
COMPOSE := docker compose

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create .env from the template with a generated SECRET_KEY
	@test -f .env && echo ".env already exists; leaving it alone" && exit 0 || true
	@python3 -c "import secrets,re,pathlib; \
t=pathlib.Path('.env.example').read_text(); \
pathlib.Path('.env').write_text(re.sub(r'^SECRET_KEY=.*$$','SECRET_KEY='+secrets.token_urlsafe(48),t,flags=re.M))"
	@echo "Wrote .env - review it, then run: make up"

.PHONY: up
up: ## Build and start the whole stack
	$(COMPOSE) up -d --build
	@echo "Dashboard  http://localhost:5173"
	@echo "API docs   http://localhost:8000/docs"

.PHONY: down
down: ## Stop the stack (keeps data)
	$(COMPOSE) down

.PHONY: reset
reset: ## Stop the stack and delete all data volumes
	$(COMPOSE) down -v

.PHONY: ps
ps: ## Show container status
	$(COMPOSE) ps

.PHONY: logs
logs: ## Tail logs from every service
	$(COMPOSE) logs -f

.PHONY: logs-api
logs-api: ## Tail backend logs only
	$(COMPOSE) logs -f backend

.PHONY: shell
shell: ## Open a shell in the backend container
	$(COMPOSE) exec backend bash

.PHONY: psql
psql: ## Open psql against the application database
	$(COMPOSE) exec postgres psql -U postgres -d calling_agent

.PHONY: migrate
migrate: ## Apply database migrations
	$(COMPOSE) exec backend alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="add agents"
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Create the first account: make seed email=you@co.com pass='...' name='You' org='Co'
	$(COMPOSE) exec backend python -m scripts.seed \
		--email "$(email)" --password "$(pass)" --name "$(name)" --org "$(org)"

.PHONY: test
test: ## Run the backend test suite
	cd backend && .venv/bin/python -m pytest -q

.PHONY: lint
lint: ## Lint and type-check both sides
	cd backend && .venv/bin/python -m ruff check app tests && .venv/bin/python -m ruff format --check app tests
	cd frontend && npm run lint && npm run typecheck

.PHONY: build-web
build-web: ## Production build of the dashboard
	cd frontend && npm run build

.PHONY: dev-backend
dev-backend: ## Run the API on the host (needs postgres+redis up)
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

.PHONY: dev-frontend
dev-frontend: ## Run the dashboard on the host
	cd frontend && npm run dev
