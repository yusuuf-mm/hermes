# HERMES

**Hierarchical Execution & Routing for Multi-agent Enterprise Supply-chain**

An event-driven AI logistics operations platform that blends classical Operations Research with a multi-agent LLM decision layer. Built as a demonstration of production-grade AI Systems Engineering.

---

## What this system does

HERMES solves a real logistics problem — last-mile delivery in a metropolitan area — and keeps solving it continuously as conditions change.

Each morning, an OR-Tools solver generates an optimal vehicle route plan for the day (CVRPTW). As vehicles execute those routes, a live event stream captures disruptions: traffic, breakdowns, failed deliveries, new orders. A five-agent LangGraph pipeline monitors those events, classifies them, quantifies SLA risk, decides whether to re-optimise, and generates a plain-language dispatch brief for human operators.

The OR solver remains the authoritative decision engine. Agents provide operational intelligence around it, not instead of it.

---

## Architecture

```
Orders → CVRPTW Solver → Live Operations → Event Stream → Agent System → Decisions
                ↑                                               |
                └───────────── re-solve trigger ───────────────┘
```

| Layer | Technology | Role |
|---|---|---|
| Data ingestion | Bruin + DuckDB | Pull orders, build arc-cost matrix, enforce quality checks |
| Optimisation | OR-Tools CP-SAT | Solve CVRPTW — minimise total route cost subject to C1-C7 |
| Event streaming | Python simulator → DuckDB | Simulate GPS, traffic, failures, new orders |
| Agent orchestration | LangGraph + OpenRouter | Five-agent pipeline: monitor → classify → risk → reroute → dispatch |
| Dashboard | Evidence.dev | Live KPI tracking over DuckDB |

---

## Mathematical model (CVRPTW)

**Objective:** minimise total fleet travel cost

```
min  Σ_k  Σ_(i,j)∈A  c_ij · x_ijk
```

**Decision variables:**
- `x_ijk ∈ {0,1}` — 1 if vehicle k traverses arc (i→j)
- `t_ik` — arrival time of vehicle k at node i

**Constraints:**
- C1: all vehicles depart and return to depot
- C2: each customer visited exactly once
- C3: vehicle capacity not exceeded
- C4: service starts inside customer time window
- C5: temporal feasibility (no time travel between stops)
- C6: driver shift limit respected
- C7: flow conservation at every node

---

## Agent system

| Agent | Model | Responsibility |
|---|---|---|
| Monitoring | claude-haiku-4-5 | Detect anomalies in the event stream |
| Classification | claude-haiku-4-5 | Assign severity and category to each event |
| SLA Risk | claude-sonnet-4-6 | Quantify probability of time-window violations (0–1 score) |
| Rerouting | claude-sonnet-4-6 | Decide whether to trigger re-optimisation and what strategy |
| Dispatch | claude-sonnet-4-6 | Write the plain-language operations brief for human operators |

LLM calls routed through **OpenRouter** — swap models with a one-line change in `agents/llm_client.py`.

---

## Project structure

```
hermes/
├── Makefile                          # make seed | solve | events | agents
├── pyproject.toml                    # Python dependencies
├── config/
│   └── .env.example                  # Environment variable template
│
├── pipelines/
│   ├── ingestion/
│   │   ├── seed_data.py              # Generates Lagos metro seed data → DuckDB
│   │   └── seed_data.asset.yaml      # Bruin asset definition
│   ├── quality/
│   │   ├── check_orders_freshness.yaml
│   │   ├── check_demand_positive.yaml
│   │   └── check_time_windows_valid.yaml
│   └── transforms/
│       └── build_cvrptw_input.sql    # Clean view joining orders + nodes
│
├── optimization/
│   ├── cvrptw_solver.py              # OR-Tools CVRPTW model (C1-C7)
│   ├── solution_writer.py            # Persists solver output to DuckDB
│   ├── run_solver.py                 # Entry point (also Bruin asset)
│   ├── run_solver.asset.yaml
│   └── tests/
│       └── test_solution_feasibility.py  # Validates C1-C7 on every run
│
├── events/
│   └── simulator/
│       ├── event_schemas.py          # Pydantic models for all event types
│       └── disruption_generator.py   # Live event stream → DuckDB
│
├── agents/
│   ├── llm_client.py                 # OpenRouter client + model aliases
│   ├── state.py                      # LangGraph shared state schema
│   ├── monitoring_agent.py           # Agent 1: anomaly detection
│   ├── classification_agent.py       # Agent 2: severity + category
│   ├── sla_risk_agent.py             # Agent 3: risk quantification
│   ├── rerouting_agent.py            # Agent 4: re-solve decision
│   ├── dispatch_agent.py             # Agent 5: operator brief + DB write
│   ├── graph.py                      # LangGraph wiring + conditional edges
│   ├── run_agents.py                 # Entry point (also Bruin asset)
│   └── run_agents.asset.yaml
│
└── dashboard/
    ├── package.json                  # Evidence.dev dependency
    ├── evidence.config.json
    ├── sources/
    │   └── hermes_db.yaml            # DuckDB connection
    └── pages/
        ├── index.md                  # KPI overview
        ├── routes.md                 # Route stop sequences + timing
        ├── events.md                 # Event stream + agent output
        └── fleet.md                  # Vehicle utilisation
```

---

## Quickstart

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the dashboard)
- An [OpenRouter](https://openrouter.ai) API key

### Setup

```bash
# 1. Clone and install
git clone https://github.com/yourname/hermes
cd hermes
pip install -e ".[dev]"

# 2. Configure environment
cp config/.env.example .env
# Edit .env — add your OPENROUTER_API_KEY

# 3. Run the full pipeline
make seed       # seed DuckDB with Lagos metro data
make solve      # run CVRPTW solver
make events     # run event simulator (Ctrl+C after ~30 seconds)
make agents     # run five-agent LangGraph pipeline

# 4. Launch dashboard
cd dashboard
npm install
npm run dev     # opens at http://localhost:3000
```

### Individual commands

```bash
make test          # run constraint feasibility tests
make db-inspect    # show row counts for all tables
make lint          # ruff code quality check
make clean         # reset DuckDB and caches
```

---

## Database schema

| Table | Description |
|---|---|
| `nodes` | 26 nodes: 1 depot + 25 Lagos metro customers |
| `fleet` | 5 vehicles with capacity and shift limits |
| `arc_costs` | 650 directed arcs with distance and travel time |
| `daily_orders` | 30 daily orders with demand and date |
| `cvrptw_input` | Clean view joining orders to node attributes |
| `route_solutions` | Solver output: stop sequences + arrival/departure times |
| `solution_metadata` | KPIs per solver run: cost, vehicles used, solve time |
| `raw_events` | Live event stream: GPS, traffic, failures, new orders |
| `processed_events` | Agent-classified events with SLA risk score |

---

## Key design decisions

**Why OR-Tools over a pure LLM solution?**
Routing optimisation is an NP-hard combinatorial problem. LLMs cannot reliably solve it. OR-Tools finds provably near-optimal solutions in under 60 seconds. Agents provide operational context; the solver provides mathematically valid routes.

**Why LangGraph over CrewAI for orchestration?**
LangGraph gives explicit control over graph topology and state flow. The conditional edge after the Monitoring Agent (skipping 3 LLM calls when operations are nominal) is not possible in CrewAI's sequential model without hacks. Explicit is better than implicit.

**Why OpenRouter?**
Single endpoint, multiple models. Fast agents (Monitoring, Classification) use Haiku for cost efficiency. Reasoning agents (SLA Risk, Rerouting, Dispatch) use Sonnet for accuracy. Swapping any model is a one-line change.

**Why DuckDB as the integration layer?**
Every layer — Bruin, the solver, the agents, the dashboard — reads and writes from one DuckDB file. No message queues, no shared memory, no API contracts between layers. The database is the contract.

---

*Lagos metro scenario. 26 nodes. 5 vehicles. Continuous optimisation.*
