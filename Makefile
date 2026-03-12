CONDA_ENV_NAME = proj_con_3.12
PYTHON = python

.PHONY: build-env install fmt lint unit integration test cov

build-env:
	conda create -n $(CONDA_ENV_NAME) python=3.12 -y

install:
	uv pip install -r requirements.txt -r requirements-dev.txt

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
