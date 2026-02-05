#!/usr/bin/env python3
"""
REST API Lambda ローカルテストスクリプト

test_polling.py と同じパターンで API Lambda をテストする。

使用方法:
    python aws_cloud_integration/tests/test_api.py
    python aws_cloud_integration/tests/test_api.py --endpoint devices
    python aws_cloud_integration/tests/test_api.py --device-id nrf-352656100123456
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

# API Lambda ソースをパスに追加
API_LAMBDA_DIR = Path(__file__).parent.parent / "lambda" / "api"
sys.path.insert(0, str(API_LAMBDA_DIR))

# .env ファイルを読み込み
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def _make_event(method: str, resource: str, path_params: dict = None,
                query_params: dict = None, body: dict = None) -> dict:
    """API Gateway proxy integration イベントを生成する。"""
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params,
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
    }


def _print_response(result: dict):
    """レスポンスをフォーマットして表示する。"""
    status = result.get("statusCode")
    body = result.get("body", "")

    try:
        parsed = json.loads(body) if body else None
        print(f"  Status: {status}")
        if parsed:
            print(f"  Body: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
    except (json.JSONDecodeError, TypeError):
        print(f"  Status: {status}")
        print(f"  Body: {body}")


def _run_test(name: str, test_fn):
    """テストを実行して結果を表示する。"""
    print(f"\n{'=' * 60}")
    print(f"  TEST: {name}")
    print("=" * 60)
    try:
        test_fn()
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


def test_get_devices(handler):
    """GET /devices テスト"""
    event = _make_event("GET", "/devices")
    result = handler(event, None)
    _print_response(result)


def test_get_location(handler, device_id: str):
    """GET /devices/{deviceId}/location テスト"""
    event = _make_event(
        "GET", "/devices/{deviceId}/location",
        path_params={"deviceId": device_id}
    )
    result = handler(event, None)
    _print_response(result)


def test_get_temperature(handler, device_id: str):
    """GET /devices/{deviceId}/temperature テスト"""
    event = _make_event(
        "GET", "/devices/{deviceId}/temperature",
        path_params={"deviceId": device_id}
    )
    result = handler(event, None)
    _print_response(result)


def test_get_history(handler, device_id: str):
    """GET /devices/{deviceId}/history テスト"""
    print("\n  --- Without filters ---")
    event = _make_event(
        "GET", "/devices/{deviceId}/history",
        path_params={"deviceId": device_id},
        query_params={"limit": "5"}
    )
    result = handler(event, None)
    _print_response(result)

    print("\n  --- With type=GNSS ---")
    event = _make_event(
        "GET", "/devices/{deviceId}/history",
        path_params={"deviceId": device_id},
        query_params={"type": "GNSS", "limit": "3"}
    )
    result = handler(event, None)
    _print_response(result)


def test_safezones_crud(handler, device_id: str):
    """セーフゾーン CRUD テスト"""
    # 1. Create
    print("\n  --- Create SafeZone ---")
    event = _make_event(
        "PUT", "/devices/{deviceId}/safezones",
        path_params={"deviceId": device_id},
        body={
            "name": "テストゾーン",
            "center": {"lat": 35.6812, "lon": 139.7671},
            "radius": 200,
        }
    )
    result = handler(event, None)
    _print_response(result)

    # zoneId を取得
    body = json.loads(result.get("body", "{}"))
    zone_id = body.get("safezone", {}).get("zoneId")

    if zone_id:
        # 2. List
        print("\n  --- List SafeZones ---")
        event = _make_event(
            "GET", "/devices/{deviceId}/safezones",
            path_params={"deviceId": device_id}
        )
        result = handler(event, None)
        _print_response(result)

        # 3. Update
        print("\n  --- Update SafeZone ---")
        event = _make_event(
            "PUT", "/devices/{deviceId}/safezones",
            path_params={"deviceId": device_id},
            body={
                "zoneId": zone_id,
                "name": "更新済みゾーン",
                "radius": 300,
            }
        )
        result = handler(event, None)
        _print_response(result)

        # 4. Delete
        print("\n  --- Delete SafeZone ---")
        event = _make_event(
            "DELETE", "/devices/{deviceId}/safezones/{zoneId}",
            path_params={"deviceId": device_id, "zoneId": zone_id}
        )
        result = handler(event, None)
        _print_response(result)
    else:
        print("  Skipping update/delete (no zoneId in response)")


def test_get_firmware(handler, device_id: str):
    """GET /devices/{deviceId}/firmware テスト"""
    event = _make_event(
        "GET", "/devices/{deviceId}/firmware",
        path_params={"deviceId": device_id}
    )
    result = handler(event, None)
    _print_response(result)


def main():
    parser = argparse.ArgumentParser(description="REST API Lambda ローカルテスト")
    parser.add_argument("--api-key", help="nRF Cloud API キー")
    parser.add_argument("--device-id", help="テスト対象のデバイス ID")
    parser.add_argument(
        "--endpoint",
        choices=["devices", "location", "temperature", "history",
                 "safezones", "firmware", "all"],
        default="all",
        help="テストするエンドポイント (デフォルト: all)"
    )
    args = parser.parse_args()

    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    # ローカルモード設定
    os.environ["LOCAL_MODE"] = "true"
    if args.api_key:
        os.environ["NRF_CLOUD_API_KEY"] = args.api_key

    # Lambda ハンドラをインポート
    from handler import lambda_handler

    # デフォルトデバイス ID
    device_id = args.device_id or "nrf-352656100123456"

    print("=" * 60)
    print("  REST API Lambda Local Test")
    print("=" * 60)
    print(f"  Device ID: {device_id}")
    print(f"  Endpoint: {args.endpoint}")

    # テスト定義
    tests = {
        "devices": lambda: test_get_devices(lambda_handler),
        "location": lambda: test_get_location(lambda_handler, device_id),
        "temperature": lambda: test_get_temperature(lambda_handler, device_id),
        "history": lambda: test_get_history(lambda_handler, device_id),
        "safezones": lambda: test_safezones_crud(lambda_handler, device_id),
        "firmware": lambda: test_get_firmware(lambda_handler, device_id),
    }

    # テスト実行
    if args.endpoint == "all":
        for name, test_fn in tests.items():
            _run_test(name, test_fn)
    elif args.endpoint in tests:
        _run_test(args.endpoint, tests[args.endpoint])

    print("\n" + "=" * 60)
    print("  Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
