COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: up down migrate logs ps clean rollback

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
