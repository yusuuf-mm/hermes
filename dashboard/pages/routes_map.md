# Route Map

Interactive map of vehicle routes across Lagos. Toggle between scenarios using the layer control.

<iframe
    src="/routes_map.html"
    width="100%"
    height="700px"
    frameborder="0"
    style="border-radius: 8px; border: 1px solid #e0e0e0;">
</iframe>

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
