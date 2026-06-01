SELECT * FROM raw_events
UNION ALL
SELECT
    '__placeholder__' as event_id,
    'placeholder' as event_type,
    NULL as vehicle_id,
    NULL as node_id,
    NULL as payload,
    NULL as emitted_at
WHERE NOT EXISTS (SELECT 1 FROM raw_events LIMIT 1)
