#!/usr/bin/env python3
"""
Webhook Lambda ハンドラ
nRF Cloud Message Routing からのWebhookを受信し、DynamoDB に保存する。

nRF Cloud がデバイスメッセージをリアルタイムにPOSTしてくる。
Function URL 経由で受信し、既存の message_transformer で変換後、DynamoDB に書き込む。
"""
import os
import json
import logging

from message_transformer import transform_message, extract_device_state_update

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TEAM_ID = os.environ.get("NRF_CLOUD_TEAM_ID", "")


def lambda_handler(event, context):
    """
    Lambda エントリーポイント (Function URL)

    nRF Cloud Message Routing からのPOSTリクエストを処理する。
    - type: "system.verification" → 検証応答
    - type: "device.messages" → メッセージ処理・DynamoDB書き込み
    """
    logger.info(f"Received webhook event")

    body = event.get("body", "")
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse body: {e}")
        return _response(400, {"error": "Invalid JSON"})

    payload_type = payload.get("type", "")
    logger.info(f"Payload type: {payload_type}")

    # 検証リクエスト
    if payload_type == "system.verification":
        logger.info("Handling system verification request")
        return _response(200, {"message": "OK"})

    # デバイスメッセージ
    if payload_type == "device.messages":
        return _process_device_messages(payload)

    logger.warning(f"Unknown payload type: {payload_type}")
    return _response(200, {"message": "OK", "skipped": True})


def _process_device_messages(payload: dict) -> dict:
    """デバイスメッセージを処理してDynamoDBに保存する"""
    messages = payload.get("messages", [])
    logger.info(f"Processing {len(messages)} messages")

    records = []
    device_state_updates = {}

    for raw_message in messages:
        try:
            record = transform_message(raw_message)
        except Exception as e:
            logger.warning(f"Failed to transform message: {e}")
            record = None

        if record:
            records.append(record)

            state_update = extract_device_state_update(record)
            if state_update:
                device_id = state_update["deviceId"]
                if device_id not in device_state_updates:
                    device_state_updates[device_id] = state_update
                else:
                    _merge_device_state(device_state_updates[device_id], state_update)

    gnss_count = sum(1 for r in records if r["messageType"] == "GNSS")
    ground_fix_count = sum(1 for r in records if r["messageType"] == "GROUND_FIX")
    temp_count = sum(1 for r in records if r["messageType"] == "TEMP")
    logger.info(
        f"Transformed {len(records)} records "
        f"(GNSS: {gnss_count}, GROUND_FIX: {ground_fix_count}, TEMP: {temp_count})"
    )

    if records:
        _write_to_dynamodb(records, device_state_updates)

    return _response(200, {
        "message": "OK",
        "messagesProcessed": len(records),
        "devicesUpdated": len(device_state_updates),
    })


def _response(status_code: int, body: dict) -> dict:
    """Function URL レスポンスを構築する（nRF Cloud検証用ヘッダー付き）"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "x-nrfcloud-team-id": TEAM_ID,
        },
        "body": json.dumps(body),
    }


def _write_to_dynamodb(records, device_state_updates):
    """DynamoDB にレコードを書き込む"""
    import boto3
    from botocore.exceptions import ClientError

    dynamodb = boto3.resource("dynamodb")

    # DeviceMessages テーブルへの書き込み
    messages_table_name = os.environ.get("DEVICE_MESSAGES_TABLE", "DeviceMessages")
    messages_table = dynamodb.Table(messages_table_name)

    written = 0
    for record in records:
        try:
            messages_table.put_item(
                Item=record,
                ConditionExpression="attribute_not_exists(deviceId) AND attribute_not_exists(#ts)",
                ExpressionAttributeNames={"#ts": "timestamp"},
            )
            written += 1
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.debug(f"Duplicate record skipped: {record['deviceId']} {record['timestamp']}")
            else:
                logger.error(f"DynamoDB write error: {e}")

    logger.info(f"Wrote {written}/{len(records)} records to {messages_table_name}")

    # DeviceState テーブルの更新
    state_table_name = os.environ.get("DEVICE_STATE_TABLE", "DeviceState")
    state_table = dynamodb.Table(state_table_name)

    for device_id, state in device_state_updates.items():
        try:
            update_expr_parts = ["#updatedAt = :updatedAt", "#lastSeen = :lastSeen"]
            expr_names = {
                "#updatedAt": "updatedAt",
                "#lastSeen": "lastSeen",
            }
            expr_values = {
                ":updatedAt": state["updatedAt"],
                ":lastSeen": state["lastSeen"],
            }

            if "lastLocation" in state:
                update_expr_parts.append("#lastLocation = :lastLocation")
                expr_names["#lastLocation"] = "lastLocation"
                expr_values[":lastLocation"] = state["lastLocation"]

            if "lastTemperature" in state:
                update_expr_parts.append("#lastTemperature = :lastTemperature")
                expr_names["#lastTemperature"] = "lastTemperature"
                expr_values[":lastTemperature"] = state["lastTemperature"]

            state_table.update_item(
                Key={"deviceId": device_id},
                UpdateExpression="SET " + ", ".join(update_expr_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
        except ClientError as e:
            logger.error(f"DeviceState update error for {device_id}: {e}")

    logger.info(f"Updated {len(device_state_updates)} device states")


def _merge_device_state(existing: dict, new: dict):
    """同一デバイスの DeviceState 更新をマージする（最新のみ保持）"""
    if "lastLocation" in new:
        existing["lastLocation"] = new["lastLocation"]
    if "lastTemperature" in new:
        existing["lastTemperature"] = new["lastTemperature"]
    existing["lastSeen"] = new["lastSeen"]
    existing["updatedAt"] = new["updatedAt"]
