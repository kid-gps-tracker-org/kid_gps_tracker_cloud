"""
履歴エンドポイント
API 仕様書 4.4 に基づく。

GET /devices/{deviceId}/history
"""
import os
import logging
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from response_utils import success_response, error_response
from validators import get_device_id, validate_history_params

logger = logging.getLogger(__name__)


def _get_device_messages_table():
    """DeviceMessages テーブルリソースを取得する。"""
    table_name = os.environ.get("DEVICE_MESSAGES_TABLE", "DeviceMessages")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def _get_device_state_table():
    """DeviceState テーブルリソースを取得する（存在チェック用）。"""
    table_name = os.environ.get("DEVICE_STATE_TABLE", "DeviceState")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def get_device_history(event: dict) -> dict:
    """
    GET /devices/{deviceId}/history
    位置・温度の履歴を取得する。
    API 仕様書 4.4 に基づく。

    クエリパラメータ:
        type: GNSS / GROUND_FIX / TEMP (省略時は全種別)
        start: 開始時刻 (ISO 8601、デフォルト: 24時間前)
        end: 終了時刻 (ISO 8601、デフォルト: 現在時刻)
        limit: 最大件数 (1-1000、デフォルト: 100)

    Response: { "deviceId": "...", "history": [HistoryEntry], "count": N }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    # パラメータバリデーション
    params, error = validate_history_params(event)
    if error:
        if "start" in error.lower() and "end" in error.lower():
            return error_response(400, "INVALID_TIME_RANGE", error)
        return error_response(400, "INVALID_PARAMETER", error)

    msg_type = params["type"]
    start = params["start"]
    end = params["end"]
    limit = params["limit"]

    # デフォルト値設定
    if not end:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if not start:
        start_dt = datetime.now(timezone.utc) - timedelta(hours=24)
        start = start_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # デバイス存在チェック
    state_table = _get_device_state_table()
    device_response = state_table.get_item(Key={"deviceId": device_id})
    if "Item" not in device_response:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    # 履歴取得
    table = _get_device_messages_table()
    items = _query_history(table, device_id, msg_type, start, end, limit)

    # フォーマット
    history = [_format_history_entry(item) for item in items]

    return success_response(200, {
        "deviceId": device_id,
        "history": history,
        "count": len(history),
    })


def _query_history(table, device_id: str, msg_type: str, start: str, end: str, limit: int) -> list:
    """
    DeviceMessages テーブルから履歴を取得する。
    timestamp 降順（新しい順）で返す。
    """
    # キー条件: deviceId = X AND timestamp BETWEEN start AND end
    key_condition = Key("deviceId").eq(device_id) & Key("timestamp").between(start, end)

    query_kwargs = {
        "KeyConditionExpression": key_condition,
        "ScanIndexForward": False,  # 降順（新しい順）
        "Limit": limit,
    }

    # type フィルタがある場合は FilterExpression を追加
    if msg_type:
        query_kwargs["FilterExpression"] = "#mt = :mt"
        query_kwargs["ExpressionAttributeNames"] = {"#mt": "messageType"}
        query_kwargs["ExpressionAttributeValues"] = {":mt": msg_type}

    all_items = []

    # FilterExpression がある場合、Limit は読み取り件数に適用されるため
    # フィルタ後の件数が limit 未満になる可能性がある。
    # 必要に応じてページネーションで追加取得する。
    while True:
        response = table.query(**query_kwargs)
        items = response.get("Items", [])
        all_items.extend(items)

        if len(all_items) >= limit:
            break

        if "LastEvaluatedKey" not in response:
            break

        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    # limit を超えた場合は切り詰め
    return all_items[:limit]


def _format_history_entry(item: dict) -> dict:
    """
    DeviceMessages アイテムを HistoryEntry 型 (API 仕様書 3.6) にフォーマットする。
    messageType によって null フィールドが異なる。
    """
    msg_type = item.get("messageType")

    if msg_type in ("GNSS", "GROUND_FIX"):
        return {
            "timestamp": item.get("timestamp"),
            "messageType": msg_type,
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "accuracy": item.get("accuracy"),
            "temperature": None,
        }
    elif msg_type == "TEMP":
        return {
            "timestamp": item.get("timestamp"),
            "messageType": msg_type,
            "lat": None,
            "lon": None,
            "accuracy": None,
            "temperature": item.get("temperature"),
        }
    else:
        # 未知の messageType
        return {
            "timestamp": item.get("timestamp"),
            "messageType": msg_type,
            "lat": None,
            "lon": None,
            "accuracy": None,
            "temperature": None,
        }
