#!/usr/bin/env python3
"""
nRF Cloud メッセージ → DynamoDB レコード変換モジュール
interface_design.md セクション4 のデータ変換仕様に準拠。
"""
from datetime import datetime, timezone
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

# デバイスメッセージの保持期間（日）
DEFAULT_RETENTION_DAYS = 30


def transform_message(raw_message: Dict) -> Optional[Dict]:
    """
    nRF Cloud メッセージを DynamoDB レコード形式に変換する。

    Args:
        raw_message: nRF Cloud API レスポンスの1メッセージ
            {
                "deviceId": "nrf-352656100123456",
                "receivedAt": "2026-02-03T10:30:00.000Z",
                "message": {
                    "appId": "GNSS",
                    "ts": 1738577400000,
                    "data": {...}
                }
            }

    Returns:
        変換済みレコード。未対応の appId の場合は None。
    """
    device_id = raw_message.get("deviceId")
    received_at = raw_message.get("receivedAt")
    message = raw_message.get("message", {})
    app_id = message.get("appId")

    if not device_id or not message:
        logger.warning(f"Invalid message format: missing deviceId or message")
        return None

    if app_id == "GNSS":
        return _transform_gnss(device_id, received_at, message)
    elif app_id == "TEMP":
        return _transform_temp(device_id, received_at, message)
    else:
        logger.debug(f"Skipping unsupported appId: {app_id}")
        return None


def _transform_gnss(device_id: str, received_at: str, message: Dict) -> Optional[Dict]:
    """
    GNSS メッセージを DynamoDB レコードに変換する。

    入力:
        {"appId":"GNSS","ts":1738577400000,"data":{"pvt":{"lat":35.6812,"lon":139.7671,"acc":10.5}}}

    出力:
        {
            "deviceId": "nrf-352656100123456",
            "timestamp": "2026-02-03T10:30:00.000Z",
            "messageType": "GNSS",
            "lat": 35.6812,
            "lon": 139.7671,
            "accuracy": 10.5,
            "deviceTs": 1738577400000,
            "receivedAt": "2026-02-03T10:30:00.000Z",
            "ttl": 1741169400
        }
    """
    device_ts = message.get("ts")
    data = message.get("data", {})
    pvt = data.get("pvt", {})

    lat = pvt.get("lat")
    lon = pvt.get("lon")
    acc = pvt.get("acc")

    if lat is None or lon is None:
        logger.warning(f"GNSS message missing lat/lon for device {device_id}")
        return None

    timestamp = _ts_to_iso8601(device_ts) if device_ts else received_at

    record = {
        "deviceId": device_id,
        "timestamp": timestamp,
        "messageType": "GNSS",
        "lat": lat,
        "lon": lon,
        "deviceTs": device_ts,
        "receivedAt": received_at,
        "ttl": _calculate_ttl(device_ts),
    }

    if acc is not None:
        record["accuracy"] = acc

    return record


def _transform_temp(device_id: str, received_at: str, message: Dict) -> Optional[Dict]:
    """
    温度メッセージを DynamoDB レコードに変換する。

    入力:
        {"appId":"TEMP","messageType":"DATA","ts":1738577405000,"data":23.5}

    出力:
        {
            "deviceId": "nrf-352656100123456",
            "timestamp": "2026-02-03T10:30:05.000Z",
            "messageType": "TEMP",
            "temperature": 23.5,
            "deviceTs": 1738577405000,
            "receivedAt": "2026-02-03T10:30:05.000Z",
            "ttl": 1741169405
        }
    """
    device_ts = message.get("ts")
    temperature = message.get("data")

    if temperature is None:
        logger.warning(f"TEMP message missing data for device {device_id}")
        return None

    timestamp = _ts_to_iso8601(device_ts) if device_ts else received_at

    return {
        "deviceId": device_id,
        "timestamp": timestamp,
        "messageType": "TEMP",
        "temperature": temperature,
        "deviceTs": device_ts,
        "receivedAt": received_at,
        "ttl": _calculate_ttl(device_ts),
    }


def extract_device_state_update(record: Dict) -> Optional[Dict]:
    """
    変換済みレコードから DeviceState テーブルの更新データを抽出する。

    Args:
        record: transform_message() の戻り値

    Returns:
        DeviceState 更新用の辞書
    """
    if not record:
        return None

    device_id = record["deviceId"]
    message_type = record["messageType"]

    update = {
        "deviceId": device_id,
        "lastSeen": record["receivedAt"],
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    if message_type == "GNSS":
        update["lastLocation"] = {
            "lat": record["lat"],
            "lon": record["lon"],
            "accuracy": record.get("accuracy"),
            "timestamp": record["timestamp"],
        }
    elif message_type == "TEMP":
        update["lastTemperature"] = {
            "value": record["temperature"],
            "timestamp": record["timestamp"],
        }

    return update


def _ts_to_iso8601(ts_ms: int) -> str:
    """Unix ミリ秒タイムスタンプを ISO 8601 文字列に変換"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_ms % 1000:03d}Z"


def _calculate_ttl(device_ts_ms: Optional[int], retention_days: int = DEFAULT_RETENTION_DAYS) -> Optional[int]:
    """
    TTL 値を計算する。DynamoDB の TTL は Unix 秒。

    Args:
        device_ts_ms: デバイスタイムスタンプ (ミリ秒)
        retention_days: 保持期間 (日)

    Returns:
        TTL (Unix 秒)。device_ts_ms が None の場合は None。
    """
    if device_ts_ms is None:
        return None
    return int(device_ts_ms / 1000) + (retention_days * 24 * 3600)
