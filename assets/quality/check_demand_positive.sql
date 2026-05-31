/* @bruin
name: hermes.quality.check_demand_positive
type: duckdb.sql

connection: hermes_db

depends:
  - hermes.ingestion.seed

description: >
  Asserts that no order has zero or negative demand.

columns:
  - name: bad_rows
    type: integer
    description: "Count of orders with non-positive demand"
    checks:
      - name: max
        value: 0
@bruin */

SELECT COUNT(*) AS bad_rows
FROM daily_orders
WHERE demand_units <= 0
