PYTHON ?= python3.13
VENV ?= .venv

.PHONY: install pdfs test up run down deploy test-down

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -e ".[dev]"

pdfs:
	$(VENV)/bin/policy-kg generate-pdfs --out data/policies

test:
	$(VENV)/bin/pytest

up:
	docker compose up -d --build --wait

run: up

down:
	docker compose down

test-down:
	docker compose -f docker-compose.test.yml -p policykgtest down

deploy: up
