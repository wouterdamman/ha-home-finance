VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: venv lint format test

venv:
	uv venv -p 3.14 $(VENV)
	uv pip install -p $(VENV) -r requirements-test.txt

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format:
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

test:
	$(PY) -m pytest
