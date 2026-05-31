/* @bruin
name: hermes.transforms.build_cvrptw_input
type: duckdb.sql

connection: hermes_db

depends:
  - hermes.quality.check_orders_freshness
  - hermes.quality.check_demand_positive
  - hermes.quality.check_time_windows_valid

materialization:
  type: view

description: >
  Materialises the cvrptw_input view joining active orders with
  node attributes. Solver reads from this view — no raw table
  joins inside solver code.
@bruin */

CREATE OR REPLACE VIEW cvrptw_input AS

WITH active_orders AS (
  SELECT o.order_id, o.node_id, o.demand_units, o.order_date
  FROM daily_orders o
  WHERE o.status = 'pending'
),
customer_nodes AS (
  SELECT n.node_id, n.name, n.lat, n.lon,
         n.tw_open, n.tw_close, n.service_min
  FROM nodes n
  WHERE NOT n.is_depot
),
node_demand AS (
  SELECT
    ao.node_id,
    SUM(ao.demand_units)  AS total_demand,
    MIN(cn.tw_open)       AS tw_open,
    MAX(cn.tw_close)      AS tw_close,
    MAX(cn.service_min)   AS service_min,
    MAX(cn.name)          AS name,
    MAX(cn.lat)           AS lat,
    MAX(cn.lon)           AS lon
  FROM active_orders ao
  JOIN customer_nodes cn ON ao.node_id = cn.node_id
  GROUP BY ao.node_id
)

SELECT 0 AS node_id, 'Depot' AS name, 6.4541 AS lat, 3.3947 AS lon,
       360 AS tw_open, 1080 AS tw_close, 0 AS service_min,
       0 AS total_demand, TRUE AS is_depot
FROM (SELECT 1) _depot

UNION ALL

SELECT nd.node_id, nd.name, nd.lat, nd.lon,
       nd.tw_open, nd.tw_close, nd.service_min,
       nd.total_demand, FALSE AS is_depot
FROM node_demand nd
ORDER BY is_depot DESC, node_id ASC;
