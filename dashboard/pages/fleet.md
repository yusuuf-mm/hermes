---
title: Fleet
---

```sql fleet_performance
select
    f.vehicle_id,
    f.capacity_units,
    f.max_shift_min,
    printf('%02d:%02d', cast(f.max_shift_min / 60 as int), cast(f.max_shift_min % 60 as int)) as max_shift_hhmm,
    coalesce(v.customer_stops, 0)   as customer_stops,
    coalesce(v.demand_served, 0)    as demand_served,
    coalesce(v.active_min, 0)       as active_min,
    round(coalesce(v.demand_served, 0) * 100.0 / f.capacity_units, 1) as load_pct,
    round(coalesce(v.active_min, 0)  * 100.0 / f.max_shift_min,   1) as shift_pct
from hermes_db.fleet f
left join (
    select
        vehicle_id,
        count(*) filter (where rs.node_id != 0)         as customer_stops,
        sum(n.demand_units)                          as demand_served,
        max(arrival_time) - min(arrival_time)        as active_min
    from hermes_db.route_solutions rs
    join hermes_db.nodes n on rs.node_id = n.node_id
    where rs.run_id = (
        select run_id from hermes_db.solution_metadata
        order by created_at desc limit 1
    )
    group by rs.vehicle_id
) v on f.vehicle_id = v.vehicle_id
order by f.vehicle_id
```

```sql idle_vehicles
select vehicle_id
from ${fleet_performance}
where customer_stops = 0
```

```sql capacity_summary
select
    sum(capacity_units)                  as total_fleet_capacity,
    sum(demand_served)                   as total_demand_served,
    round(sum(demand_served) * 100.0
        / sum(capacity_units), 1)        as fleet_load_pct,
    count(*) filter (where customer_stops > 0) as active_vehicles,
    count(*) filter (where customer_stops = 0) as idle_vehicles
from ${fleet_performance}
```

# Fleet Status

---

## Fleet Capacity Summary

<BigValue
  data={capacity_summary}
  value="total_fleet_capacity"
  title="Total Fleet Capacity (units)"
/>

<BigValue
  data={capacity_summary}
  value="total_demand_served"
  title="Demand Served (units)"
/>

<BigValue
  data={capacity_summary}
  value="fleet_load_pct"
  title="Fleet Load %"
  fmt="num1"
/>

<BigValue
  data={capacity_summary}
  value="active_vehicles"
  title="Active Vehicles"
/>

---

## Per-Vehicle Performance

<DataTable
  data={fleet_performance}
  rows=10
/>

<BarChart
  data={fleet_performance}
  x="vehicle_id"
  y={["load_pct", "shift_pct"]}
  title="Load % vs Shift Utilisation % per Vehicle"
  yAxisTitle="%"
  yMax=100
  type=grouped
/>

{#if idle_vehicles.length > 0}

## Idle Vehicles (not deployed in current run)

<DataTable data={idle_vehicles} />

> These vehicles were not assigned routes in the current solver run.
> They represent available spare capacity for re-optimisation.

{/if}
