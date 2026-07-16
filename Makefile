PYTHON ?= python3

.PHONY: install install-dev dev docker-build docker-up docker-down check setup-git

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

install-dev: install
	$(PYTHON) -m pip install -r requirements-dev.txt

dev:
	$(PYTHON) -m uvicorn app.main:app --reload --host localhost --port 8000

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down

check:
	$(PYTHON) -m compileall app scripts

setup-git:
	git config commit.template .gitmessage
	git config core.hooksPath .githooks
	chmod +x .githooks/commit-msg .githooks/pre-commit .githooks/pre-push
	@printf '%s\n' "Git hooks configured via core.hooksPath=.githooks (skipping pre-commit installation)."
