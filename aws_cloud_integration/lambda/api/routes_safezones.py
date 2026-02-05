"""
セーフゾーンエンドポイント
API 仕様書 4.5, 4.6, 4.7 に基づく。

GET    /devices/{deviceId}/safezones
PUT    /devices/{deviceId}/safezones
DELETE /devices/{deviceId}/safezones/{zoneId}
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from response_utils import success_response, error_response
from validators import (
    get_device_id,
    get_zone_id,
    parse_json_body,
    validate_safezone_create,
    validate_safezone_update,
)

logger = logging.getLogger(__name__)


def _get_safe_zones_table():
    """SafeZones テーブルリソースを取得する。"""
    table_name = os.environ.get("SAFE_ZONES_TABLE", "SafeZones")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def _get_device_state_table():
    """DeviceState テーブルリソースを取得する（存在チェック用）。"""
    table_name = os.environ.get("DEVICE_STATE_TABLE", "DeviceState")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def _now_iso8601() -> str:
    """現在時刻を ISO 8601 形式で取得する。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_safezones(event: dict) -> dict:
    """
    GET /devices/{deviceId}/safezones
    指定デバイスのセーフゾーン一覧を取得する。
    API 仕様書 4.5 に基づく。

    Response: { "deviceId": "...", "safezones": [SafeZone] }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    # デバイス存在チェック
    state_table = _get_device_state_table()
    device_response = state_table.get_item(Key={"deviceId": device_id})
    if "Item" not in device_response:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    # セーフゾーン一覧取得
    table = _get_safe_zones_table()
    response = table.query(
        KeyConditionExpression=Key("deviceId").eq(device_id)
    )
    items = response.get("Items", [])

    safezones = [_format_safezone(item) for item in items]

    return success_response(200, {
        "deviceId": device_id,
        "safezones": safezones,
    })


def put_safezone(event: dict) -> dict:
    """
    PUT /devices/{deviceId}/safezones
    セーフゾーンを作成または更新する。
    API 仕様書 4.6 に基づく。

    - zoneId を省略 → 新規作成 (サーバーが UUID を生成)
    - zoneId を指定 → 既存ゾーンの更新

    Request body: { "zoneId"?, "name", "center": {"lat", "lon"}, "radius", "enabled"? }
    Response: { "deviceId": "...", "safezone": SafeZone }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    # デバイス存在チェック
    state_table = _get_device_state_table()
    device_response = state_table.get_item(Key={"deviceId": device_id})
    if "Item" not in device_response:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    # リクエストボディパース
    body, parse_error = parse_json_body(event)
    if parse_error:
        return error_response(400, "INVALID_REQUEST", parse_error)

    zone_id = body.get("zoneId")
    is_create = zone_id is None

    if is_create:
        # 新規作成
        return _create_safezone(device_id, body)
    else:
        # 更新
        return _update_safezone(device_id, zone_id, body)


def _create_safezone(device_id: str, body: dict) -> dict:
    """セーフゾーンを新規作成する。"""
    # バリデーション
    error = validate_safezone_create(body)
    if error:
        error_code = _get_validation_error_code(error)
        return error_response(400, error_code, error)

    zone_id = str(uuid.uuid4())
    now = _now_iso8601()

    item = {
        "deviceId": device_id,
        "zoneId": zone_id,
        "name": body["name"],
        "center": {
            "lat": Decimal(str(body["center"]["lat"])),
            "lon": Decimal(str(body["center"]["lon"])),
        },
        "radius": Decimal(str(body["radius"])),
        "enabled": body.get("enabled", True),
        "createdAt": now,
        "updatedAt": now,
    }

    table = _get_safe_zones_table()
    table.put_item(Item=item)

    return success_response(201, {
        "deviceId": device_id,
        "safezone": _format_safezone(item),
    })


def _update_safezone(device_id: str, zone_id: str, body: dict) -> dict:
    """既存セーフゾーンを更新する。"""
    table = _get_safe_zones_table()

    # 存在チェック
    existing = table.get_item(Key={"deviceId": device_id, "zoneId": zone_id})
    if "Item" not in existing:
        return error_response(404, "ZONE_NOT_FOUND",
                              f"Safe zone '{zone_id}' not found")

    # バリデーション（更新用）
    error = validate_safezone_update(body)
    if error:
        error_code = _get_validation_error_code(error)
        return error_response(400, error_code, error)

    # 更新式を構築
    update_parts = ["#updatedAt = :updatedAt"]
    expr_names = {"#updatedAt": "updatedAt"}
    expr_values = {":updatedAt": _now_iso8601()}

    if "name" in body:
        update_parts.append("#name = :name")
        expr_names["#name"] = "name"
        expr_values[":name"] = body["name"]

    if "center" in body:
        update_parts.append("#center = :center")
        expr_names["#center"] = "center"
        expr_values[":center"] = {
            "lat": Decimal(str(body["center"]["lat"])),
            "lon": Decimal(str(body["center"]["lon"])),
        }

    if "radius" in body:
        update_parts.append("#radius = :radius")
        expr_names["#radius"] = "radius"
        expr_values[":radius"] = Decimal(str(body["radius"]))

    if "enabled" in body:
        update_parts.append("#enabled = :enabled")
        expr_names["#enabled"] = "enabled"
        expr_values[":enabled"] = body["enabled"]

    # 更新実行
    response = table.update_item(
        Key={"deviceId": device_id, "zoneId": zone_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )

    updated_item = response["Attributes"]

    return success_response(200, {
        "deviceId": device_id,
        "safezone": _format_safezone(updated_item),
    })


def delete_safezone(event: dict) -> dict:
    """
    DELETE /devices/{deviceId}/safezones/{zoneId}
    指定セーフゾーンを削除する。
    API 仕様書 4.7 に基づく。

    Response: { "deleted": true, "zoneId": "..." }
    """
    device_id = get_device_id(event)
    zone_id = get_zone_id(event)

    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")
    if not zone_id:
        return error_response(400, "INVALID_REQUEST", "zoneId is required")

    # デバイス存在チェック
    state_table = _get_device_state_table()
    device_response = state_table.get_item(Key={"deviceId": device_id})
    if "Item" not in device_response:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    table = _get_safe_zones_table()

    # ゾーン存在チェック
    existing = table.get_item(Key={"deviceId": device_id, "zoneId": zone_id})
    if "Item" not in existing:
        return error_response(404, "ZONE_NOT_FOUND",
                              f"Safe zone '{zone_id}' not found")

    # 削除
    table.delete_item(Key={"deviceId": device_id, "zoneId": zone_id})

    return success_response(200, {
        "deleted": True,
        "zoneId": zone_id,
    })


def _format_safezone(item: dict) -> dict:
    """
    SafeZones アイテムを SafeZone 型 (API 仕様書 3.4) にフォーマットする。
    """
    center = item.get("center", {})
    return {
        "zoneId": item.get("zoneId"),
        "name": item.get("name"),
        "center": {
            "lat": center.get("lat"),
            "lon": center.get("lon"),
        },
        "radius": item.get("radius"),
        "enabled": item.get("enabled", True),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
    }


def _get_validation_error_code(error_message: str) -> str:
    """エラーメッセージからエラーコードを判定する。"""
    if "Required field" in error_message:
        return "MISSING_REQUIRED_FIELD"
    if "Latitude" in error_message or "longitude" in error_message:
        return "INVALID_COORDINATE"
    if "Radius" in error_message:
        return "INVALID_RADIUS"
    if "Zone name" in error_message:
        return "INVALID_ZONE_NAME"
    return "INVALID_REQUEST"
