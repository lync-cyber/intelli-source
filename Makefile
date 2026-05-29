COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: up down migrate logs ps clean rollback bootstrap \
        arch deps deadcode deps-graph check check-all lint-fix help \
        test-unit test-integration contract-check

# ---------------------------------------------------------------------------
# Docker dev stack
# ---------------------------------------------------------------------------
up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) run --rm migrate

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

clean:
	$(COMPOSE) down -v

rollback:
	$(COMPOSE) run --rm api python -m alembic downgrade -1

# First-time setup: copy env template + create sources / subscriptions dirs
bootstrap:
	@[ -f docker/.env ] || (cp docker/.env.example docker/.env && echo "Created docker/.env — edit IS_API_KEY and LLM keys before starting")
	@mkdir -p config/sources config/subscriptions
	@[ -f config/sources/sources.yaml ] || (cp config/sources.example.yaml config/sources/sources.yaml && echo "Created config/sources/sources.yaml — edit to add your RSS sources")
	@[ -f config/subscriptions/subscriptions.yaml ] || (cp config/subscriptions.example.yaml config/subscriptions/subscriptions.yaml && echo "Created config/subscriptions/subscriptions.yaml — edit to add your push subscriptions")
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit docker/.env  (set IS_API_KEY + LLM provider key)"
	@echo "  2. Edit config/sources/sources.yaml  (add your RSS / API sources)"
	@echo "  3. Edit config/subscriptions/subscriptions.yaml  (configure push channels)"
	@echo "  4. make up"
	@echo "  5. uv run intellisource doctor  (verify configuration)"
	@echo "  6. curl -X POST -H \"X-API-Key: \$$IS_API_KEY\" http://localhost:8000/api/v1/subscriptions/reload"

# ---------------------------------------------------------------------------
# Architecture & quality gates
# Run a single target:    make <target>
# Run the full local pass: make check
# ---------------------------------------------------------------------------
help:
	@echo "Architecture / quality:"
	@echo "  arch              Run import-linter (architecture contracts)"
	@echo "  deps              Run deptry (dependency hygiene)"
	@echo "  deadcode          Run vulture (dead code)"
	@echo "  deps-graph        Generate dependency SVG via pydeps (needs graphviz 'dot')"
	@echo "  check             arch + deps + deadcode + ruff + mypy + unit tests"
	@echo "  check-all         check + integration tests (needs 'make up' first)"
	@echo "  contract-check    Suggest which test categories to run based on diff vs main"
	@echo "  lint-fix          ruff format + ruff check --fix"
	@echo "Tests:"
	@echo "  test-unit         Run unit tests only (no PG/Redis required)"
	@echo "  test-integration  Run integration tests (requires 'make up' first)"
	@echo "Docker:"
	@echo "  up / down / migrate / logs / ps / clean / rollback"
	@echo "Setup:"
	@echo "  bootstrap         First-time setup: copy .env + create sources dir"

arch:
	uv run lint-imports --no-cache

deps:
	uv run deptry src

deadcode:
	uv run vulture

deps-graph:
	uv run pydeps src/intellisource \
		--max-bacon=2 --cluster --noshow \
		-o docs/arch/deps-graph.svg

check: arch deps deadcode test-unit
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy --strict src/

# check-all extends `check` with integration tests. Run `make up` first so the
# PG / Redis containers are healthy; the integration suite uses real PG via the
# pg_container fixture and will fail without a running stack.
check-all: check test-integration

test-unit:
	uv run pytest tests/unit -q --tb=short -m "not slow" -n auto

test-integration:
	@if ! docker compose -f docker/docker-compose.yml ps --status=running --services 2>/dev/null | grep -q '^db$$'; then \
		echo "ERROR: db container not running. Run 'make up' first." >&2; \
		exit 1; \
	fi
	DATABASE_URL="postgresql+asyncpg://intellisource:intellisource@localhost:5432/intellisource" \
		uv run pytest tests/integration -q --tb=short

# contract-check looks at staged + unstaged diff vs main and prints which test
# categories should be run. Triggers on changes to files that historically
# break integration tests when modified without local PG verification:
#   - src/intellisource/api/routers/   (response_model / signature changes)
#   - src/intellisource/search/        (SearchResponse / EnrichedSearchResult schema)
#   - src/intellisource/storage/       (dataclass fields / SQL column lists)
#   - src/intellisource/llm/gateway/   (model resolution / streaming paths)
contract-check:
	@uv run python scripts/contract_check.py

lint-fix:
	uv run ruff format .
	uv run ruff check --fix .
