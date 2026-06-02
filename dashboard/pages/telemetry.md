# Agent Telemetry

Cognitive audit trail of the multi-agent decision pipeline. Shows agent execution history, latency, and reasoning.

```sql total_ticks
SELECT COUNT(DISTINCT tick_id) AS total_ticks FROM agent_logs
WHERE agent_name != 'placeholder'
```

```sql total_resolves
SELECT COUNT(DISTINCT tick_id) AS total_resolves
FROM agent_logs
WHERE agent_name = 'rerouting' AND decision LIKE '%resolv=True%'
```

```sql avg_latency
SELECT ROUND(SUM(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000) / 1000.0 / COUNT(DISTINCT tick_id), 1) AS avg_latency_s
FROM agent_logs
WHERE agent_name != 'placeholder'
```

<BigValue data={total_ticks} value="total_ticks" title="Total Ticks Run" />
<BigValue data={total_resolves} value="total_resolves" title="Re-Solves Triggered" />
<BigValue data={avg_latency} value="avg_latency_s" title="Avg Pipeline Latency (s)" />

## SLA Risk Score by Tick

```sql sla_by_tick
SELECT
    al.tick_id,
    MAX(CASE WHEN al.agent_name = 'sla_risk' THEN TRY_CAST(al.decision AS DOUBLE) END) AS sla_risk_score,
    MIN(al.started_at) AS tick_started
FROM agent_logs al
WHERE al.agent_name != 'placeholder'
GROUP BY al.tick_id
ORDER BY tick_started
```

<LineChart data={sla_by_tick} x="tick_id" y="sla_risk_score" title="SLA Risk Score by Tick" />

## Agent Latency

```sql agent_latency
SELECT
    agent_name,
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000), 0) AS avg_latency_ms
FROM agent_logs
WHERE agent_name != 'placeholder'
GROUP BY agent_name
ORDER BY avg_latency_ms DESC
```

<BarChart data={agent_latency} x="agent_name" y="avg_latency_ms" title="Agent Latency (ms)" />

## Agent Summary

```sql agent_summary
SELECT
    agent_name,
    COUNT(*) AS executions,
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000), 0) AS avg_latency_ms,
    llm_model
FROM agent_logs
WHERE agent_name != 'placeholder'
GROUP BY agent_name, llm_model
ORDER BY executions DESC
```

<DataTable data={agent_summary} search="true" />

## Execution Log

```sql full_log
SELECT
    strftime(completed_at, '%Y-%m-%d %H:%M:%S') AS logged_at,
    tick_id AS tick,
    agent_name,
    llm_model AS model,
    ROUND(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000, 0) AS latency_ms,
    LEFT(output_summary, 120) AS summary,
    decision
FROM agent_logs
WHERE agent_name != 'placeholder'
ORDER BY completed_at DESC
LIMIT 50
```

<DataTable data={full_log} search="true" rows=25 />

## Tick History

```sql tick_history
SELECT
    al.tick_id,
    COUNT(*) AS events_processed,
    MIN(al.started_at) AS tick_started,
    ROUND(SUM(EXTRACT(EPOCH FROM (al.completed_at - al.started_at)) * 1000) / 1000.0, 1) AS pipeline_latency_s,
    MAX(CASE WHEN al.agent_name = 'rerouting' AND al.decision LIKE '%resolv=True%' THEN true ELSE false END) AS resolve_triggered
FROM agent_logs al
WHERE al.agent_name != 'placeholder'
GROUP BY al.tick_id
ORDER BY tick_started DESC
LIMIT 20
```

<DataTable data={tick_history} search="true" />
