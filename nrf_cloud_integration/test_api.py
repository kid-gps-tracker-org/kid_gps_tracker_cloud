#!/usr/bin/env python3
"""
nRF Cloud API 接続テスト

使用方法:
    python test_api.py --nrf-cloud-api-key YOUR_KEY
"""
import os
import sys
import argparse
import logging
from dotenv import load_dotenv

from nrf_cloud_api import NrfCloudAPI
from github_fetcher import GitHubReleaseFetcher

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_nrf_cloud(api_key: str):
    """nRF Cloud API 接続テスト"""
    logger.info("🔍 nRF Cloud API 接続テスト...")

    try:
        api = NrfCloudAPI(api_key)
        firmwares = api.list_firmwares(limit=5)

        logger.info(f"✅ API 接続成功！")
        logger.info(f"\n📦 最新のファームウェア ({len(firmwares)} 件):")

        for i, fw in enumerate(firmwares, 1):
            logger.info(f"\n{i}. {fw.get('name', 'N/A')}")
            logger.info(f"   Version: {fw.get('version', 'N/A')}")
            logger.info(f"   ID: {fw.get('id', fw.get('bundleId', 'N/A'))}")
            logger.info(f"   Type: {fw.get('fwType', 'N/A')}")
            logger.info(f"   Created: {fw.get('createdAt', 'N/A')}")

        return True

    except Exception as e:
        logger.error(f"❌ API 接続失敗: {e}")
        return False


def test_github(token: str = None):
    """GitHub API 接続テスト"""
    logger.info("\n🔍 GitHub API 接続テスト...")

    try:
        fetcher = GitHubReleaseFetcher('kid-gps-tracker-org', 'kid_gps_tracker', token)
        releases = fetcher.list_releases(limit=3)

        logger.info(f"✅ GitHub API 接続成功！")
        logger.info(f"\n📦 最新のリリース ({len(releases)} 件):")

        for i, release in enumerate(releases, 1):
            logger.info(f"\n{i}. {release['name'] or release['tag_name']}")
            logger.info(f"   Tag: {release['tag_name']}")
            logger.info(f"   Published: {release['published_at']}")
            logger.info(f"   Assets: {len(release.get('assets', []))} files")

            # ファームウェアアセットの検索
            fw_asset = fetcher.find_firmware_asset(release)
            if fw_asset:
                logger.info(f"   Firmware: {fw_asset['name']} ({fw_asset['size']} bytes)")

        return True

    except Exception as e:
        logger.error(f"❌ GitHub API 接続失敗: {e}")
        return False


def main():
    """メイン処理"""
    load_dotenv()

    parser = argparse.ArgumentParser(description='API 接続テスト')
    parser.add_argument('--nrf-cloud-api-key', help='nRF Cloud API キー')
    parser.add_argument('--github-token', help='GitHub Token')
    parser.add_argument('--skip-nrf-cloud', action='store_true', help='nRF Cloud テストをスキップ')
    parser.add_argument('--skip-github', action='store_true', help='GitHub テストをスキップ')

    args = parser.parse_args()

    nrf_success = True
    github_success = True

    # nRF Cloud テスト
    if not args.skip_nrf_cloud:
        api_key = args.nrf_cloud_api_key or os.getenv('NRF_CLOUD_API_KEY')
        if not api_key:
            logger.warning("⚠️  nRF Cloud API キーが設定されていません（テストをスキップ）")
            nrf_success = False
        else:
            nrf_success = test_nrf_cloud(api_key)

    # GitHub テスト
    if not args.skip_github:
        token = args.github_token or os.getenv('GITHUB_TOKEN')
        github_success = test_github(token)

    # 結果サマリー
    logger.info("\n" + "="*50)
    logger.info("📊 テスト結果サマリー")
    logger.info("="*50)

    if not args.skip_nrf_cloud:
        status = "✅ 成功" if nrf_success else "❌ 失敗"
        logger.info(f"nRF Cloud API: {status}")

    if not args.skip_github:
        status = "✅ 成功" if github_success else "❌ 失敗"
        logger.info(f"GitHub API:    {status}")

    if (not args.skip_nrf_cloud and not nrf_success) or (not args.skip_github and not github_success):
        sys.exit(1)

    logger.info("\n✨ すべてのテストが完了しました")


if __name__ == "__main__":
    main()
