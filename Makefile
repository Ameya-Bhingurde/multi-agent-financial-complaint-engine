# ============================================================
# Multi-Agent Financial Complaint Governance Engine
# Makefile — Common Commands
# ============================================================
# Usage:
#   make up           Start all Docker services
#   make down         Stop all services
#   make logs         Tail all service logs
#   make ingest       Run CFPB data ingestion (500 complaints)
#   make ingest-full  Ingest all available Credit Card complaints
#   make eval         Run evaluation against CFPB outcomes
#   make calibrate    Run calibration job
#   make dashboard    Launch Streamlit dashboard locally
#   make shell-db     Open psql shell
#   make reset-db     Drop and recreate all tables (DANGER)

.PHONY: up down logs ingest ingest-full eval calibrate dashboard shell-db reset-db help

up:
	docker compose up -d
	@echo "✅ All services started"
	@echo "   n8n         → http://localhost:5678"
	@echo "   FastAPI     → http://localhost:8000/docs"
	@echo "   Qdrant      → http://localhost:6333/dashboard"
	@echo "   Dashboard   → run 'make dashboard'"

down:
	docker compose down
	@echo "✅ All services stopped"

logs:
	docker compose logs -f

ingest:
	@echo "📥 Starting CFPB ingestion (limit=500)..."
	python ingestion/run_ingestion.py --limit 500

ingest-full:
	@echo "📥 Starting full CFPB ingestion..."
	python ingestion/run_ingestion.py --limit 0

eval:
	@echo "📊 Running evaluation against CFPB outcomes..."
	python evaluation/evaluator.py

calibrate:
	@echo "🔧 Running calibration job..."
	python evaluation/calibrator.py

dashboard:
	@echo "🖥  Launching Streamlit dashboard..."
	streamlit run dashboard/app.py

shell-db:
	docker exec -it cfpb_postgres psql -U cfpb -d complaints_db

reset-db:
	@echo "⚠️  This will DROP all tables and recreate them."
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	docker exec -i cfpb_postgres psql -U cfpb -d complaints_db < db/init.sql
	@echo "✅ Database reset complete"

help:
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
