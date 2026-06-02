---
title: Event Monitor
---

```sql raw_events_full
select
    event_id,
    event_type,
    coalesce(vehicle_id, '—')  as vehicle_id,
    coalesce(cast(node_id as varchar), '—') as node_id,
    strftime(emitted_at, '%H:%M:%S') as time
from hermes_db.raw_events
where event_type != 'placeholder'
order by emitted_at desc
limit 100
```

```sql event_type_counts
select
    event_type,
    count(*) as total,
    count(*) filter (where emitted_at >= current_timestamp - interval '1 hour') as last_hour
from hermes_db.raw_events
where event_type != 'placeholder'
group by event_type
order by total desc
```

```sql processed_events_full
select
    p.event_id,
    r.event_type,
    p.severity,
    p.category,
    round(p.sla_risk_score, 3) as sla_risk_score,
    p.action_taken,
    strftime(p.processed_at, '%H:%M:%S') as processed_at
from hermes_db.processed_events p
join hermes_db.raw_events r on p.event_id = r.event_id
where p.severity != 'placeholder'
order by p.processed_at desc
```

```sql severity_breakdown
select
    severity,
    count(*) as count
from hermes_db.processed_events
where severity != 'placeholder'
group by severity
order by
    case severity
        when 'critical' then 1
        when 'high'     then 2
        when 'medium'   then 3
        when 'low'      then 4
    end
```

```sql sla_risk_trend
select
    strftime(processed_at, '%H:%M') as time_bucket,
    round(avg(sla_risk_score), 3)   as avg_risk,
    round(max(sla_risk_score), 3)   as peak_risk,
    count(*)                        as events
from hermes_db.processed_events
where severity != 'placeholder'
group by time_bucket
order by time_bucket
```

# Event Monitor

---

## Event Counts by Type

<DataTable data={event_type_counts} rows=10 />

<BarChart
  data={event_type_counts}
  x="event_type"
  y="total"
  title="Total Events by Type"
  swapXY=true
/>

---

## Raw Event Feed

<DataTable
  data={raw_events_full}
  rows=20
  search=true
/>

---

{#if processed_events_full.length > 0}

## Agent-Processed Events

<DataTable
  data={processed_events_full}
  rows=20
  search=true
/>

### Severity Distribution

<BarChart
  data={severity_breakdown}
  x="severity"
  y="count"
  title="Processed Events by Severity"
  yAxisTitle="Count"
/>

### SLA Risk Over Time

<LineChart
  data={sla_risk_trend}
  x="time_bucket"
  y={["avg_risk", "peak_risk"]}
  title="SLA Risk Score Trend"
  yAxisTitle="Risk Score (0–1)"
  yMin=0
  yMax=1
/>

{:else}

> No processed events yet. Run `make agents` after seeding events to see agent output here.

{/if}
