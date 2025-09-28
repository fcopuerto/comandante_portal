import os
import json
import datetime
import boto3

dynamodb = boto3.resource('dynamodb')
USERS_TABLE = os.environ.get('USERS_TABLE', 'users')
TENANT_ID = os.environ.get('TENANT_ID', 'default')

# For future optimization: maintain a meta row with global version. Here we just return full set.


def lambda_handler(event, context):
    table = dynamodb.Table(USERS_TABLE)
    # Simple full scan (OK for small user counts); replace with Query + key design if multi-tenant scaling needed.
    items = []
    response = table.scan()
    items.extend(response.get('Items', []))
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response.get('Items', []))

    # Strip sensitive fields beyond password_hash if you later add more
    users = [
        {
            'username': it.get('username'),
            'password_hash': it.get('password_hash'),
            'roles': it.get('roles', []),
            'version': it.get('version', 0),
            'disabled': it.get('disabled', False)
        }
        for it in items if it.get('tenant_id', TENANT_ID) == TENANT_ID
    ]

    return {"statusCode": 200, "body": json.dumps({"users": users})}
