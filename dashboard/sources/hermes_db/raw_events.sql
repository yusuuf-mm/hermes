SELECT * FROM raw_events
UNION ALL
SELECT '__placeholder__' AS event_id, NULL AS event_type, NULL AS vehicle_id, NULL AS node_id, NULL AS payload, NULL AS emitted_at
WHERE NOT EXISTS (SELECT 1 FROM raw_events)
