.PHONY: install seed solve events agents test lint clean

# ── Setup ────────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Pipeline steps (run in order) ────────────────────────────────────────────
seed:
	@echo "Seeding HERMES database..."
	python assets/ingestion/seed_data.py

solve:
	@echo "Running CVRPTW solver..."
	python assets/optimization/run_solver.py

events:
	@echo "Starting event simulator (Ctrl+C to stop)..."
	python events/simulator/disruption_generator.py

agents:
	@echo "Running agent system..."
	python assets/agents/run_agents.py

# ── Full pipeline (seed → quality checks → solve → agents) ───────────────────
run:
	$(MAKE) seed
	$(MAKE) solve

# ── Bruin DAG execution ──────────────────────────────────────────────────────
bruin-run:
	bruin run .

bruin-validate:
	bruin validate .

# ── Testing ──────────────────────────────────────────────────────────────────
test:
	pytest optimization/tests/ agents/tests/ -v

test-solver:
	pytest optimization/tests/test_solution_feasibility.py -v

# ── Code quality ─────────────────────────────────────────────────────────────
lint:
	ruff check . --fix

# ── Utilities ────────────────────────────────────────────────────────────────
db-inspect:
	@python -c "\
import duckdb; \
con = duckdb.connect('hermes.duckdb'); \
tables = con.execute(\"SHOW TABLES\").fetchall(); \
[print(f'  {t[0]:30s} {con.execute(f\"SELECT COUNT(*) FROM {t[0]}\").fetchone()[0]:>6} rows') for t in tables]; \
con.close()"

clean:
	rm -f hermes.duckdb
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
