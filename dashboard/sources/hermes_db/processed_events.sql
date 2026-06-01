SELECT * FROM processed_events
UNION ALL
SELECT '__placeholder__' AS event_id, NULL AS severity, NULL AS category, NULL AS sla_risk_score, NULL AS action_taken, NULL AS processed_at
WHERE NOT EXISTS (SELECT 1 FROM processed_events)
