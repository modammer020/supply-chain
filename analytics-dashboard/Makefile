# AEGIS Analytics — demo-controls
# Gebruik: make start | stop | demo | engineer | pdf VEHICLE=TRK-104
SHELL := /bin/bash
VENV := .venv/bin/python

.PHONY: start stop ps demo logs engineer pdf

start: ## Bouw + start platform
	podman compose up -d --build

stop: ## Stop platform (command center blijft draaien)
	podman compose down

ps: ## Status
	podman compose ps

demo: ## Toon demo-URL's
	@echo "═══ AEGIS ANALYTICS ═════════════════════════════"
	@echo "  Dashboard (4 tabs) : http://localhost:8402"
	@echo "  API (docs)         : http://localhost:8401/docs"
	@echo "  Kafka UI           : http://localhost:8040"
	@echo "  MinIO console      : http://localhost:9001  (minioadmin / Password123!)"
	@echo "  Trino UI           : http://localhost:8543"
	@echo "  Grafana            : http://localhost:3000  (admin / Password123!)"
	@echo "  Jupyter            : http://localhost:8888  (Password123!)"
	@echo "  Adminer            : http://localhost:8081"
	@echo "═════════════════════════════════════════════════"

engineer: ## Draai data-engineer agent één keer (inbox → JSON)
	$(VENV) agents/data_engineer.py --once

pdf: ## Genereer voertuig-PDF (make pdf VEHICLE=TRK-104)
	@test -n "$(VEHICLE)" || (echo "gebruik: make pdf VEHICLE=TRK-104" && exit 1)
	curl -s localhost:8401/api/vehicle/$(VEHICLE)/dossier.pdf -o dossier-$(VEHICLE).pdf
	@echo "→ dossier-$(VEHICLE).pdf"

logs: ## Logs per service (make logs SVC=dashboard)
	@test -n "$(SVC)" || (echo "gebruik: make logs SVC=dashboard" && exit 1)
	podman logs --tail 40 aegis_analytics_$(SVC)
