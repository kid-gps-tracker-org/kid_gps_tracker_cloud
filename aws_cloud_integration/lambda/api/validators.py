"""
リクエストバリデーションヘルパー
API 仕様書セクション 7 のバリデーションルールに基づく。
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple


def get_device_id(event: dict) -> Optional[str]:
    """パスパラメータから deviceId を取得する。"""
    params = event.get("pathParameters") or {}
    return params.get("deviceId")


def get_zone_id(event: dict) -> Optional[str]:
    """パスパラメータから zoneId を取得する。"""
    params = event.get("pathParameters") or {}
    return params.get("zoneId")


def get_query_param(event: dict, name: str, default: Optional[str] = None) -> Optional[str]:
    """クエリストリングパラメータを取得する。"""
    params = event.get("queryStringParameters") or {}
    return params.get(name, default)


def parse_json_body(event: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    JSON リクエストボディをパースする。

    Returns:
        (parsed_body, error_message) -- 成功時は error_message が None
    """
    body = event.get("body")
    if not body:
        return None, "Request body is not valid JSON"
    try:
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            return None, "Request body is not valid JSON"
        return parsed, None
    except (json.JSONDecodeError, TypeError):
        return None, "Request body is not valid JSON"


def validate_iso8601(value: str) -> bool:
    """ISO 8601 UTC タイムスタンプの妥当性を検証する。"""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def validate_history_params(event: dict) -> Tuple[dict, Optional[str]]:
    """
    history エンドポイントのクエリパラメータをバリデーションする。
    API 仕様書 4.4 のバリデーションルールに基づく。

    Returns:
        (params_dict, error_message)
        params_dict のキー: type, start, end, limit
    """
    msg_type = get_query_param(event, "type")
    start = get_query_param(event, "start")
    end = get_query_param(event, "end")
    limit_str = get_query_param(event, "limit", "100")

    # type バリデーション
    if msg_type and msg_type not in ("GNSS", "GROUND_FIX", "TEMP"):
        return {}, f"Parameter 'type' is invalid"

    # start バリデーション
    if start:
        if not validate_iso8601(start):
            return {}, f"Parameter 'start' is invalid"
        # 過去30日以内チェック
        start_dt = _parse_iso8601(start)
        if start_dt and start_dt < datetime.now(timezone.utc) - timedelta(days=30):
            return {}, f"Parameter 'start' is invalid"

    # end バリデーション
    if end and not validate_iso8601(end):
        return {}, f"Parameter 'end' is invalid"

    # start < end チェック
    if start and end and start >= end:
        return {}, "Start time must be before end time"

    # limit バリデーション
    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        return {}, f"Parameter 'limit' is invalid"

    if limit < 1 or limit > 1000:
        return {}, f"Parameter 'limit' is invalid"

    return {"type": msg_type, "start": start, "end": end, "limit": limit}, None


def validate_safezone_create(body: dict) -> Optional[str]:
    """
    セーフゾーン新規作成のバリデーション。
    API 仕様書 4.6: name, center, radius は必須。

    Returns:
        エラーメッセージ文字列。バリデーション成功時は None。
    """
    # name バリデーション
    name = body.get("name")
    if name is None or not isinstance(name, str) or len(name) == 0:
        return "Required field 'name' is missing"
    if len(name) > 50:
        return "Zone name must be 1 to 50 characters"

    # center バリデーション
    center = body.get("center")
    if center is None or not isinstance(center, dict):
        return "Required field 'center' is missing"

    error = _validate_coordinate(center)
    if error:
        return error

    # radius バリデーション
    radius = body.get("radius")
    if radius is None:
        return "Required field 'radius' is missing"
    error = _validate_radius(radius)
    if error:
        return error

    return None


def validate_safezone_update(body: dict) -> Optional[str]:
    """
    セーフゾーン更新のバリデーション。
    API 仕様書 4.6: zoneId のみ必須、他は送信されたフィールドのみ検証。

    Returns:
        エラーメッセージ文字列。バリデーション成功時は None。
    """
    # name バリデーション（指定された場合のみ）
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or len(name) == 0:
            return "Zone name must be 1 to 50 characters"
        if len(name) > 50:
            return "Zone name must be 1 to 50 characters"

    # center バリデーション（指定された場合のみ）
    if "center" in body:
        center = body["center"]
        if not isinstance(center, dict):
            return "Latitude must be -90 to 90, longitude -180 to 180"
        error = _validate_coordinate(center)
        if error:
            return error

    # radius バリデーション（指定された場合のみ）
    if "radius" in body:
        error = _validate_radius(body["radius"])
        if error:
            return error

    return None


def _validate_coordinate(center: dict) -> Optional[str]:
    """座標のバリデーション。"""
    lat = center.get("lat")
    lon = center.get("lon")

    if lat is None or lon is None:
        return "Latitude must be -90 to 90, longitude -180 to 180"

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return "Latitude must be -90 to 90, longitude -180 to 180"

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return "Latitude must be -90 to 90, longitude -180 to 180"

    return None


def _validate_radius(radius) -> Optional[str]:
    """半径のバリデーション。"""
    try:
        radius_val = int(radius)
    except (TypeError, ValueError):
        return "Radius must be between 50 and 10000 meters"

    if radius_val < 50 or radius_val > 10000:
        return "Radius must be between 50 and 10000 meters"

    return None


def _parse_iso8601(value: str) -> Optional[datetime]:
    """ISO 8601 文字列を datetime に変換する。"""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
