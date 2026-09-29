# tg-relay — команды разработки и эксплуатации.

SHELL := /bin/sh
PYTHON ?= python
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help install env up down logs cli lint format typecheck test check bench clean

help: ## показать команды
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

install: ## поставить пакет и инструменты разработки
	$(PYTHON) -m pip install -e ".[dev]"

env: ## создать .env со случайными секретами и напечатать ключ
	@if [ -f .env ]; then echo ".env уже существует — не трогаю"; exit 0; fi; \
	KEY="$$($(PYTHON) -c 'import secrets; print("rl_live_" + secrets.token_urlsafe(24))')"; \
	PW="$$($(PYTHON) -c 'import secrets; print(secrets.token_hex(16))')"; \
	sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$PW|" \
	    -e "s|^BOOTSTRAP_KEY=.*|BOOTSTRAP_KEY=$$KEY|" .env.example > .env; \
	echo "Создан .env. Ключ первого проекта (сохраните): $$KEY"

up: ## поднять шлюз и PostgreSQL в Docker
	$(COMPOSE) up -d --build

down: ## остановить
	$(COMPOSE) down

logs: ## логи шлюза
	$(COMPOSE) logs -f gateway

cli: ## CLI в контейнере: make cli ARGS="list-projects"
	$(COMPOSE) exec gateway tg-relay $(ARGS)

lint: ## ruff: стиль и типичные ошибки
	ruff check src tests benchmarks
	ruff format --check src tests benchmarks

format: ## привести код к стилю
	ruff format src tests benchmarks
	ruff check --fix src tests benchmarks

typecheck: ## mypy в строгом режиме
	mypy

test: ## тесты (с TEST_DATABASE_URL — ещё и на PostgreSQL)
	pytest

check: lint typecheck test ## всё, что проверяет CI

bench: ## нагрузочный замер
	$(PYTHON) -m benchmarks.bench

clean: ## удалить контейнеры и данные
	$(COMPOSE) down -v
