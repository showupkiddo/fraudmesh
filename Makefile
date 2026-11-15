.PHONY: install test lint precommit mlflow-up

install:
	python -m pip install -e .[dev]

test:
	pytest -q

lint:
	ruff check .
	mypy src tests

precommit:
	pre-commit run --all-files

mlflow-up:
	docker compose up -d mlflow
