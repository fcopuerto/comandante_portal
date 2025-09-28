#!/usr/bin/env bash
set -euo pipefail
STACK_NAME=${STACK_NAME:-cobaltax-monitor-backend}
REGION=${AWS_REGION:-eu-west-1}
STAGE=${STAGE:-dev}
TENANT_ID=${TENANT_ID:-default}
ARTIFACT_BUCKET=${ARTIFACT_BUCKET:-}

if [ -z "${ARTIFACT_BUCKET}" ]; then
  echo "You must set ARTIFACT_BUCKET (pre-created S3 bucket for SAM artifacts)." >&2
  exit 1
fi

sam build --use-container
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --s3-bucket "$ARTIFACT_BUCKET" \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --parameter-overrides StageName=$STAGE TenantId=$TENANT_ID

sam describe stack --stack-name "$STACK_NAME" --region "$REGION" || true
