#!/usr/bin/env bash
# PromoLens AI — load synthetic CSVs into BigQuery (run in Cloud Shell).
# Prereq: a project with billing enabled, BigQuery API on.
set -euo pipefail

PROJECT="${1:-august-apogee-382815}"
DATASET="${2:-promolens_db}"
LOCATION="${3:-asia-south1}"   # Mumbai

echo ">> project=$PROJECT dataset=$DATASET location=$LOCATION"
gcloud config set project "$PROJECT"

# create dataset (idempotent)
bq --location="$LOCATION" mk -d --description "PromoLens synthetic trade-promotion data" "$PROJECT:$DATASET" 2>/dev/null || true

# load every CSV with schema autodetect (header row present)
for f in csv/*.csv; do
  [ -e "$f" ] || continue
  base="$(basename "$f" .csv)"
  [[ "$base" == _* ]] && continue   # skip _planted_needles.json etc
  echo ">> loading $base"
  bq load --replace --autodetect --source_format=CSV --skip_leading_rows=1 \
     "$PROJECT:$DATASET.$base" "$f"
done

echo ">> done. sample check:"
bq query --use_legacy_sql=false \
"SELECT status, COUNT(*) schemes FROM \`$PROJECT.$DATASET.schemes_master\` GROUP BY status"
