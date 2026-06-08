COMPOSE := docker compose -f docker/docker-compose.yml

# UTF-8 process floor for local test runs. Must prefix the command so the env
# is set before the interpreter starts — PYTHONUTF8 is read at init and has no
# effect if set afterwards. Mirrors docker/Dockerfile and the CI test jobs.
UTF8_ENV := PYTHONUTF8=1 PYTHONIOENCODING=utf-8

.PHONY: up down migrate logs ps clean rollback bootstrap \
        arch deps deadcode deps-graph check check-all lint-fix help \
        test-unit test-integration contract-check gen-schemas

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

# First-time setup — delegates to the cross-platform interactive wizard.
# Windows users without make run `uv run intellisource init` directly.
bootstrap:
	uv run intellisource init

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
	@echo "  gen-schemas       Regenerate config/schema/*.json from the config models"
	@echo "  lint-fix          ruff format + ruff check --fix"
	@echo "Tests:"
	@echo "  test-unit         Run unit tests only (no PG/Redis required)"
	@echo "  test-integration  Run integration tests (requires 'make up' first)"
	@echo "Docker:"
	@echo "  up / down / migrate / logs / ps / clean / rollback"
	@echo "Setup:"
	@echo "  bootstrap         First-time setup (= uv run intellisource init)"

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
	$(UTF8_ENV) uv run pytest tests/unit -q --tb=short -m "not slow" -n auto

test-integration:
	@if ! docker compose -f docker/docker-compose.yml ps --status=running --services 2>/dev/null | grep -q '^db$$'; then \
		echo "ERROR: db container not running. Run 'make up' first." >&2; \
		exit 1; \
	fi
	$(UTF8_ENV) \
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

# Regenerate config/schema/*.json from the config Pydantic models / constants.
gen-schemas:
	uv run python scripts/gen_config_schemas.py

lint-fix:
	uv run ruff format .
	uv run ruff check --fix .
