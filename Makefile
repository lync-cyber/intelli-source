COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: up down migrate logs ps clean rollback \
        arch deps deadcode deps-graph check lint-fix help

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

# ---------------------------------------------------------------------------
# Architecture & quality gates
# Run a single target:    make <target>
# Run the full local pass: make check
# ---------------------------------------------------------------------------
help:
	@echo "Architecture / quality:"
	@echo "  arch        Run import-linter (architecture contracts)"
	@echo "  deps        Run deptry (dependency hygiene)"
	@echo "  deadcode    Run vulture (dead code)"
	@echo "  deps-graph  Generate dependency SVG via pydeps (needs graphviz 'dot')"
	@echo "  check       arch + deps + deadcode + ruff + mypy + pytest"
	@echo "  lint-fix    ruff format + ruff check --fix"
	@echo "Docker:"
	@echo "  up / down / migrate / logs / ps / clean / rollback"

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

check: arch deps deadcode
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy --strict src/
	uv run pytest -q --tb=short -m "not slow"

lint-fix:
	uv run ruff format .
	uv run ruff check --fix .
