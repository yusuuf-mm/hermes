"""
dashboard.py
------------
Generates a standalone HTML dashboard from HERMES DuckDB data.
Outputs hermes_dashboard.html with dark theme, Plotly charts,
and an agent telemetry audit trail.

Usage:
    python dashboard/dashboard.py           # generate once
    python dashboard/dashboard.py --watch   # regenerate every 60s
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import duckdb

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "hermes_dashboard.html")

# Dark theme colours
BG = "#0A0E1A"
CARD = "#111827"
TEXT = "#E2E8F0"
ACCENT = "#00D4A8"
BORDER = "#1E293B"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_solution_metadata(con):
    rows = con.execute("""
        SELECT run_id, total_cost_km, vehicles_used, orders_served,
               constraint_violations, solve_time_s, solver_status,
               scenario_tag, created_at
        FROM solution_metadata
        ORDER BY created_at DESC LIMIT 1
    """).fetchall()
    if not rows:
        return None
    r = rows[0]
    return {
        "run_id": r[0], "total_cost_km": r[1], "vehicles_used": r[2],
        "orders_served": r[3], "constraint_violations": r[4],
        "solve_time_s": r[5], "solver_status": r[6],
        "scenario_tag": r[7], "created_at": str(r[8]),
    }


def load_fleet(con):
    rows = con.execute("""
        SELECT
            f.vehicle_id,
            COUNT(rs.node_id) FILTER (WHERE rs.node_id != 0) AS stops,
            COALESCE(SUM(n.demand_units), 0) AS demand,
            f.capacity_units,
            f.max_shift_min
        FROM fleet f
        LEFT JOIN route_solutions rs ON f.vehicle_id = rs.vehicle_id
            AND rs.run_id = (SELECT run_id FROM solution_metadata ORDER BY created_at DESC LIMIT 1)
        LEFT JOIN nodes n ON rs.node_id = n.node_id
        GROUP BY f.vehicle_id, f.capacity_units, f.max_shift_min
        ORDER BY f.vehicle_id
    """).fetchall()
    return [
        {"vehicle_id": r[0], "stops": r[1], "demand": r[2],
         "capacity": r[3], "max_shift": r[4]}
        for r in rows
    ]


def load_processed_events(con):
    rows = con.execute("""
        SELECT p.event_id, r.event_type, p.severity, p.category,
               p.sla_risk_score, p.action_taken, p.processed_at
        FROM processed_events p
        JOIN raw_events r ON p.event_id = r.event_id
        ORDER BY p.processed_at DESC LIMIT 30
    """).fetchall()
    return [
        {"event_id": r[0], "event_type": r[1], "severity": r[2],
         "category": r[3], "sla_risk_score": r[4],
         "action_taken": r[5], "processed_at": str(r[6])}
        for r in rows
    ]


def load_agent_logs(con):
    """Load last 100 agent log rows. Returns empty list if table missing."""
    try:
        rows = con.execute("""
            SELECT
                tick_id,
                agent_name,
                llm_model,
                ROUND(EPOCH_MS(completed_at - started_at), 0) AS latency_ms,
                input_summary,
                output_summary,
                completed_at
            FROM agent_logs
            ORDER BY completed_at DESC
            LIMIT 100
        """).fetchall()
        return [
            {"tick_id": r[0], "agent_name": r[1], "llm_model": r[2],
             "latency_ms": r[3], "input_summary": r[4],
             "output_summary": r[5], "completed_at": str(r[6])}
            for r in rows
        ]
    except Exception:
        return []


def load_sla_trend(con):
    """SLA risk score per tick from agent_logs. Empty list if unavailable."""
    try:
        rows = con.execute("""
            SELECT
                tick_id,
                MAX(CASE WHEN agent_name = 'sla_risk'
                    THEN TRY_CAST(decision AS DOUBLE) END) AS sla_risk_score,
                MIN(started_at) AS tick_started
            FROM agent_logs
            GROUP BY tick_id
            ORDER BY tick_started
        """).fetchall()
        return [{"tick_id": r[0], "sla_risk_score": r[1] or 0, "tick_started": str(r[2])} for r in rows]
    except Exception:
        return []


def load_agent_latency(con):
    """Average latency per agent. Empty list if unavailable."""
    try:
        rows = con.execute("""
            SELECT
                agent_name,
                ROUND(AVG(EPOCH_MS(completed_at - started_at)), 0) AS avg_latency_ms
            FROM agent_logs
            GROUP BY agent_name
            ORDER BY avg_latency_ms DESC
        """).fetchall()
        return [{"agent_name": r[0], "avg_latency_ms": r[1] or 0} for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Plotly chart generators
# ---------------------------------------------------------------------------

def chart_sla_trend(sla_data):
    if not sla_data:
        return "<p style='color:#64748B'>No SLA trend data available.</p>"
    tick_ids = [d["tick_id"][:8] for d in sla_data]
    scores = [d["sla_risk_score"] for d in sla_data]
    return f"""
    <div id="sla_trend" style="height:300px"></div>
    <script>
    Plotly.newPlot('sla_trend', [{{
        x: {json.dumps(tick_ids)},
        y: {json.dumps(scores)},
        type: 'scatter',
        mode: 'lines+markers',
        line: {{color: '{ACCENT}', width: 2}},
        marker: {{color: '{ACCENT}', size: 6}},
        fill: 'tozeroy',
        fillcolor: 'rgba(0,212,168,0.1)'
    }}], {{
        paper_bgcolor: '{CARD}', plot_bgcolor: '{CARD}',
        font: {{color: '{TEXT}'}},
        xaxis: {{title: 'Tick', gridcolor: '{BORDER}'}},
        yaxis: {{title: 'SLA Risk Score', gridcolor: '{BORDER}', range: [0, 1]}},
        margin: {{t: 30, b: 50, l: 50, r: 20}},
        title: {{text: 'SLA Risk Trend Across Ticks', font: {{size: 14}}}}
    }}, {{responsive: true}});
    </script>
    """


def chart_agent_latency(latency_data):
    if not latency_data:
        return "<p style='color:#64748B'>No latency data available.</p>"
    agents = [d["agent_name"] for d in latency_data]
    latencies = [d["avg_latency_ms"] for d in latency_data]
    colors = ["#00D4A8", "#3B82F6", "#F59E0B", "#EF4444", "#8B5CF6"][:len(agents)]
    return f"""
    <div id="agent_latency" style="height:300px"></div>
    <script>
    Plotly.newPlot('agent_latency', [{{
        y: {json.dumps(agents)},
        x: {json.dumps(latencies)},
        type: 'bar',
        orientation: 'h',
        marker: {{color: {json.dumps(colors)}}}
    }}], {{
        paper_bgcolor: '{CARD}', plot_bgcolor: '{CARD}',
        font: {{color: '{TEXT}'}},
        xaxis: {{title: 'Avg Latency (ms)', gridcolor: '{BORDER}'}},
        yaxis: {{gridcolor: '{BORDER}'}},
        margin: {{t: 30, b: 50, l: 120, r: 20}},
        title: {{text: 'Agent Execution Latency (ms)', font: {{size: 14}}}}
    }}, {{responsive: true}});
    </script>
    """


# ---------------------------------------------------------------------------
# HTML table generators
# ---------------------------------------------------------------------------

def html_fleet_table(fleet):
    rows = ""
    for v in fleet:
        load_pct = round(v["demand"] / v["capacity"] * 100) if v["capacity"] > 0 else 0
        status = "IDLE" if v["stops"] == 0 else ("OVERLOADED" if load_pct > 100 else "ACTIVE")
        status_color = "#64748B" if status == "IDLE" else ("#EF4444" if status == "OVERLOADED" else ACCENT)
        rows += f"""<tr>
            <td>{v['vehicle_id']}</td><td>{v['stops']}</td>
            <td>{v['demand']}/{v['capacity']}</td>
            <td style="color:{status_color}">{status}</td>
        </tr>"""
    return f"""<table>
        <thead><tr><th>Vehicle</th><th>Stops</th><th>Load</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def html_events_table(events):
    if not events:
        return "<p style='color:#64748B'>No processed events yet.</p>"
    rows = ""
    for e in events:
        sev_color = {"critical": "#EF4444", "high": "#F59E0B", "medium": "#3B82F6", "low": "#64748B"}.get(e["severity"], TEXT)
        rows += f"""<tr>
            <td>{e['event_type']}</td>
            <td style="color:{sev_color}">{e['severity']}</td>
            <td>{e['category']}</td>
            <td>{e['sla_risk_score']:.2f}</td>
            <td>{e['action_taken']}</td>
        </tr>"""
    return f"""<table>
        <thead><tr><th>Event Type</th><th>Severity</th><th>Category</th><th>SLA Score</th><th>Action</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def html_agent_logs_table(logs):
    if not logs:
        return "<p style='color:#64748B'>No agent logs yet. Run the agent pipeline to generate data.</p>"
    rows = ""
    for r in logs[:20]:
        summary = (r["output_summary"] or "")[:100]
        rows += f"""<tr>
            <td>{r['tick_id'][:8]}</td>
            <td>{r['agent_name']}</td>
            <td>{r['llm_model']}</td>
            <td>{int(r['latency_ms'] or 0)}</td>
            <td>{summary}</td>
            <td>{r['completed_at'][:19]}</td>
        </tr>"""
    return f"""<table>
        <thead><tr><th>Tick</th><th>Agent</th><th>Model</th><th>Latency (ms)</th><th>Summary</th><th>Time</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


# ---------------------------------------------------------------------------
# Main HTML builder
# ---------------------------------------------------------------------------

def build_html(con):
    meta = load_solution_metadata(con)
    fleet = load_fleet(con)
    events = load_processed_events(con)
    agent_logs = load_agent_logs(con)
    sla_trend = load_sla_trend(con)
    agent_latency = load_agent_latency(con)

    meta_html = ""
    if meta:
        meta_html = f"""
        <div class="kpi-row">
            <div class="kpi"><span class="kpi-label">Run ID</span><span class="kpi-value">{meta['run_id'][:12]}</span></div>
            <div class="kpi"><span class="kpi-label">Status</span><span class="kpi-value">{meta['solver_status']}</span></div>
            <div class="kpi"><span class="kpi-label">Scenario</span><span class="kpi-value">{meta['scenario_tag']}</span></div>
            <div class="kpi"><span class="kpi-label">Total Cost</span><span class="kpi-value">{meta['total_cost_km']:.1f} km</span></div>
            <div class="kpi"><span class="kpi-label">Vehicles</span><span class="kpi-value">{meta['vehicles_used']}</span></div>
            <div class="kpi"><span class="kpi-label">Orders Served</span><span class="kpi-value">{meta['orders_served']}</span></div>
            <div class="kpi"><span class="kpi-label">Violations</span><span class="kpi-value">{meta['constraint_violations']}</span></div>
            <div class="kpi"><span class="kpi-label">Solve Time</span><span class="kpi-value">{meta['solve_time_s']:.1f}s</span></div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HERMES Operations Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: {BG}; color: {TEXT}; font-family: 'Inter', -apple-system, sans-serif; padding: 2rem; }}
        h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; color: {ACCENT}; }}
        h2 {{ font-size: 1.3rem; margin: 2rem 0 1rem; color: {TEXT}; border-bottom: 1px solid {BORDER}; padding-bottom: 0.5rem; }}
        .subtitle {{ color: #64748B; margin-bottom: 2rem; }}
        .kpi-row {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }}
        .kpi {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 1rem 1.5rem; min-width: 140px; }}
        .kpi-label {{ display: block; font-size: 0.75rem; color: #64748B; text-transform: uppercase; }}
        .kpi-value {{ display: block; font-size: 1.4rem; font-weight: 700; color: {ACCENT}; margin-top: 0.25rem; }}
        .card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
        th {{ text-align: left; padding: 0.75rem; border-bottom: 2px solid {BORDER}; color: #64748B; font-size: 0.75rem; text-transform: uppercase; }}
        td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid {BORDER}; }}
        tr:hover td {{ background: rgba(0,212,168,0.05); }}
        .timestamp {{ color: #475569; font-size: 0.8rem; text-align: right; margin-top: 2rem; }}
    </style>
</head>
<body>
    <h1>HERMES Operations Dashboard</h1>
    <p class="subtitle">Hierarchical Execution & Routing for Multi-agent Enterprise Supply-chain</p>

    {meta_html}

    <h2>Fleet Status</h2>
    <div class="card">{html_fleet_table(fleet)}</div>

    <h2>Processed Events</h2>
    <div class="card">{html_events_table(events)}</div>

    <h2>Agent Telemetry — Cognitive Audit Trail</h2>
    <div class="card">{chart_sla_trend(sla_trend)}</div>
    <div class="card">{chart_agent_latency(agent_latency)}</div>
    <div class="card">{html_agent_logs_table(agent_logs)}</div>

    <p class="timestamp">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate():
    con = duckdb.connect(DB_PATH, read_only=True)
    html = build_html(con)
    con.close()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] Dashboard generated: {OUTPUT_PATH}")


def main():
    if "--watch" in sys.argv:
        print(f"Watching for changes, regenerating every 60s. Ctrl+C to stop.")
        while True:
            try:
                generate()
            except Exception as e:
                print(f"[ERROR] {e}")
            time.sleep(60)
    else:
        generate()


if __name__ == "__main__":
    main()
