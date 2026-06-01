# Route Map

Interactive map of vehicle routes across Lagos. Toggle between scenarios using the layer control.

> The interactive route map is generated locally. Run `python optimization/generate_map.py` to generate it, then redeploy.

## Scenarios

```sql scenarios
SELECT
    run_id,
    scenario_tag,
    total_cost_km,
    vehicles_used,
    orders_served,
    solver_status,
    created_at
FROM solution_metadata
ORDER BY created_at DESC
```

<DataTable data={scenarios} rows=10 />
