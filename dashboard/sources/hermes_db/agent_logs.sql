SELECT * FROM agent_logs
UNION ALL
SELECT
    '__placeholder__' as tick_id,
    NULL as run_id,
    'placeholder' as agent_name,
    NULL as started_at,
    NULL as completed_at,
    NULL as input_summary,
    NULL as output_summary,
    NULL as decision,
    NULL as llm_model,
    NULL as tokens_used
WHERE NOT EXISTS (SELECT 1 FROM agent_logs LIMIT 1)
