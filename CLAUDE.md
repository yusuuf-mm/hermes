# HERMES Project Context & Constraints

## Technical Stack
- **Orchestration:** Bruin (Data pipelines and QA checks)
- **Database:** DuckDB (Local file: `hermes.duckdb`)
- **Core Engine:** Python 3.11+ with Google OR-Tools (CP-SAT)
- **Multi-Agent Layer:** LangGraph + CrewAI using OpenRouter API
- **UI Presentation:** Evidence.dev (SQL + Markdown)

## Strict Architecture Rules
1. **Separation of Concerns:** Do not replace mathematical models with LLMs. OR-Tools handles deterministic routing paths; LangGraph handles event intelligence and exceptions.
2. **Layout Blueprint:** Keep flat layout intact (`agents/`, `config/`, `events/`, `optimization/`, `pipelines/`). Do not wrap these top-level folders into a nested package structure.
3. **Execution Isolation:** The OR-Tools solver execution must be triggered as an external subprocess task outside the LangGraph execution block to maintain stateless agent design.

## Current Target Commands
- `make seed` -> Run pipeline ingestion data seeding
- `make solve` -> Trigger CVRPTW routing solver run
- `make events` -> Spin up the background telemetry simulator
- `make agents` -> Run the 5-agent decision graph execution
