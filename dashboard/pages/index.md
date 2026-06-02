---
title: HERMES — Operations Overview
---

```sql solution_kpis
select
    run_id,
    solver_status,
    total_cost_km,
    vehicles_used,
    orders_served,
    solve_time_s,
    constraint_violations,
    strftime(created_at, '%Y-%m-%d %H:%M') as run_time
from hermes_db.solution_metadata
order by created_at desc
limit 1
```

```sql event_summary
select
    event_type,
    count(*) as total_events
from hermes_db.raw_events
where event_type != 'placeholder'
group by event_type
order by total_events desc
```

```sql processed_summary
select
    severity,
    category,
    count(*)              as event_count,
    round(avg(sla_risk_score), 3) as avg_sla_risk
from hermes_db.processed_events
where severity != 'placeholder'
group by severity, category
order by avg_sla_risk desc
```

```sql vehicle_utilisation
select
    rs.vehicle_id,
    count(*) filter (where rs.node_id != 0) as customer_stops,
    round(max(rs.arrival_time) - min(rs.arrival_time), 0) as time_span_min,
    f.capacity_units,
    f.max_shift_min
from hermes_db.route_solutions rs
join hermes_db.fleet f on rs.vehicle_id = f.vehicle_id
where rs.run_id = (select run_id from hermes_db.solution_metadata order by created_at desc limit 1)
group by rs.vehicle_id, f.capacity_units, f.max_shift_min
order by rs.vehicle_id
```

```sql events_over_time
select
    strftime(emitted_at, '%H:%M') as minute,
    event_type,
    count(*) as events
from hermes_db.raw_events
where event_type != 'placeholder'
group by minute, event_type
order by minute
```

# HERMES Operations Dashboard

Latest solver run: **{solution_kpis[0].run_id}** — Status: **{solution_kpis[0].solver_status}**

---

## Solver KPIs

<BigValue
  data={solution_kpis}
  value="total_cost_km"
  title="Total Route Cost (km)"
  fmt="num1"
/>

<BigValue
  data={solution_kpis}
  value="vehicles_used"
  title="Vehicles Deployed"
/>

<BigValue
  data={solution_kpis}
  value="orders_served"
  title="Nodes Served"
/>

<BigValue
  data={solution_kpis}
  value="solve_time_s"
  title="Solve Time (s)"
  fmt="num2"
/>

<BigValue
  data={solution_kpis}
  value="constraint_violations"
  title="Constraint Violations"
/>

---

## Vehicle Utilisation

<DataTable
  data={vehicle_utilisation}
  rows=10
/>

<BarChart
  data={vehicle_utilisation}
  x="vehicle_id"
  y="customer_stops"
  title="Customer Stops per Vehicle"
  yAxisTitle="Stops"
/>

---

## Event Stream

<BarChart
  data={event_summary}
  x="event_type"
  y="total_events"
  title="Events by Type"
  yAxisTitle="Count"
  swapXY=true
/>

{#if processed_summary.length > 0}

## Agent-Processed Events

<DataTable
  data={processed_summary}
  rows=20
/>

<BubbleChart
  data={processed_summary}
  x="category"
  y="avg_sla_risk"
  size="event_count"
  title="SLA Risk by Event Category"
/>

{/if}

---

*HERMES — Hierarchical Execution & Routing for Multi-agent Enterprise Supply-chain*
