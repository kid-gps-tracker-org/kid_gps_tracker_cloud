#!/usr/bin/env python3
"""
GitHub Releases から nRF Cloud へのファームウェア手動アップロード

使用方法:
    python upload_firmware.py --nrf-cloud-api-key YOUR_KEY --version v1.0.0
    python upload_firmware.py --nrf-cloud-api-key YOUR_KEY  # 最新バージョン
"""
import os
import sys
import argparse
import tempfile
import logging
from pathlib import Path
from dotenv import load_dotenv

from nrf_cloud_api import NrfCloudAPI
from github_fetcher import GitHubReleaseFetcher

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """メイン処理"""
    # 環境変数を読み込み
    load_dotenv()

    # コマンドライン引数のパース
    parser = argparse.ArgumentParser(
        description='GitHub Releases から nRF Cloud へファームウェアをアップロード'
    )
    parser.add_argument(
        '--nrf-cloud-api-key',
        help='nRF Cloud API キー（または環境変数 NRF_CLOUD_API_KEY）'
    )
    parser.add_argument(
        '--github-token',
        help='GitHub Personal Access Token（オプション、環境変数 GITHUB_TOKEN）'
    )
    parser.add_argument(
        '--version',
        help='アップロードするバージョン（例: v1.0.0、デフォルト: 最新）'
    )
    parser.add_argument(
        '--board',
        default='nrf9151dk',
        help='ボード名（デフォルト: nrf9151dk）'
    )
    parser.add_argument(
        '--create-fota-job',
        action='store_true',
        help='FOTAジョブを自動作成'
    )
    parser.add_argument(
        '--device-ids',
        nargs='+',
        help='FOTAジョブのターゲットデバイスID（複数指定可）'
    )

    args = parser.parse_args()

    # API キーの取得
    nrf_cloud_api_key = args.nrf_cloud_api_key or os.getenv('NRF_CLOUD_API_KEY')
    if not nrf_cloud_api_key:
        logger.error("❌ nRF Cloud API キーが指定されていません")
        logger.error("   --nrf-cloud-api-key オプションまたは NRF_CLOUD_API_KEY 環境変数を設定してください")
        sys.exit(1)

    github_token = args.github_token or os.getenv('GITHUB_TOKEN')

    try:
        # GitHub から最新リリースを取得
        logger.info("📦 GitHub Releases からファームウェアを取得中...")
        fetcher = GitHubReleaseFetcher(
            'kid-gps-tracker-org',
            'kid_gps_tracker',
            github_token
        )

        if args.version:
            release = fetcher.get_release_by_tag(args.version)
            version = args.version.lstrip('v')
        else:
            release = fetcher.get_latest_release()
            version = release['tag_name'].lstrip('v')

        logger.info(f"ℹ️  バージョン: {version}")

        # 一時ディレクトリにダウンロード
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            logger.info(f"⬇️  ファームウェアをダウンロード中...")
            firmware_path = fetcher.download_firmware(
                version=release['tag_name'] if args.version else None,
                output_dir=tmpdir_path,
                board=args.board
            )

            # nRF Cloud にアップロード
            logger.info(f"⬆️  nRF Cloud にアップロード中...")
            nrf_api = NrfCloudAPI(nrf_cloud_api_key)

            result = nrf_api.upload_firmware(
                bundle_path=firmware_path,
                version=version,
                board=args.board,
                description=f"Kid GPS Tracker v{version} for {args.board}"
            )

            firmware_id = result.get('id') or result.get('bundleId')
            logger.info(f"✅ アップロード成功！")
            logger.info(f"   Firmware ID: {firmware_id}")

            # FOTA ジョブ作成（オプション）
            if args.create_fota_job and firmware_id:
                logger.info(f"🚀 FOTA ジョブを作成中...")
                job = nrf_api.create_fota_job(
                    firmware_id=firmware_id,
                    device_ids=args.device_ids,
                    description=f"Kid GPS Tracker v{version} FOTA"
                )
                logger.info(f"✅ FOTA ジョブ作成成功: {job.get('jobId')}")

        logger.info("\n✨ すべての処理が完了しました")

    except Exception as e:
        logger.error(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
