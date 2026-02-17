"""
デバイス系エンドポイント
API 仕様書 4.1, 4.2, 4.3 に基づく。

GET /devices
GET /devices/{deviceId}/location
GET /devices/{deviceId}/temperature
"""
import os
import logging
from datetime import datetime, timezone, timedelta

import boto3

from response_utils import success_response, error_response
from validators import get_device_id

# GNSS データがこの時間より古い場合、GROUND_FIX にフォールバックする
# GNSS は約 5 分間隔で届くため、2 回分 (10 分) 届いていなければ屋内とみなす
_GNSS_STALE_THRESHOLD_MINUTES = 10


def _is_stale(location: dict) -> bool:
    """
    位置情報のタイムスタンプが _GNSS_STALE_THRESHOLD_MINUTES 分以上古ければ True を返す。
    タイムスタンプが取得できない場合は古くないとみなす（フォールバックしない）。
    """
    ts = location.get("timestamp")
    if not ts:
        return False
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            threshold = datetime.now(timezone.utc) - timedelta(minutes=_GNSS_STALE_THRESHOLD_MINUTES)
            return dt < threshold
        except ValueError:
            continue
    return False

logger = logging.getLogger(__name__)


def _get_device_state_table():
    """DeviceState テーブルリソースを取得する。"""
    table_name = os.environ.get("DEVICE_STATE_TABLE", "DeviceState")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def get_devices(event: dict) -> dict:
    """
    GET /devices
    デバイス一覧と各デバイスの最新状態を取得する。
    API 仕様書 4.1 に基づく。

    Response: { "devices": [Device] }
    """
    table = _get_device_state_table()

    # Scan でデバイス一覧を取得（ページネーション対応）
    response = table.scan()
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    devices = [_format_device(item) for item in items]

    return success_response(200, {"devices": devices})


def get_device_location(event: dict) -> dict:
    """
    GET /devices/{deviceId}/location
    指定デバイスの最新位置情報を取得する。
    API 仕様書 4.2 に基づく。

    Response: { "deviceId": "...", "location": Location }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    table = _get_device_state_table()
    response = table.get_item(Key={"deviceId": device_id})
    item = response.get("Item")

    if not item:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    last_location = item.get("lastLocation")
    if not last_location or _is_stale(last_location):
        # GNSS がない、または古すぎる場合はセルラー測位にフォールバック (source="GROUND_FIX")
        ground_fix = item.get("lastGroundFixLocation")
        if ground_fix:
            last_location = ground_fix
    if not last_location:
        return error_response(404, "NO_LOCATION_DATA",
                              "No location data available for device")

    return success_response(200, {
        "deviceId": device_id,
        "location": _format_location(last_location),
    })


def get_device_temperature(event: dict) -> dict:
    """
    GET /devices/{deviceId}/temperature
    指定デバイスの最新温度情報を取得する。
    API 仕様書 4.3 に基づく。

    Response: { "deviceId": "...", "temperature": Temperature }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    table = _get_device_state_table()
    response = table.get_item(Key={"deviceId": device_id})
    item = response.get("Item")

    if not item:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    last_temp = item.get("lastTemperature")
    if not last_temp:
        return error_response(404, "NO_TEMPERATURE_DATA",
                              "No temperature data available for device")

    return success_response(200, {
        "deviceId": device_id,
        "temperature": _format_temperature(last_temp),
    })


def _format_device(item: dict) -> dict:
    """
    DeviceState アイテムを Device 型 (API 仕様書 3.5) にフォーマットする。
    null ハンドリング: 値がない場合は null を返す。キーは省略しない。
    """
    last_location = item.get("lastLocation")
    if not last_location or _is_stale(last_location):
        ground_fix = item.get("lastGroundFixLocation")
        if ground_fix:
            last_location = ground_fix
    last_temp = item.get("lastTemperature")

    return {
        "deviceId": item["deviceId"],
        "lastLocation": _format_location(last_location) if last_location else None,
        "lastTemperature": _format_temperature(last_temp) if last_temp else None,
        "inSafeZone": item.get("inSafeZone", False),
        "firmwareVersion": item.get("firmwareVersion", None),
        "lastSeen": item.get("lastSeen", None),
    }


def _format_location(loc: dict) -> dict:
    """
    lastLocation マップを Location 型 (API 仕様書 3.1) にフォーマットする。
    """
    return {
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "accuracy": loc.get("accuracy"),
        "source": loc.get("source", "GNSS"),
        "timestamp": loc.get("timestamp"),
    }


def _format_temperature(temp: dict) -> dict:
    """
    lastTemperature マップを Temperature 型 (API 仕様書 3.2) にフォーマットする。
    """
    return {
        "value": temp.get("value"),
        "timestamp": temp.get("timestamp"),
    }
