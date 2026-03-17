CONDA_ENV_NAME = proj_con_3.12
PYTHON = python

.PHONY: build-env install format fmt lint unit integration test cov ci dev

build-env:
	conda create -n $(CONDA_ENV_NAME) python=3.12 -y

install:
	pip install uv
	uv pip install --system -r requirements.txt -r requirements-dev.txt

format:
	isort app/ tests/
	black app/ tests/

lint:
	flake8 app/ tests/
	isort --check-only app/ tests/
	black --check app/ tests/

unit:
	pytest tests/unit/ -v

integration:
	pytest tests/integration/ -v

test: unit integration

cov:
	pytest tests/ --cov=app --cov-report=term-missing

ci: install lint test

dev:
	alembic upgrade head && uvicorn app.main:app --reload
