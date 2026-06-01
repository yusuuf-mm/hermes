# HERMES

**Hierarchical Execution & Routing for Multi-agent Enterprise Supply-chain**

An event-driven logistics operations platform that pairs classical Operations Research with a multi-agent LLM decision layer. Built to demonstrate how mathematical optimisation and AI agents solve real problems together — not as replacements for each other.

---

## The Problem

Last-mile delivery in Lagos is chaotic. Traffic changes by the hour. Vehicles break down. Customers miss delivery windows. New orders arrive mid-route. A static morning plan is obsolete by noon.

Traditional fleet management tools generate an optimised route plan once and hand it to drivers. When conditions change, a human dispatcher has to manually re-route vehicles — a process that takes 15-30 minutes and produces suboptimal results because humans cannot mentally solve a 26-node routing problem with time windows and capacity constraints under pressure.

The question: can we build a system that detects disruptions in real time, quantifies their operational impact, and automatically re-optimises routes — while keeping a human in the loop for high-stakes decisions?

---

## The Solution

HERMES solves this in three layers:

**Layer 1 — Mathematical Optimisation (OR-Tools)**
An OR-Tools Routing Library solver generates a Capacitated Vehicle Routing Problem with Time Windows (CVRPTW) solution. It assigns 30 orders across 5 vehicles, respecting capacity limits, customer time windows, driver shift limits, and depot return constraints. The solver runs in under 2 seconds for 26 nodes.

**Layer 2 — Multi-Agent Intelligence (LangGraph)**
A five-agent LangGraph pipeline monitors a live event stream. When disruptions occur — traffic congestion, vehicle breakdowns, failed deliveries, priority orders — the agents classify severity, quantify SLA breach probability, and decide whether to trigger a re-solve. Agents never touch the routing math. They decide *when* the solver should run and *what constraints* to relax.

**Layer 3 — Data Engineering & Presentation (Bruin + Evidence.dev)**
A Bruin orchestration pipeline manages the data lifecycle: ingest, quality checks, transforms, and execution. An Evidence.dev dashboard presents live KPIs, route maps, fleet utilisation, and event timelines to human operators.

```
Morning Plan                    Live Operations
┌─────────┐    ┌──────────┐    ┌──────────────┐    ┌─────────────┐
│  Orders  │───▶│  Solver   │───▶│ Event Stream  │───▶│  5 Agents   │
└─────────┘    │ (OR-Tools) │    └──────────────┘    └──────┬──────┘
               └──────────┘           ▲                     │
                    ▲                 │              re-solve trigger
                    └─────────────────┘                     │
                    OR-Tools re-optimisation ◀──────────────┘
```

---

## Mathematical Model

**Objective:** minimise total fleet travel distance

```
min  Σ_k  Σ_(i,j)∈A  c_ij · x_ijk
```

**Decision variables:**
- `x_ijk ∈ {0,1}` — 1 if vehicle k traverses arc (i→j)
- `t_ik` — arrival time of vehicle k at node i

**Constraints:**

| ID | Constraint | Description |
|----|-----------|-------------|
| C1 | Depot return | All vehicles depart from and return to the depot |
| C2 | Visit-once | Each customer node is visited exactly once |
| C3 | Capacity | Total demand on a route must not exceed vehicle capacity (100 units) |
| C4 | Time windows | Service must begin within [tw_open, tw_close] at each node |
| C5 | Temporal feasibility | Travel time between consecutive stops must be respected |
| C6 | Shift limits | Total route duration must not exceed 480 minutes (8 hours) |
| C7 | Flow conservation | Vehicles entering a node must also leave it |

**Solver configuration:**
- First solution: PATH_CHEAPEST_ARC heuristic
- Metaheuristic: GUIDED_LOCAL_SEARCH with 60-second time limit
- Distance matrix: haversine × 1.35 road factor, 25 km/h average Lagos speed
- Time windows: minutes from midnight (e.g., 480 = 8:00 AM, 1020 = 5:00 PM)

---

## Agent System

Five agents, each with a specific role in the decision chain:

| # | Agent | Model | Provider | Role |
|---|-------|-------|----------|------|
| 1 | Monitoring | Llama 3.1 8B Instant | Groq | Scans raw events, determines if anomalies exist. Telemetry alone is not an anomaly — only fuel < 15% or engine off triggers the full chain. |
| 2 | Classification | Llama 3.1 8B Instant | Groq | Enriches each event with severity (low/medium/high/critical) and category (operational/safety/sla_risk/capacity/new_demand). |
| 3 | SLA Risk | Llama 3.3 70B Versatile | Groq | Quantifies probability of time-window violations on a 0.0–1.0 scale. Identifies at-risk nodes and vehicles. |
| 4 | Rerouting | Xiaomi Mimo v2.5 Pro | GitLawb | Decides whether to trigger a re-solve. Returns strategy (full_replan/partial_replan/vehicle_swap/hold), urgency, and whether human approval is required. |
| 5 | Dispatch | Llama 3.3 70B Versatile | Groq | Generates a plain-language operations brief: SITUATION / SLA RISK / RECOMMENDATION / ACTIONS / STATUS. Writes classified events to processed_events. |

**Graph topology:**
```
monitoring ──▶ [anomalies?] ──yes──▶ classification ──▶ sla_risk ──▶ rerouting ──▶ dispatch ──▶ END
                        │
                        └──no──▶ dispatch (skips 3 LLM calls when nominal)
```

The conditional edge after Monitoring is the key efficiency gain. When the event stream is nominal (routine telemetry, minor deviations), the pipeline skips Classification, SLA Risk, and Rerouting — saving three LLM calls and ~10 seconds per tick.

**LLM provider architecture:**
- Groq (Agents 1, 2, 3, 5): fast inference on Llama models for classification and reporting tasks
- GitLawb Opengateway (Agent 4): Xiaomi Mimo for the rerouting decision, which requires deeper reasoning about constraint tradeoffs
- OpenAI-compatible SDK for both providers — swap any model with a one-line change in `agents/llm_client.py`
- Retry logic: 4 attempts with exponential backoff (5s, 10s, 20s) on rate-limit errors

---

## Event System

Six event types model real-world logistics disruptions:

| Event Type | Probability | Key Fields | Impact |
|-----------|-------------|------------|--------|
| `vehicle_telemetry` | 40% | lat, lon, speed_kmh, fuel_pct, engine_status | Low — informational unless fuel < 15% or engine off |
| `traffic_disruption` | 25% | affected_from/to_node, congestion_factor, cause | Medium — increases travel time on affected arcs |
| `route_deviation` | 15% | planned_node_id, deviation_km, time_lost_min | Medium — vehicle off planned route |
| `failed_delivery` | 12% | node_id, order_id, reason, attempt_count | High — customer not served, may breach SLA |
| `live_order` | 5% | node_id, demand_units, priority, latest_delivery_time | High — new demand may exceed capacity |
| `vehicle_breakdown` | 3% | breakdown_type, estimated_repair_min | Critical — vehicle offline, routes must be redistributed |

Events are generated by a probabilistic simulator and written to DuckDB. The agent pipeline reads unprocessed events via an anti-join pattern (`LEFT JOIN ... WHERE p.event_id IS NULL`) to prevent reprocessing.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Optimisation | Google OR-Tools (Routing Library) | CVRPTW solver with 7 constraints |
| Database | DuckDB | Single integration layer — all components read/write here |
| Agent orchestration | LangGraph | State machine with conditional edges, not a sequential chain |
| LLM inference | Groq + GitLawb | Dual-provider routing for cost/speed/quality tradeoffs |
| Data pipelines | Bruin | DAG orchestration with embedded quality checks |
| Dashboard | Evidence.dev | SQL-driven markdown pages with charts and tables |
| Route visualisation | Folium | Interactive OpenStreetMap with scenario toggle |
| Terminal UI | Rich | Three-panel control room for live agent telemetry |
| Schemas | Pydantic v2 | Typed event models with validation |

**Why these choices:**

- **OR-Tools over LLM routing:** CVRPTW is NP-hard. LLMs cannot reliably solve it. OR-Tools finds provably near-optimal solutions in seconds.
- **LangGraph over CrewAI:** Explicit graph topology with conditional edges. The "skip 3 agents when nominal" pattern is a conditional edge, not a sequential pipeline.
- **DuckDB over PostgreSQL:** Zero infrastructure. Every layer — Bruin, solver, agents, dashboard — reads and writes one file. The database is the API contract.
- **Dual LLM provider:** Fast/cheap models (Llama 8B) for classification tasks. Reasoning models (Mimo, Llama 70B) for decisions. One SDK, two providers.

---

## Project Structure

```
hermes/
├── agents/                              # Multi-agent system
│   ├── graph.py                         # LangGraph topology + conditional edges
│   ├── state.py                         # HermesState TypedDict (shared state)
│   ├── monitoring_agent.py              # Agent 1: anomaly detection
│   ├── classification_agent.py          # Agent 2: severity + category
│   ├── sla_risk_agent.py                # Agent 3: SLA breach quantification
│   ├── rerouting_agent.py               # Agent 4: re-solve decision
│   ├── dispatch_agent.py                # Agent 5: operator brief + DB write
│   ├── llm_client.py                    # Groq + GitLawb routing
│   ├── telemetry.py                     # Agent execution logging
│   ├── db_lock.py                       # Shared threading lock for DuckDB
│   └── run_telemetry.py                 # Rich control room daemon
│
├── optimization/                        # OR-Tools solver
│   ├── cvrptw_solver.py                 # CVRPTW model (C1-C7)
│   ├── solution_writer.py               # Persists solver output to DuckDB
│   ├── generate_map.py                  # Folium route map generator
│   └── tests/
│       └── test_solution_feasibility.py
│
├── events/                              # Event simulation
│   └── simulator/
│       ├── event_schemas.py             # Pydantic models (6 event types)
│       └── disruption_generator.py      # Probabilistic event stream
│
├── assets/                              # Bruin pipeline assets
│   ├── ingestion/seed_data.py           # Lagos metro data (26 nodes, 5 vehicles)
│   ├── quality/                         # 3 QA checks (time windows, demand, freshness)
│   ├── transforms/build_cvrptw_input.sql
│   ├── optimization/run_solver.py       # Solver entry point (Bruin asset)
│   └── agents/run_agents.py             # Agent pipeline entry point (Bruin asset)
│
├── dashboard/                           # Evidence.dev
│   ├── pages/
│   │   ├── index.md                     # KPI overview
│   │   ├── routes.md                    # Route stop sequences + timing
│   │   ├── routes_map.md                # Folium map (iframe)
│   │   ├── events.md                    # Event stream + agent output
│   │   └── fleet.md                     # Vehicle utilisation
│   └── sources/hermes_db/               # 8 SQL source definitions
│
├── pipeline.yaml                        # Bruin pipeline config
├── Makefile                             # make seed | solve | agents | watch | map
└── pyproject.toml                       # Python dependencies
```

---

## Quickstart

### Prerequisites

- Python 3.11+
- Node.js v22 LTS (Node v24 breaks DuckDB + Vite bindings)
- A [Groq](https://console.groq.com) API key
- A [GitLawb](https://opengateway.gitlawb.com) API key

### Setup

```bash
# 1. Clone and install
git clone https://github.com/yusuuf-mm/hermes
cd hermes
pip install -e ".[dev]"

# 2. Configure environment
cp config/.env.example .env
# Edit .env — add GROQ_API_KEY and GITLAWB_API_KEY

# 3. Seed and solve
python assets/ingestion/seed_data.py
python assets/optimization/run_solver.py

# 4. Generate events and run agents
python -c "from events.simulator.disruption_generator import generate_batch; generate_batch(10)"
python assets/agents/run_agents.py

# 5. Generate route map
python optimization/generate_map.py

# 6. Launch dashboard
cd dashboard
npm install
npx evidence sources
npm run dev     # opens at http://localhost:3000
```

### With Bruin (orchestrated pipeline)

```bash
bruin run .     # runs: seed → QA checks → transform → solve → agents
```

### Telemetry control room (live demo)

```bash
python agents/run_telemetry.py
```

Rich terminal UI with three panels: agent reasoning log, fleet metrics, and system status. Generates events and processes them in a continuous loop. Record this as a GIF for the README.

> **Note:** Do not run `make solve` in another terminal while the telemetry daemon is running. The daemon manages the solver internally when re-solves are triggered.

---

## Database Schema

| Table | Rows | Description |
|-------|------|-------------|
| `nodes` | 26 | 1 depot (Lagos Island) + 25 customer locations across Lagos metro |
| `fleet` | 5 | Vehicles VH-001 through VH-005, 100-unit capacity, 8-hour shift limit |
| `arc_costs` | 650 | 26×25 directed arcs with haversine distance × 1.35 road factor |
| `daily_orders` | 30 | Pending orders with demand, assigned to customer nodes |
| `cvrptw_input` | 19 | Materialised view joining orders with node attributes |
| `route_solutions` | ~24 | Solver output: vehicle, stop sequence, arrival/departure times |
| `solution_metadata` | 1+ | Per-run KPIs: cost, vehicles used, solve time, scenario tag |
| `raw_events` | N | Live event stream from simulator |
| `processed_events` | N | Agent-classified events with severity, category, SLA risk score |
| `agent_logs` | N | Per-agent execution log: timing, input/output summary, decision |

---

## Error Handling

**LLM resilience:**
- 4-attempt retry with exponential backoff (5s, 10s, 20s) on 429 rate-limit errors
- Provider isolation: Groq and GitLawb failures are independent — one provider down doesn't take out all agents
- Graceful degradation: if the Rerouting agent fails, the pipeline defaults to "hold" strategy (no re-solve)

**Solver validation:**
- Post-solve capacity check: counts actual demand per vehicle and flags violations
- Infeasible solutions return `status=INFEASIBLE` with `constraint_violations=1` — the pipeline does not write broken routes to DuckDB

**Data integrity:**
- Anti-join pattern (`LEFT JOIN ... WHERE p.event_id IS NULL`) prevents event reprocessing
- `INSERT OR IGNORE` on processed_events prevents duplicate writes
- Shared `db_lock` threading lock serialises all DuckDB access when the telemetry daemon is running

**DuckDB concurrency:**
- Windows: single-process file lock — only one Python process can open the DB at a time
- The telemetry daemon and Evidence dashboard cannot run simultaneously on Windows
- Solution: batch pipeline workflow for demos, telemetry UI recorded separately as video

---

## Challenges & Lessons

**OR-Tools metaheuristic can violate constraints.**
GUIDED_LOCAL_SEARCH optimises for the objective function and may slightly violate capacity constraints (e.g., 101 units on a 100-capacity vehicle). Fixed by adding post-solve validation that counts actual demand per vehicle and flags violations. The solver now reports `constraint_violations > 0` when this happens.

**DuckDB single-writer lock on Windows.**
Unlike PostgreSQL, DuckDB uses file-level locking. Two processes cannot have the DB open simultaneously. This affected the telemetry daemon + Evidence dashboard architecture. Resolved by designing the batch pipeline as the primary workflow and recording the telemetry UI as a video for the README.

**Mixed connection modes fail cross-process.**
DuckDB does not allow mixing read-write and read-only connections to the same file from different processes. A read-write connection from the telemetry daemon blocks a read-only connection from Evidence. Resolved by ensuring all connections use the same mode within a process.

**LangGraph conditional edges save LLM calls.**
The biggest performance gain was the conditional edge after Monitoring: when no anomalies are detected, skip Classification, SLA Risk, and Rerouting entirely. This saves 3 LLM calls (~10 seconds) per nominal tick — the majority of ticks in steady state.

**Agent roles must be separated from solver logic.**
Early iterations considered having the Rerouting agent directly modify routes. This was rejected — agents decide *when* to re-solve and *what constraints to relax*, but the OR-Tools solver is the only component that touches routing math. This separation of concerns is the core architectural principle.

---

## Portfolio Context

HERMES demonstrates three competencies that are rarely combined in a single project:

1. **Operations Research** — CVRPTW formulation with 7 constraints, OR-Tools solver, capacity validation
2. **Multi-Agent AI** — LangGraph state machine with conditional edges, dual-provider LLM routing, structured decision chain
3. **Data Engineering** — Bruin orchestration, DuckDB integration layer, quality checks, Evidence.dev dashboard

The system is designed so that each layer can be discussed independently with a technical interviewer, or as a cohesive whole with a hiring manager.

---

*Lagos metro scenario. 26 nodes. 5 vehicles. 6 event types. 5 agents. Continuous optimisation.*
