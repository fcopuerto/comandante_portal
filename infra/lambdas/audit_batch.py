import os
import json
import time
import uuid
import datetime
import boto3

dynamodb = boto3.resource('dynamodb')
AUDIT_TABLE = os.environ.get('AUDIT_TABLE', 'audit_events')
TENANT_ID = os.environ.get('TENANT_ID', 'default')


def _now_iso():
    return datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'


def lambda_handler(event, context):
    """Ingest a batch of audit events.

    Expected body JSON: {"events": [{"local_id": int|str, "ts": iso8601?, "event": str, "user": str, "details": {...}}]}
    Adds server ulid/uuid, normalizes timestamp if missing.
    Returns accepted local_ids and rejected with errors.
    """
    try:
        body = event.get('body') or '{}'
        if event.get('isBase64Encoded'):
            import base64
            body = base64.b64decode(body).decode('utf-8')
        payload = json.loads(body)
    except Exception as e:
        return {"statusCode": 400, "body": json.dumps({"error": f"invalid_json: {e}"})}

    events = payload.get('events') or []
    if not isinstance(events, list):
        return {"statusCode": 400, "body": json.dumps({"error": "events_not_list"})}

    table = dynamodb.Table(AUDIT_TABLE)
    accepted = []
    rejected = []

    with table.batch_writer(overwrite_by_pkeys=['tenant_id', 'id']) as batch:
        for ev in events:
            try:
                local_id = ev.get('local_id')
                evt_name = ev.get('event')
                if not evt_name:
                    raise ValueError('missing event')
                ts = ev.get('ts') or _now_iso()
                # Use uuid4 for now (ULID later)
                item_id = str(uuid.uuid4())
                item = {
                    'tenant_id': TENANT_ID,
                    'id': item_id,
                    'ts': ts,
                    'event': evt_name,
                    'user': ev.get('user'),
                    'details': ev.get('details') or {},
                    'source_host': ev.get('source_host'),
                    'client_local_id': str(local_id) if local_id is not None else None,
                    'ingested_at': _now_iso()
                }
                batch.put_item(Item=item)
                accepted.append(local_id)
            except Exception as ex:  # per-event failure shouldn't abort all
                rejected.append(
                    {"local_id": ev.get('local_id'), "error": str(ex)})

    return {
        "statusCode": 200,
        "body": json.dumps({"accepted": accepted, "rejected": rejected})
    }
