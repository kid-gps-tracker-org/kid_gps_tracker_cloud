#!/usr/bin/env python3
"""
ポーリング Lambda ハンドラ
nRF Cloud REST API からデバイスメッセージを取得し、DynamoDB に保存する。

ローカルモード (LOCAL_MODE=true):
  - ポーリング状態をローカルファイル (polling_state.json) で管理
  - 変換結果をコンソールに出力
  - DynamoDB への書き込みをスキップ

AWS モード (デフォルト):
  - ポーリング状態を DynamoDB PollingState テーブルで管理
  - 変換結果を DynamoDB DeviceMessages テーブルに書き込み
  - DeviceState テーブルを更新
"""
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nrf_cloud_client import NrfCloudClient
from message_transformer import transform_message, extract_device_state_update

logger = logging.getLogger(__name__)

# ローカルモードのポーリング状態ファイル
POLLING_STATE_FILE = Path(__file__).parent / "polling_state.json"

# 初回ポーリング時のデフォルト開始時刻（現在から何分前か）
DEFAULT_LOOKBACK_MINUTES = 5


def lambda_handler(event, context):
    """
    Lambda エントリーポイント

    Args:
        event: EventBridge イベント（ローカルモードでは空辞書）
        context: Lambda コンテキスト（ローカルモードでは None）

    Returns:
        処理結果サマリー
    """
    local_mode = os.environ.get("LOCAL_MODE", "false").lower() == "true"
    api_key = _get_api_key(local_mode)

    if not api_key:
        logger.error("NRF_CLOUD_API_KEY is not set")
        return {"statusCode": 500, "error": "API key not configured"}

    client = NrfCloudClient(api_key)

    # 1. 前回のポーリングタイムスタンプを取得
    last_poll_timestamp = _get_last_poll_timestamp(local_mode)
    logger.info(f"Polling messages since: {last_poll_timestamp}")

    # 2. nRF Cloud API からメッセージ取得
    try:
        messages = client.get_all_messages(inclusive_start=last_poll_timestamp)
    except Exception as e:
        logger.error(f"Failed to fetch messages from nRF Cloud: {e}")
        return {"statusCode": 502, "error": str(e)}

    if not messages:
        logger.info("No new messages")
        return {"statusCode": 200, "messagesProcessed": 0}

    logger.info(f"Fetched {len(messages)} messages from nRF Cloud")

    # 3. メッセージ変換
    records = []
    device_state_updates = {}
    latest_received_at = last_poll_timestamp

    for raw_message in messages:
        record = transform_message(raw_message)
        if record:
            records.append(record)

            # DeviceState 更新データを蓄積（デバイスごとに最新のみ保持）
            state_update = extract_device_state_update(record)
            if state_update:
                device_id = state_update["deviceId"]
                if device_id not in device_state_updates:
                    device_state_updates[device_id] = state_update
                else:
                    _merge_device_state(device_state_updates[device_id], state_update)

        # 最新の receivedAt を追跡
        received_at = raw_message.get("receivedAt", "")
        if received_at > latest_received_at:
            latest_received_at = received_at

    gnss_count = sum(1 for r in records if r["messageType"] == "GNSS")
    ground_fix_count = sum(1 for r in records if r["messageType"] == "GROUND_FIX")
    temp_count = sum(1 for r in records if r["messageType"] == "TEMP")
    logger.info(
        f"Transformed {len(records)} records "
        f"(GNSS: {gnss_count}, GROUND_FIX: {ground_fix_count}, TEMP: {temp_count})"
    )

    # 4. 結果出力
    if local_mode:
        _output_local(records, device_state_updates)
    else:
        _write_to_dynamodb(records, device_state_updates)

    # 5. ポーリングタイムスタンプ更新
    _update_last_poll_timestamp(latest_received_at, len(records), local_mode)

    return {
        "statusCode": 200,
        "messagesProcessed": len(records),
        "devicesUpdated": len(device_state_updates),
        "lastReceivedAt": latest_received_at,
    }


def _get_api_key(local_mode: bool) -> str:
    """API キーを取得する"""
    if local_mode:
        return os.environ.get("NRF_CLOUD_API_KEY", "")
    else:
        # AWS モード: Secrets Manager から取得
        secret_arn = os.environ.get("NRF_CLOUD_API_KEY_SECRET_ARN")
        if secret_arn:
            import boto3
            client = boto3.client("secretsmanager")
            response = client.get_secret_value(SecretId=secret_arn)
            return response["SecretString"]
        return os.environ.get("NRF_CLOUD_API_KEY", "")


def _get_last_poll_timestamp(local_mode: bool) -> str:
    """前回のポーリングタイムスタンプを取得する"""
    if local_mode:
        return _get_last_poll_timestamp_local()
    else:
        return _get_last_poll_timestamp_dynamodb()


def _get_last_poll_timestamp_local() -> str:
    """ローカルファイルからポーリングタイムスタンプを取得"""
    if POLLING_STATE_FILE.exists():
        with open(POLLING_STATE_FILE, "r") as f:
            state = json.load(f)
            return state.get("lastPollTimestamp", _default_start_timestamp())
    return _default_start_timestamp()


def _get_last_poll_timestamp_dynamodb() -> str:
    """DynamoDB からポーリングタイムスタンプを取得"""
    import boto3
    table_name = os.environ.get("POLLING_STATE_TABLE", "PollingState")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    response = table.get_item(Key={"configKey": "polling"})
    item = response.get("Item")
    if item:
        return item.get("lastPollTimestamp", _default_start_timestamp())
    return _default_start_timestamp()


def _update_last_poll_timestamp(timestamp: str, message_count: int, local_mode: bool):
    """ポーリングタイムスタンプを更新する"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    if local_mode:
        state = {
            "lastPollTimestamp": timestamp,
            "lastPollExecutedAt": now,
            "messageCount": message_count,
        }
        with open(POLLING_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"Updated polling state: {POLLING_STATE_FILE}")
    else:
        import boto3
        table_name = os.environ.get("POLLING_STATE_TABLE", "PollingState")
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        table.put_item(Item={
            "configKey": "polling",
            "lastPollTimestamp": timestamp,
            "lastPollExecutedAt": now,
            "messageCount": message_count,
        })


def _output_local(records, device_state_updates):
    """ローカルモード: 変換結果をコンソールに出力"""
    print("\n" + "=" * 70)
    print("  DeviceMessages Records")
    print("=" * 70)

    for record in records:
        msg_type = record["messageType"]
        device_id = record["deviceId"]
        timestamp = record["timestamp"]

        if msg_type in ("GNSS", "GROUND_FIX"):
            source = f" ({record.get('fulfilledWith', '')})" if record.get("fulfilledWith") else ""
            print(
                f"  [{msg_type}] {device_id} | {timestamp} | "
                f"lat={record['lat']}, lon={record['lon']}, "
                f"acc={record.get('accuracy', 'N/A')}{source}"
            )
        elif msg_type == "TEMP":
            print(
                f"  [{msg_type}] {device_id} | {timestamp} | "
                f"temp={record['temperature']}C"
            )

    print("\n" + "=" * 70)
    print("  DeviceState Updates")
    print("=" * 70)

    for device_id, state in device_state_updates.items():
        print(f"  Device: {device_id}")
        if "lastLocation" in state:
            loc = state["lastLocation"]
            print(f"    Location: lat={loc['lat']}, lon={loc['lon']}")
        if "lastTemperature" in state:
            temp = state["lastTemperature"]
            print(f"    Temperature: {temp['value']}C")
        print(f"    Last seen: {state['lastSeen']}")

    print("=" * 70 + "\n")


def _write_to_dynamodb(records, device_state_updates):
    """AWS モード: DynamoDB にレコードを書き込む"""
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


def _default_start_timestamp() -> str:
    """初回ポーリング時のデフォルト開始タイムスタンプ"""
    dt = datetime.now(timezone.utc) - timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
