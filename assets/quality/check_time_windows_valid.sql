/* @bruin
name: hermes.quality.check_time_windows_valid
type: duckdb.sql

connection: hermes_db

depends:
  - hermes.ingestion.seed

description: >
  Asserts every customer node has tw_open < tw_close and
  the window is wide enough to accommodate service time.

columns:
  - name: invalid_windows
    type: integer
    description: "Count of nodes with invalid time windows"
    checks:
      - name: max
        value: 0
@bruin */

CREATE OR REPLACE TABLE quality.check_time_windows_valid AS
SELECT COUNT(*) AS invalid_windows
FROM nodes
WHERE NOT is_depot
  AND (
    tw_open >= tw_close
    OR (tw_close - tw_open) < service_min
  )
