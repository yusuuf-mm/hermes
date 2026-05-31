---
title: Route Plan
---

```sql latest_run
select run_id
from hermes_db.solution_metadata
order by created_at desc
limit 1
```

```sql route_stops
select
    rs.vehicle_id,
    rs.stop_seq,
    rs.node_id,
    n.name                                           as node_name,
    n.is_depot,
    round(rs.arrival_time, 0)                        as arrival_min,
    round(rs.departure_time, 0)                      as departure_min,
    -- Convert minutes from midnight to HH:MM
    printf('%02d:%02d',
        cast(rs.arrival_time / 60 as int),
        cast(rs.arrival_time % 60 as int))           as arrival_hhmm,
    printf('%02d:%02d',
        cast(rs.departure_time / 60 as int),
        cast(rs.departure_time % 60 as int))         as departure_hhmm,
    printf('%02d:%02d', cast(n.tw_open  / 60 as int), cast(n.tw_open  % 60 as int)) as window_open,
    printf('%02d:%02d', cast(n.tw_close / 60 as int), cast(n.tw_close % 60 as int)) as window_close,
    n.demand_units,
    -- Flag stops where arrival is close to window close (within 30 min)
    case when (n.tw_close - rs.arrival_time) < 30 and not n.is_depot
         then 'at_risk' else 'ok' end               as time_window_status
from hermes_db.route_solutions rs
join hermes_db.nodes n on rs.node_id = n.node_id
where rs.run_id = (select run_id from hermes_db.solution_metadata order by created_at desc limit 1)
order by rs.vehicle_id, rs.stop_seq
```

```sql at_risk_stops
select *
from ${route_stops}
where time_window_status = 'at_risk'
```

```sql vehicle_timelines
select
    vehicle_id,
    count(*) filter (where not is_depot) as customer_stops,
    min(arrival_min) as earliest_min,
    max(departure_min) as latest_min,
    max(departure_min) - min(arrival_min) as active_duration_min,
    sum(demand_units) as total_demand_served
from ${route_stops}
group by vehicle_id
order by vehicle_id
```

# Route Plan

Run: **{latest_run[0].run_id}**

---

## Route Summary by Vehicle

<DataTable data={vehicle_timelines} rows=10 />

---

## Full Stop Sequences

<DataTable
  data={route_stops}
  rows=30
  search=true
/>

{#if at_risk_stops.length > 0}

## ⚠ At-Risk Stops (arrival within 30 min of window close)

<DataTable
  data={at_risk_stops}
  rows=10
/>

{/if}

---

## Arrival Timeline per Vehicle

<BarChart
  data={route_stops}
  x="arrival_hhmm"
  y="demand_units"
  series="vehicle_id"
  title="Demand Delivered by Arrival Time"
  yAxisTitle="Demand Units"
  type=stacked
/>
