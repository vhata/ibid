# ibid — common development tasks. Run `make help` for an overview.
#
# Everything goes through .venv. The targets accept the venv being missing —
# `make sync` creates it. After that, you can either activate it
# (source .venv/bin/activate) or just keep using make.

VENV       ?= .venv
PYTHON     := $(VENV)/bin/python
PYTEST     := $(VENV)/bin/pytest
RUFF       := $(VENV)/bin/ruff
MYPY       := $(VENV)/bin/mypy
IBID       := $(VENV)/bin/ibid

# Path to a legacy mysqldump for the `import` target.
DUMP       ?= spinach-20151117-115729.sql
DB_URL     ?= sqlite+aiosqlite:///ibid.db

.PHONY: help venv sync test lint format format-check typecheck check \
        run import clean distclean docker-build

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make <target>\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  %-15s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

venv: $(PYTHON) ## Create the virtualenv (no-op if it exists)

$(PYTHON):
	uv venv --python 3.12 $(VENV)

sync: venv ## Install/refresh deps into the venv from pyproject.toml
	uv pip install --python $(PYTHON) -e '.[dev]'

test: sync ## Run pytest
	$(PYTEST)

lint: sync ## ruff check
	$(RUFF) check .

format: sync ## ruff format (writes)
	$(RUFF) format .

format-check: sync ## ruff format --check (read-only)
	$(RUFF) format --check .

typecheck: sync ## mypy --strict
	$(MYPY) src tests

check: lint format-check typecheck test ## Full pre-commit suite

run: sync ## Start the bot (reads ./ibid.toml)
	$(IBID) run

import: sync ## Import a legacy mysqldump (DUMP=path/to/file.sql)
	@test -f "$(DUMP)" || { echo "no dump at $(DUMP); set DUMP=..."; exit 2; }
	$(PYTHON) -m ibid.import_legacy "$(DUMP)" --db '$(DB_URL)'

clean: ## Remove caches and pyc files
	find . -type d \( -name __pycache__ -o -name .pytest_cache \
		-o -name .mypy_cache -o -name .ruff_cache \) \
		-not -path './$(VENV)/*' -not -path './legacy/*' -prune -exec rm -rf {} +
	rm -f .coverage coverage.xml
	rm -rf htmlcov build dist *.egg-info

distclean: clean ## Also remove the virtualenv and any local DB
	rm -rf $(VENV)
	rm -f ibid.db ibid.db-journal imported.db

docker-build: ## Build the production Docker image
	docker build -t ibid:latest .
