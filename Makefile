PYTHON ?= python3
HW4_PYTHON = .venv-hw4/bin/python

.PHONY: setup prepare check infra
setup:
	$(PYTHON) -m venv .venv-hw4
	$(HW4_PYTHON) -m pip install -r requirements.txt

prepare:
	$(PYTHON) scripts/prepare_romashka.py

check:
	$(PYTHON) scripts/check_preparation.py

infra:
	docker compose --profile build build sandbox
	docker compose up -d github-mcp
