SELECT * FROM processed_events
UNION ALL
SELECT
    '__placeholder__' as event_id,
    'placeholder' as severity,
    'placeholder' as category,
    0.0 as sla_risk_score,
    'placeholder' as action_taken,
    NULL as processed_at
WHERE NOT EXISTS (SELECT 1 FROM processed_events LIMIT 1)
