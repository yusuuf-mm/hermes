SELECT * FROM solution_metadata
UNION ALL
SELECT
    '__placeholder__' as run_id,
    0 as total_cost_km,
    0 as vehicles_used,
    0 as orders_served,
    0 as constraint_violations,
    0 as solve_time_s,
    'placeholder' as solver_status,
    'placeholder' as scenario_tag,
    NULL as created_at
WHERE NOT EXISTS (SELECT 1 FROM solution_metadata LIMIT 1)
