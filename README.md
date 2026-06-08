# PromoLens AI — working core

Trade Promotion Intelligence Copilot. Built for Gen AI Academy APAC 2026 (Cohort 2).
**No customer data** — everything runs on synthetic data.

## What's here

```
promolens/
├── data/
│   ├── generate_synthetic_data.py   # seeded generator (3 fictional firms, 12 tables)
│   ├── csv/                          # generated dataset + _planted_needles.json
│   └── data_dictionary.md            # tables, columns, planted needles
├── engine/
│   └── tools.py                      # deterministic reasoning tools (the moat)
├── tests/
│   └── prove.py                      # runs 6 hero queries, asserts all 8 needles
├── sql/
│   └── load_bigquery.sh              # load CSVs to BigQuery (Cloud Shell)
├── agents/                           # ADK agents (next increment)
└── api/                              # FastAPI for Cloud Run (next increment)
```

## Prove it works locally (no cloud needed)

```bash
cd promolens/data && python3 generate_synthetic_data.py
cd ../tests && python3 prove.py        # -> all needles PASS
```

## Reasoning tools (`engine/tools.py`)

| Tool | Answers |
|---|---|
| `rank_schemes_by_roi` / `scheme_roi` | which schemes worked vs gave away margin (baseline + uplift) |
| `why_not_applied` / `scheme_state_view` | did a scheme apply? what's active/expired/orphaned |
| `inventory_loading_leaks` | high sell-in + flat sell-out (primary vs secondary) |
| `overclaims` | claims above earned entitlement |
| `stacked_effective_discount` | true effective discount when schemes stack |
| `slab_accrual` | Running / Step / Fixed / Linear payout math |
| `data_trust_summary` | master-sync failures in plain English |
| `cannibalisation` | adjacent-SKU impact during a promo |
| `whatif_simulator` | projected payout & ROI before launch (in-build) |

## Cloud (driven next, with your billing/credential steps)

1. Enable billing + APIs (Vertex AI, BigQuery, Cloud Run) — *human-only*.
2. `cd promolens && bash sql/load_bigquery.sh` in Cloud Shell.
3. ADK agents wrap the same `engine/tools.py` functions; FastAPI on Cloud Run; React chat UI on Firebase.
