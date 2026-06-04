#!/bin/bash
set -e

echo "=== HERMES Pipeline ==="
source .venv/Scripts/activate

echo "[1/5] Seeding database..."
python assets/ingestion/seed_data.py

echo "[2/5] Running solver..."
python assets/optimization/run_solver.py

echo "[3/5] Generating events (30s)..."
timeout 30 python events/simulator/disruption_generator.py || true

echo "[4/5] Running agent pipeline..."
python assets/agents/run_agents.py

echo "[5/5] Generating map + dashboard..."
python optimization/generate_map.py
python dashboard/dashboard.py

echo "=== Done. Run 'python agents/run_telemetry.py' for live telemetry ==="
