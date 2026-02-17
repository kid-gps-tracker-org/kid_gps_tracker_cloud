#!/usr/bin/env python3
"""
REST API Lambda ハンドラ
API Gateway (proxy integration) イベントを受け取り、適切なルートハンドラにディスパッチする。

ローカルモード (LOCAL_MODE=true):
  - テストスクリプトから直接呼び出し可能
  - DynamoDB テーブルは環境変数またはデフォルト名で接続
"""
import logging

logger = logging.getLogger(__name__)

# ルートテーブル（初回呼び出し時に登録）
_ROUTES = {}


def _register_routes():
    """ルートディスパッチテーブルを構築する。コールドスタート時に1回だけ実行。"""
    from routes_devices import get_devices, get_device_location, get_device_temperature
    from routes_history import get_device_history
    from routes_safezones import get_safezones, put_safezone, delete_safezone
    from routes_firmware import get_firmware, post_firmware_update, get_firmware_status
    from routes_notifications import post_notification_token

    _ROUTES[("GET", "/devices")] = get_devices
    _ROUTES[("GET", "/devices/{deviceId}/location")] = get_device_location
    _ROUTES[("GET", "/devices/{deviceId}/temperature")] = get_device_temperature
    _ROUTES[("GET", "/devices/{deviceId}/history")] = get_device_history
    _ROUTES[("GET", "/devices/{deviceId}/safezones")] = get_safezones
    _ROUTES[("PUT", "/devices/{deviceId}/safezones")] = put_safezone
    _ROUTES[("DELETE", "/devices/{deviceId}/safezones/{zoneId}")] = delete_safezone
    _ROUTES[("POST", "/devices/{deviceId}/notification-token")] = post_notification_token
    _ROUTES[("GET", "/devices/{deviceId}/firmware")] = get_firmware
    _ROUTES[("POST", "/devices/{deviceId}/firmware/update")] = post_firmware_update
    _ROUTES[("GET", "/devices/{deviceId}/firmware/status")] = get_firmware_status


def lambda_handler(event, context):
    """
    Lambda エントリーポイント

    Args:
        event: API Gateway proxy integration イベント
            使用キー: httpMethod, resource, pathParameters, queryStringParameters, body
        context: Lambda コンテキスト（ローカルモードでは None）

    Returns:
        API Gateway proxy レスポンス: { statusCode, headers, body }
    """
    if not _ROUTES:
        _register_routes()

    http_method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    route_key = (http_method, resource)

    logger.info(f"Request: {http_method} {resource}")

    handler_fn = _ROUTES.get(route_key)
    if not handler_fn:
        from response_utils import error_response
        return error_response(404, "ROUTE_NOT_FOUND",
                              f"No handler for {http_method} {resource}")

    try:
        return handler_fn(event)
    except Exception as e:
        logger.exception(f"Unhandled error in {http_method} {resource}")
        from response_utils import error_response
        return error_response(500, "INTERNAL_ERROR", "An internal error occurred")
