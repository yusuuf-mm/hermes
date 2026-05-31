/* @bruin
name: hermes.quality.check_orders_freshness
type: duckdb.sql

connection: hermes_db

depends:
  - hermes.ingestion.seed

description: >
  Asserts that daily_orders contains pending orders.
  Fails the pipeline if no orders exist.

columns:
  - name: order_count
    type: integer
    description: "Count of pending orders"
    checks:
      - name: not_null
      - name: min
        value: 1
@bruin */

SELECT COUNT(*) AS order_count
FROM daily_orders
WHERE status = 'pending'
