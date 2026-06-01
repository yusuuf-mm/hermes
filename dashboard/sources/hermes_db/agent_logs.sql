SELECT * FROM agent_logs
UNION ALL
SELECT NULL AS tick_id, NULL AS run_id, NULL AS agent_name, NULL AS started_at, NULL AS completed_at, NULL AS input_summary, NULL AS output_summary, NULL AS decision, NULL AS llm_model, NULL AS tokens_used
WHERE NOT EXISTS (SELECT 1 FROM agent_logs)
