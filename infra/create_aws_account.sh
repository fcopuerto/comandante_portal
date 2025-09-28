#!/bin/bash

# === CONFIGURATION ===
ACCOUNT_NAME="anemona_dev"
ACCOUNT_EMAIL="anemona_dev@example.com"  # must be unique across AWS
IAM_ROLE_NAME="OrganizationAccountAccessRole"

# === CREATE ACCOUNT ===
echo "Creating AWS account: $ACCOUNT_NAME"
CREATE_ID=$(aws organizations create-account \
  --email "$ACCOUNT_EMAIL" \
  --account-name "$ACCOUNT_NAME" \
  --role-name "$IAM_ROLE_NAME" \
  --query 'CreateAccountStatus.Id' \
  --output text)

echo "CreateAccountStatusId: $CREATE_ID"

# === WAIT FOR COMPLETION ===
echo "Waiting for account creation to complete..."
while true; do
  STATUS=$(aws organizations describe-create-account-status \
    --create-account-request-id "$CREATE_ID" \
    --query 'CreateAccountStatus.State' \
    --output text)

  if [ "$STATUS" == "SUCCEEDED" ]; then
    ACCOUNT_ID=$(aws organizations describe-create-account-status \
      --create-account-request-id "$CREATE_ID" \
      --query 'CreateAccountStatus.AccountId' \
      --output text)
    echo "✅ Account created successfully: $ACCOUNT_ID"
    break
  elif [ "$STATUS" == "FAILED" ]; then
    FAILURE_REASON=$(aws organizations describe-create-account-status \
      --create-account-request-id "$CREATE_ID" \
      --query 'CreateAccountStatus.FailureReason' \
      --output text)
    echo "❌ Account creation failed: $FAILURE_REASON"
    exit 1
  else
    echo "Status: $STATUS... waiting 10s"
    sleep 10
  fi
done
