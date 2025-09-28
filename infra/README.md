# AWS Deployment Overview

This folder will contain infrastructure-as-code and deployment helpers for the CobaltaX Monitor backend (audit + user directory + sync API).

## Target Architecture (Phase 1)

Services:
- API Gateway (HTTP API) -> Lambda functions
  - `POST /audit/batch`  (ingest audit events)
  - `GET /users`         (list / delta of users)
- DynamoDB Tables
  - `audit_events` (PK: tenant_id (string) == 'default', SK: ulid)
  - `users` (PK: username)
- Cognito User Pool (central authentication) (Phase 2)
- S3 (optional) for long term audit archive (Phase 2+)

## Files (planned)
- `template.yaml` (SAM/CloudFormation) OR `cdk/` (if we switch to CDK)
- `lambdas/` Python sources
- `deploy.sh` convenience wrapper: build + package + deploy

## Phasing Strategy
1. Phase 1: Minimal unauthenticated prototype (optionally a shared API key) to validate sync.
2. Phase 2: Add Cognito authorizer + token handling.
3. Phase 3: Add S3 archival + DynamoDB Streams -> S3 or Firehose.
4. Phase 4: Metrics / alarms (CloudWatch) + WAF (if public exposure needed).

## Security Notes
- NEVER hardcode secrets.
- Use Parameter Store / Secrets Manager for any API keys.
- Principle of least privilege IAM roles for Lambda.

---

Populate `template.yaml` next once customer AWS account specifics (region, naming conventions) are available.
