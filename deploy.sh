#!/usr/bin/env bash
# PromoLens AI — one-shot deploy from Cloud Shell.
# Usage:  bash deploy.sh [PROJECT_ID] [REGION]
set -euo pipefail

PROJECT="${1:-august-apogee-382815}"
REGION="${2:-asia-south1}"
DATASET="promolens_db"
SERVICE="promolens-api"

echo "==> project=$PROJECT region=$REGION"
gcloud config set project "$PROJECT"

echo "==> [1/6] enabling APIs (one-time, ~1-2 min)"
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

echo "==> [2/6] generating synthetic data"
pip3 install --user -q numpy pandas faker
( cd data && python3 generate_synthetic_data.py && python3 generate_scheme_docs.py )

echo "==> [3/6] loading BigQuery dataset '$DATASET'"
bash sql/load_bigquery.sh "$PROJECT" "$DATASET" "$REGION"

echo "==> [4/6] deploying API to Cloud Run"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --allow-unauthenticated \
  --set-env-vars "PROMOLENS_BACKEND=bigquery,PROMOLENS_PROJECT=$PROJECT,PROMOLENS_BQ_DATASET=$DATASET,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=$REGION,PROMOLENS_MODEL=gemini-2.5-flash,PROMOLENS_EMBED_LOCATION=us-central1,PROMOLENS_EMBED_MODEL=text-embedding-005" \
  --memory 1Gi --timeout 300

RUN_URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo "==> Cloud Run URL: $RUN_URL"

echo "==> [5/6] wiring UI to the API"
sed -i "s#window.PROMOLENS_API || #window.PROMOLENS_API || \"$RUN_URL\" || #" ui/public/index.html || true

echo "==> [6/6] deploying UI to Firebase Hosting"
echo "    (run once if needed:)  npm i -g firebase-tools && firebase login --no-localhost"
echo "    then:  firebase use $PROJECT && (cd ui && firebase deploy --only hosting)"

echo "==> smoke test:"
curl -s -X POST "$RUN_URL/chat" -H 'Content-Type: application/json' \
  -d '{"message":"Which building-materials schemes gave the best ROI?"}' | head -c 600
echo; echo "==> done."
