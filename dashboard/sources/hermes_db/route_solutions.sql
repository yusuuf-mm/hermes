SELECT * FROM route_solutions
UNION ALL
SELECT
    '__placeholder__' as run_id,
    '__placeholder__' as vehicle_id,
    0 as stop_seq,
    0 as node_id,
    0 as arrival_time,
    0 as departure_time
WHERE NOT EXISTS (SELECT 1 FROM route_solutions LIMIT 1)
