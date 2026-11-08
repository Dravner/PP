PYTHON ?= python3
HW4_PYTHON = .venv-hw4/bin/python
ARGS ?= --mode dry --team команда

.PHONY: setup prepare check infra run
setup: .venv-hw4/.installed

.venv-hw4/.installed: requirements.txt
	$(PYTHON) -m venv .venv-hw4
	$(HW4_PYTHON) -m pip install -r requirements.txt
	@touch $@

prepare:
	$(PYTHON) scripts/prepare_romashka.py

check:
	$(PYTHON) scripts/check_preparation.py

infra:
	docker compose --profile build build sandbox
	docker compose up -d github-mcp

run: setup infra
	$(HW4_PYTHON) duty.py $(ARGS)
