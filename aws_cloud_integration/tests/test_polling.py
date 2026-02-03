#!/usr/bin/env python3
"""
ポーリング Lambda のローカルテストスクリプト

使い方:
    # .env ファイルに NRF_CLOUD_API_KEY を設定した状態で実行
    python aws_cloud_integration/tests/test_polling.py

    # API キーを引数で指定
    python aws_cloud_integration/tests/test_polling.py --api-key YOUR_API_KEY

    # 過去N分間のメッセージを取得
    python aws_cloud_integration/tests/test_polling.py --lookback-minutes 30
"""
import sys
import os
import argparse
import logging

# Lambda コードのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda", "polling"))

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description="ポーリング Lambda ローカルテスト")
    parser.add_argument(
        "--api-key",
        help="nRF Cloud API キー（省略時は .env の NRF_CLOUD_API_KEY を使用）",
    )
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=5,
        help="過去何分間のメッセージを取得するか（デフォルト: 5）",
    )
    parser.add_argument(
        "--test-client-only",
        action="store_true",
        help="NrfCloudClient のみテスト（handler は実行しない）",
    )
    parser.add_argument(
        "--test-devices",
        action="store_true",
        help="デバイス一覧の取得テスト",
    )
    args = parser.parse_args()

    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # .env 読み込み
    load_dotenv()

    api_key = args.api_key or os.getenv("NRF_CLOUD_API_KEY")
    if not api_key:
        print("ERROR: NRF_CLOUD_API_KEY が設定されていません")
        print("  .env ファイルに NRF_CLOUD_API_KEY=your_key を追加するか、")
        print("  --api-key オプションで指定してください")
        sys.exit(1)

    if args.test_devices:
        _test_devices(api_key)
        return

    if args.test_client_only:
        _test_client(api_key, args.lookback_minutes)
        return

    _test_full_handler(api_key, args.lookback_minutes)


def _test_devices(api_key: str):
    """デバイス一覧の取得テスト"""
    from nrf_cloud_client import NrfCloudClient

    print("\n--- デバイス一覧取得テスト ---\n")

    client = NrfCloudClient(api_key)
    devices = client.get_devices()

    if not devices:
        print("デバイスが見つかりませんでした")
        return

    print(f"デバイス数: {len(devices)}\n")
    for device in devices:
        device_id = device.get("id", "N/A")
        name = device.get("name", "N/A")
        state = device.get("state", {})
        print(f"  ID: {device_id}")
        print(f"  Name: {name}")
        print(f"  State: {state}")
        print()


def _test_client(api_key: str, lookback_minutes: int):
    """NrfCloudClient 単体テスト"""
    from nrf_cloud_client import NrfCloudClient
    from datetime import datetime, timezone, timedelta

    print("\n--- NrfCloudClient 単体テスト ---\n")

    client = NrfCloudClient(api_key)

    start_time = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    print(f"取得期間: {start_str} 以降")
    print(f"（過去 {lookback_minutes} 分間）\n")

    try:
        messages = client.get_all_messages(inclusive_start=start_str)
        print(f"取得メッセージ数: {len(messages)}\n")

        for i, msg in enumerate(messages):
            device_id = msg.get("deviceId", "N/A")
            received_at = msg.get("receivedAt", "N/A")
            message = msg.get("message", {})
            app_id = message.get("appId", "N/A")

            print(f"  [{i+1}] deviceId={device_id}, appId={app_id}, receivedAt={received_at}")

            if app_id == "GNSS":
                pvt = message.get("data", {}).get("pvt", {})
                print(f"       lat={pvt.get('lat')}, lon={pvt.get('lon')}, acc={pvt.get('acc')}")
            elif app_id == "TEMP":
                print(f"       temperature={message.get('data')}C")
            else:
                print(f"       data={message.get('data')}")

        if not messages:
            print("  メッセージがありません。デバイスが nRF Cloud に接続しているか確認してください。")

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def _test_full_handler(api_key: str, lookback_minutes: int):
    """handler.py のフルテスト（ローカルモード）"""
    import handler

    print("\n--- ポーリング Lambda フルテスト (ローカルモード) ---\n")

    # 環境変数設定
    os.environ["LOCAL_MODE"] = "true"
    os.environ["NRF_CLOUD_API_KEY"] = api_key

    # lookback の設定
    handler.DEFAULT_LOOKBACK_MINUTES = lookback_minutes

    # ポーリング状態ファイルを確認
    state_file = handler.POLLING_STATE_FILE
    if state_file.exists():
        import json
        with open(state_file, "r") as f:
            state = json.load(f)
        print(f"前回のポーリング状態: {json.dumps(state, indent=2)}\n")
    else:
        print(f"初回実行（過去 {lookback_minutes} 分間のメッセージを取得）\n")

    # Lambda ハンドラ実行
    result = handler.lambda_handler({}, None)

    print(f"\n--- 実行結果 ---")
    print(f"  ステータス: {result.get('statusCode')}")
    print(f"  処理メッセージ数: {result.get('messagesProcessed', 0)}")
    print(f"  更新デバイス数: {result.get('devicesUpdated', 0)}")
    print(f"  最終受信時刻: {result.get('lastReceivedAt', 'N/A')}")

    if state_file.exists():
        import json
        with open(state_file, "r") as f:
            state = json.load(f)
        print(f"\n  ポーリング状態保存先: {state_file}")
        print(f"  保存内容: {json.dumps(state, indent=2)}")


if __name__ == "__main__":
    main()
