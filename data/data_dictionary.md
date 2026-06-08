# PromoLens AI — Synthetic Data Dictionary

> Fully synthetic. No real or customer data. Seeded & reproducible via `data/generate_synthetic_data.py`.

## Planted analytical needles

- **N1_winner** — Clear WINNER scheme (real uplift): `SCHBLD001`
- **N2_dud** — Clear DUD scheme (paid for baseline): `SCHBLD002`
- **N5_stacking** — Stacking trap schemes (putty): `['SCHBLD003', 'SCHBLD004', 'SCHBLD005', 'SCHBLD006']`
- **N4_overclaim_scheme** — Over-claim scheme: `SCHPHA008`
- **N3_leak_distributor** — Inventory-loading leak (distributor): `P1001`
- **N6_cannibal_pair** — Cannibalisation [push, victim]: `['BLD-PUTTY-S', 'BLD-PUTTY-W']`
- **N7_sync_fail_rate** — Master-sync failure rate: `0.072`
- **N8_nonapplying_scheme** — Scheme that silently didn't apply: `SCHBLD007`

## Tables

### `baseline_sales`  (1,440 rows)

| column | example |
|---|---|
| sku_code | BLD-AAC |
| region | Gujarat |
| month | 2024-12 |
| baseline_qty | 474.4 |
| baseline_value | 175439.3 |

### `channel_partners`  (95 rows)

| column | example |
|---|---|
| partner_id | P1001 |
| name | Choudhury, Bakshi and Mahara |
| type | distributor |
| parent_id | nan |
| industry_id | BLD |
| region | West |
| state | Rajasthan |
| zone | West |
| tier | B |
| channel | Direct |
| active_since | 2019-03-24 |

### `industries`  (3 rows)

| column | example |
|---|---|
| industry_id | BLD |
| name | Building Materials |
| company | DuraBuild |
| uom | bag |
| currency | INR |

### `master_sync_log`  (1,201 rows)

| column | example |
|---|---|
| entity_type | retailer_master |
| entity_id | RET00000 |
| source | ERP/Tally |
| status | ok |
| error_reason | nan |
| ts | 2026-03-18 23:30:19.914000 |

### `primary_sales`  (4,032 rows)

| column | example |
|---|---|
| order_id | PO000001 |
| partner_id | P1001 |
| sku_code | BLD-OPC53 |
| qty | 99 |
| value | 35758.8 |
| order_date | 2024-12-13 |
| region | Rajasthan |

### `products`  (18 rows)

| column | example |
|---|---|
| sku_code | BLD-OPC53 |
| industry_id | BLD |
| brand | DuraBuild Cement |
| sub_brand | Cement |
| mrp | 420 |
| category | Cement |
| uom | bag |
| asp | 361.2 |
| unit_cost | 300 |

### `scheme_application`  (1,164 rows)

| column | example |
|---|---|
| invoice_id | PO000013 |
| scheme_id | SCHBLD001 |
| applied_qty | 346 |
| computed_payout | 3124.38 |
| effective_pct | 2.5 |
| applied_flag | True |
| skip_reason | nan |

### `scheme_claims`  (95 rows)

| column | example |
|---|---|
| claim_id | CLM00001 |
| partner_id | P1001 |
| scheme_id | SCHBLD001 |
| claimed_qty | 0 |
| claimed_amount | 33718.04 |
| claim_date | 2026-05-31 |
| status | ok |

### `schemes_master`  (12 rows)

| column | example |
|---|---|
| scheme_id | SCHBLD001 |
| industry_id | BLD |
| name | Summer Growth Booster - OPC RJ |
| archetype | growth |
| mode | QPS |
| qps_basis | value |
| slab_type | running |
| sku_scope | ["BLD-OPC53", "BLD-PPC"] |
| region_scope | Rajasthan |
| channel_tier | A/B/C |
| baseline_ref | trailing_12m |
| slab_json | [{"growth_pct": 5, "payout_pct": 1.0}, { |
| incentive_type | cash |
| start_date | 2025-12-01 |
| end_date | 2026-05-31 |
| budget | 4200000 |
| status | active |

### `secondary_sales`  (4,032 rows)

| column | example |
|---|---|
| txn_id | SO000001 |
| from_partner_id | P1001 |
| to_partner_id | P1002 |
| sku_code | BLD-OPC53 |
| qty | 85 |
| value | 32237.1 |
| sale_date | 2024-12-07 |

### `stock_position`  (4,032 rows)

| column | example |
|---|---|
| partner_id | P1001 |
| sku_code | BLD-OPC53 |
| month | 2024-12 |
| opening_stock | 56 |
| closing_stock | 70 |
| stock_in_transit | 7 |

### `targets`  (35 rows)

| column | example |
|---|---|
| partner_id | P1001 |
| scheme_id | nan |
| period | 2026-Q1 |
| target_qty | 2484 |
| target_value | 3400000 |
| base_year_value | 1500000 |

