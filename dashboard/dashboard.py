"""
dashboard.py
------------
Generates a standalone HTML operational viewport for HERMES from live
DuckDB data. This complements the Evidence.dev dashboard at
https://yusuuf-mm.github.io/hermes/ — different consumer, different
purpose:

  - Evidence.dev   : 6-page static site, deployed via GitHub Pages, read-
                     only, intended for stakeholders and post-hoc analysis.
  - dashboard.py   : 1-page single-file HTML, regenerated on demand, in-
                     tended for live operator view ("what is the system
                     doing RIGHT NOW?").

Outputs hermes_dashboard.html with:
  - Dark theme, Inter typography, teal accent (matches Evidence palette).
  - Solver KPIs from the latest run.
  - Fleet status table + per-vehicle load gauges.
  - Processed events table + recent activity timeline.
  - Solver history chart (last 10 runs).
  - Agent telemetry: SLA risk trend, agent latency, audit log.
  - "Last refresh" indicator for live-operator feel.

Usage:
    python dashboard/dashboard.py           # generate once
    python dashboard/dashboard.py --watch   # regenerate every 15s
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
WATCH_INTERVAL_S = 15  # reduced from 60s — operator viewport, not archival

# Dark theme — aligned with Evidence dashboard teal (#1D9E75)
BG       = "#0A0E1A"
CARD     = "#111827"
TEXT     = "#E2E8F0"
ACCENT   = "#1D9E75"   # Evidence teal (was #00D4A8)
ACCENT2  = "#3B82F6"   # blue accent for secondary charts
BORDER   = "#1E293B"
MUTED    = "#64748B"
FONT     = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


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


def load_recent_activity(con):
    """Flat list of the last 20 events for the timeline view."""
    rows = con.execute("""
        SELECT r.event_type, p.severity, p.category, p.processed_at
        FROM processed_events p
        JOIN raw_events r ON p.event_id = r.event_id
        ORDER BY p.processed_at DESC LIMIT 20
    """).fetchall()
    return [
        {"event_type": r[0], "severity": r[1], "category": r[2],
         "processed_at": str(r[3])}
        for r in rows
    ]


def load_solver_history(con):
    """Last 10 solver runs for the solver history chart."""
    try:
        rows = con.execute("""
            SELECT run_id, solver_status, solve_time_s,
                   vehicles_used, total_cost_km, created_at
            FROM solution_metadata
            ORDER BY created_at DESC LIMIT 10
        """).fetchall()
        return [
            {"run_id": r[0], "status": r[1], "solve_time_s": float(r[2] or 0),
             "vehicles_used": r[3], "total_cost_km": float(r[4] or 0),
             "created_at": str(r[5])}
            for r in rows
        ]
    except Exception:
        return []


def load_agent_logs(con):
    """Load last 100 agent log rows. Returns empty list if table missing."""
    try:
        rows = con.execute("""
            SELECT
                tick_id,
                agent_name,
                llm_model,
                ROUND((completed_at - started_at) * 1000, 0) AS latency_ms,
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
                ROUND(AVG((completed_at - started_at) * 1000), 0) AS avg_latency_ms
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
        return f"<p style='color:{MUTED}'>No SLA trend data available.</p>"
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
        fillcolor: 'rgba(29,158,117,0.1)'
    }}], {{
        paper_bgcolor: '{CARD}', plot_bgcolor: '{CARD}',
        font: {{color: '{TEXT}', family: {json.dumps(FONT)}}},
        xaxis: {{title: 'Tick', gridcolor: '{BORDER}'}},
        yaxis: {{title: 'SLA Risk Score', gridcolor: '{BORDER}', range: [0, 1]}},
        margin: {{t: 30, b: 50, l: 50, r: 20}},
        title: {{text: 'SLA Risk Trend Across Ticks', font: {{size: 14}}}}
    }}, {{responsive: true}});
    </script>
    """


def chart_agent_latency(latency_data):
    if not latency_data:
        return f"<p style='color:{MUTED}'>No latency data available.</p>"
    agents = [d["agent_name"] for d in latency_data]
    latencies = [d["avg_latency_ms"] for d in latency_data]
    colors = [ACCENT, ACCENT2, "#F59E0B", "#EF4444", "#8B5CF6"][:len(agents)]
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
        font: {{color: '{TEXT}', family: {json.dumps(FONT)}}},
        xaxis: {{title: 'Avg Latency (ms)', gridcolor: '{BORDER}'}},
        yaxis: {{gridcolor: '{BORDER}'}},
        margin: {{t: 30, b: 50, l: 120, r: 20}},
        title: {{text: 'Agent Execution Latency (ms)', font: {{size: 14}}}}
    }}, {{responsive: true}});
    </script>
    """


def chart_solver_history(solver_data):
    if not solver_data:
        return f"<p style='color:{MUTED}'>No solver history available. Run `make solve` to generate a baseline.</p>"
    # Reverse to chronological order (oldest first)
    solver_data = list(reversed(solver_data))
    labels = [d["run_id"][:8] for d in solver_data]
    durations = [d["solve_time_s"] for d in solver_data]
    costs = [d["total_cost_km"] for d in solver_data]
    statuses = [d["status"] for d in solver_data]
    bar_colors = [ACCENT if s in ("OPTIMAL", "SUCCESS") else "#EF4444" for s in statuses]

    return f"""
    <div id="solver_history" style="height:300px"></div>
    <script>
    Plotly.newPlot('solver_history', [
        {{
            x: {json.dumps(labels)},
            y: {json.dumps(durations)},
            type: 'bar',
            name: 'Solve time (s)',
            marker: {{color: {json.dumps(bar_colors)}}},
            yaxis: 'y'
        }},
        {{
            x: {json.dumps(labels)},
            y: {json.dumps(costs)},
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Total cost (km)',
            line: {{color: '{ACCENT2}', width: 2}},
            marker: {{color: '{ACCENT2}', size: 8}},
            yaxis: 'y2'
        }}
    ], {{
        paper_bgcolor: '{CARD}', plot_bgcolor: '{CARD}',
        font: {{color: '{TEXT}', family: {json.dumps(FONT)}}},
        xaxis: {{title: 'Run', gridcolor: '{BORDER}'}},
        yaxis: {{title: 'Solve time (s)', gridcolor: '{BORDER}', side: 'left'}},
        yaxis2: {{title: 'Total cost (km)', overlaying: 'y', side: 'right', gridcolor: '{BORDER}'}},
        margin: {{t: 30, b: 50, l: 60, r: 60}},
        legend: {{x: 0, y: 1.15, orientation: 'h'}},
        title: {{text: 'Solver History (last 10 runs)', font: {{size: 14}}}}
    }}, {{responsive: true}});
    </script>
    """


# ---------------------------------------------------------------------------
# HTML table / component generators
# ---------------------------------------------------------------------------

def html_fleet_table(fleet):
    rows = ""
    for v in fleet:
        load_pct = round(v["demand"] / v["capacity"] * 100) if v["capacity"] > 0 else 0
        status = "IDLE" if v["stops"] == 0 else ("OVERLOADED" if load_pct > 100 else "ACTIVE")
        status_color = MUTED if status == "IDLE" else ("#EF4444" if status == "OVERLOADED" else ACCENT)
        rows += f"""<tr>
            <td>{v['vehicle_id']}</td><td>{v['stops']}</td>
            <td>{v['demand']}/{v['capacity']}</td>
            <td style="color:{status_color}">{status}</td>
        </tr>"""
    return f"""<table>
        <thead><tr><th>Vehicle</th><th>Stops</th><th>Load</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def html_fleet_gauges(fleet):
    """Per-vehicle horizontal load progress bars."""
    if not fleet:
        return f"<p style='color:{MUTED}'>No fleet data.</p>"
    items = ""
    for v in fleet:
        load_pct = round(v["demand"] / v["capacity"] * 100) if v["capacity"] > 0 else 0
        load_pct_clamped = min(load_pct, 100)
        bar_color = ACCENT if load_pct <= 100 else "#EF4444"
        items += f"""
        <div class="gauge">
            <div class="gauge-label">
                <span>{v['vehicle_id']}</span>
                <span style="color:{MUTED}">{load_pct}% ({v['demand']}/{v['capacity']})</span>
            </div>
            <div class="gauge-bar">
                <div class="gauge-fill" style="width:{load_pct_clamped}%;background:{bar_color}"></div>
            </div>
        </div>"""
    return f"<div class='gauges'>{items}</div>"


def html_events_table(events):
    if not events:
        return f"<p style='color:{MUTED}'>No processed events yet.</p>"
    rows = ""
    sev_color = {"critical": "#EF4444", "high": "#F59E0B", "medium": ACCENT2, "low": MUTED}
    for e in events:
        sc = sev_color.get(e["severity"], TEXT)
        rows += f"""<tr>
            <td>{e['event_type']}</td>
            <td style="color:{sc}">{e['severity']}</td>
            <td>{e['category']}</td>
            <td>{e['sla_risk_score']:.2f}</td>
            <td>{e['action_taken']}</td>
        </tr>"""
    return f"""<table>
        <thead><tr><th>Event Type</th><th>Severity</th><th>Category</th><th>SLA Score</th><th>Action</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def html_activity_timeline(events):
    """Color-coded timeline of recent events (oldest → newest, left → right)."""
    if not events:
        return f"<p style='color:{MUTED}'>No activity yet.</p>"
    sev_color = {"critical": "#EF4444", "high": "#F59E0B", "medium": ACCENT2, "low": MUTED}
    chips = ""
    for e in reversed(events):  # chronological
        c = sev_color.get(e["severity"], MUTED)
        chips += f"""<div class="timeline-chip" style="border-color:{c}" title="{e['event_type']} ({e['severity']})">
            <span class="timeline-dot" style="background:{c}"></span>
            <span class="timeline-label">{e['event_type'][:12]}</span>
        </div>"""
    return f"<div class='timeline'>{chips}</div>"


def html_agent_logs_table(logs):
    if not logs:
        return f"<p style='color:{MUTED}'>No agent logs yet. Run the agent pipeline to generate data.</p>"
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
    meta          = load_solution_metadata(con)
    fleet         = load_fleet(con)
    events        = load_processed_events(con)
    recent        = load_recent_activity(con)
    solver_hist   = load_solver_history(con)
    agent_logs    = load_agent_logs(con)
    sla_trend     = load_sla_trend(con)
    agent_latency = load_agent_latency(con)

    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: {BG}; color: {TEXT}; font-family: {FONT}; padding: 2rem; }}
        h1 {{ font-size: 1.8rem; margin-bottom: 0.25rem; color: {ACCENT}; font-weight: 700; }}
        h2 {{ font-size: 1.3rem; margin: 2rem 0 1rem; color: {TEXT}; border-bottom: 1px solid {BORDER}; padding-bottom: 0.5rem; font-weight: 600; }}
        .subtitle {{ color: {MUTED}; margin-bottom: 0.5rem; font-size: 0.95rem; }}
        .refresh {{ color: {ACCENT}; font-size: 0.8rem; margin-bottom: 1.5rem; font-weight: 500; }}
        .refresh::before {{ content: '● '; animation: pulse 2s ease-in-out infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
        .kpi-row {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }}
        .kpi {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 1rem 1.5rem; min-width: 140px; }}
        .kpi-label {{ display: block; font-size: 0.7rem; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.05em; }}
        .kpi-value {{ display: block; font-size: 1.3rem; font-weight: 700; color: {ACCENT}; margin-top: 0.25rem; font-variant-numeric: tabular-nums; }}
        .card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; }}
        .card-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
        @media (max-width: 900px) {{ .card-row {{ grid-template-columns: 1fr; }} }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
        th {{ text-align: left; padding: 0.75rem; border-bottom: 2px solid {BORDER}; color: {MUTED}; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }}
        td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid {BORDER}; }}
        tr:hover td {{ background: rgba(29,158,117,0.05); }}
        .gauges {{ display: flex; flex-direction: column; gap: 0.75rem; }}
        .gauge-label {{ display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 0.25rem; font-weight: 500; }}
        .gauge-bar {{ background: {BORDER}; height: 8px; border-radius: 4px; overflow: hidden; }}
        .gauge-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
        .timeline {{ display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }}
        .timeline-chip {{ display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0.6rem; border: 1px solid; border-radius: 4px; font-size: 0.75rem; background: {BG}; }}
        .timeline-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
        .timeline-label {{ font-weight: 500; }}
        .timestamp {{ color: {MUTED}; font-size: 0.8rem; text-align: right; margin-top: 2rem; font-variant-numeric: tabular-nums; }}
    </style>
</head>
<body>
    <h1>HERMES Operations Dashboard</h1>
    <p class="subtitle">Hierarchical Execution &amp; Routing for Multi-agent Enterprise Supply-chain</p>
    <p class="refresh">Live — last refresh {now_utc} UTC</p>

    {meta_html}

    <h2>Fleet Status</h2>
    <div class="card-row">
        <div class="card">{html_fleet_table(fleet)}</div>
        <div class="card"><h3 style="font-size:0.95rem;color:{MUTED};margin-bottom:1rem;text-transform:uppercase;letter-spacing:0.05em">Load Distribution</h3>{html_fleet_gauges(fleet)}</div>
    </div>

    <h2>Processed Events</h2>
    <div class="card-row">
        <div class="card">{html_events_table(events)}</div>
        <div class="card"><h3 style="font-size:0.95rem;color:{MUTED};margin-bottom:1rem;text-transform:uppercase;letter-spacing:0.05em">Recent Activity (last 20)</h3>{html_activity_timeline(recent)}</div>
    </div>

    <h2>Solver History</h2>
    <div class="card">{chart_solver_history(solver_hist)}</div>

    <h2>Agent Telemetry — Cognitive Audit Trail</h2>
    <div class="card-row">
        <div class="card">{chart_sla_trend(sla_trend)}</div>
        <div class="card">{chart_agent_latency(agent_latency)}</div>
    </div>
    <div class="card">{html_agent_logs_table(agent_logs)}</div>

    <p class="timestamp">Generated {now_utc} UTC &middot; HERMES dashboard.py &middot; reads live DuckDB</p>
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
        print(f"Watching for changes, regenerating every {WATCH_INTERVAL_S}s. Ctrl+C to stop.")
        while True:
            try:
                generate()
            except Exception as e:
                print(f"[ERROR] {e}")
            time.sleep(WATCH_INTERVAL_S)
    else:
        generate()


if __name__ == "__main__":
    main()
