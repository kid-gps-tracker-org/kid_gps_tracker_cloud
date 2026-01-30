#!/usr/bin/env python3
"""
位置データ管理スクリプト

nRF Cloud に蓄積された GNSS 位置情報データを管理する。
- 位置情報履歴の取得・表示
- 指定時間（デフォルト168時間=7日）を超えた古いデータの自動削除

使用例:
    # データ一覧表示
    python location_data_manager.py --device-id nrf-XXXX --list

    # 削除対象のプレビュー（実際には削除しない）
    python location_data_manager.py --device-id nrf-XXXX --dry-run

    # 168時間以上前のデータを削除
    python location_data_manager.py --device-id nrf-XXXX

    # 保持時間を変更（例: 48時間）
    python location_data_manager.py --device-id nrf-XXXX --retention-hours 48
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from nrf_cloud_api import NrfCloudAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_RETENTION_HOURS = 168  # 7日間


def list_location_data(api: NrfCloudAPI, device_id: str) -> None:
    """デバイスの位置情報履歴を一覧表示"""
    logger.info(f"デバイス {device_id} の位置情報履歴を取得中...")

    items = api.get_all_location_history(device_id=device_id)

    if not items:
        logger.info("位置情報データがありません。")
        return

    logger.info(f"合計 {len(items)} 件の位置情報レコード:")
    print(f"\n{'No':>4}  {'日時':<26}  {'緯度':>12}  {'経度':>12}  {'精度(m)':>8}  {'種別':<10}  {'ID'}")
    print("-" * 110)

    for i, item in enumerate(items, 1):
        inserted_at = item.get("insertedAt", "N/A")
        lat = item.get("lat", "N/A")
        lon = item.get("lon", "N/A")
        uncertainty = item.get("uncertainty", "N/A")
        service_type = item.get("serviceType", "N/A")
        record_id = item.get("id", "N/A")

        print(f"{i:>4}  {inserted_at:<26}  {lat:>12}  {lon:>12}  {uncertainty:>8}  {service_type:<10}  {record_id}")

    print()


def cleanup_old_data(
    api: NrfCloudAPI,
    device_id: str,
    retention_hours: int,
    dry_run: bool = False
) -> None:
    """指定時間を超えた古い位置データを削除"""
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    cutoff_str = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    logger.info(f"データ保持期間: {retention_hours} 時間（{retention_hours // 24} 日間）")
    logger.info(f"削除対象: {cutoff_str} より前のデータ")

    if dry_run:
        logger.info("[DRY RUN] 実際の削除は行いません")

    # カットオフ時刻より前のデータを取得
    items = api.get_all_location_history(
        device_id=device_id,
        end=cutoff_str
    )

    if not items:
        logger.info("削除対象のデータはありません。")
        return

    logger.info(f"削除対象: {len(items)} 件")

    if dry_run:
        for item in items:
            logger.info(
                f"  [対象] {item.get('insertedAt')} - "
                f"({item.get('lat')}, {item.get('lon')}) - "
                f"{item.get('serviceType')} - ID: {item.get('id')}"
            )
        logger.info(f"[DRY RUN] {len(items)} 件が削除対象です。")
        return

    deleted = 0
    failed = 0
    for item in items:
        record_id = item.get("id")
        if not record_id:
            continue

        if api.delete_location_record(device_id, record_id):
            deleted += 1
            logger.debug(f"  削除完了: {record_id}")
        else:
            failed += 1
            logger.warning(f"  削除失敗: {record_id}")

    logger.info(f"削除完了: {deleted} 件成功, {failed} 件失敗")


def main():
    parser = argparse.ArgumentParser(
        description="nRF Cloud 位置データ管理ツール"
    )
    parser.add_argument(
        "--device-id",
        required=True,
        help="デバイスID (例: nrf-XXXX)"
    )
    parser.add_argument(
        "--retention-hours",
        type=int,
        default=DEFAULT_RETENTION_HOURS,
        help=f"データ保持時間 (デフォルト: {DEFAULT_RETENTION_HOURS}時間 = 7日間)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除対象の確認のみ（実際に削除しない）"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_data",
        help="位置情報データの一覧表示"
    )
    parser.add_argument(
        "--nrf-cloud-api-key",
        default=None,
        help="nRF Cloud API キー (未指定時は環境変数 NRF_CLOUD_API_KEY を使用)"
    )
    args = parser.parse_args()

    # 環境変数読み込み
    load_dotenv()

    api_key = args.nrf_cloud_api_key or os.getenv("NRF_CLOUD_API_KEY")
    if not api_key:
        logger.error(
            "nRF Cloud API キーが指定されていません。"
            " --nrf-cloud-api-key 引数または環境変数 NRF_CLOUD_API_KEY を設定してください。"
        )
        sys.exit(1)

    api = NrfCloudAPI(api_key)

    if args.list_data:
        list_location_data(api, args.device_id)
    else:
        cleanup_old_data(
            api,
            args.device_id,
            args.retention_hours,
            dry_run=args.dry_run
        )


if __name__ == "__main__":
    main()
