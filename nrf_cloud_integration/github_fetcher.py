#!/usr/bin/env python3
"""
GitHub Releases からファームウェアをダウンロード
"""
import requests
from pathlib import Path
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)


class GitHubReleaseFetcher:
    """GitHub Releases からファームウェアを取得"""

    def __init__(self, org: str, repo: str, token: Optional[str] = None):
        """
        Args:
            org: GitHub 組織名
            repo: リポジトリ名
            token: GitHub Personal Access Token（オプション）
        """
        self.org = org
        self.repo = repo
        self.headers = {}
        if token:
            self.headers['Authorization'] = f'token {token}'
            self.headers['Accept'] = 'application/vnd.github.v3+json'

    def get_latest_release(self) -> Dict:
        """
        最新のリリースを取得

        Returns:
            リリース情報
        """
        url = f"https://api.github.com/repos/{self.org}/{self.repo}/releases/latest"
        response = requests.get(url, headers=self.headers, timeout=30)

        if response.status_code == 200:
            release = response.json()
            logger.info(f"Latest release: {release['tag_name']}")
            return release
        else:
            raise Exception(f"Failed to fetch release: {response.status_code} - {response.text}")

    def get_release_by_tag(self, tag: str) -> Dict:
        """
        特定のタグのリリースを取得

        Args:
            tag: リリースタグ（例: "v1.0.0"）

        Returns:
            リリース情報
        """
        url = f"https://api.github.com/repos/{self.org}/{self.repo}/releases/tags/{tag}"
        response = requests.get(url, headers=self.headers, timeout=30)

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to fetch release {tag}: {response.status_code}")

    def list_releases(self, limit: int = 10) -> List[Dict]:
        """
        リリース一覧を取得

        Args:
            limit: 取得する最大件数

        Returns:
            リリース情報のリスト
        """
        url = f"https://api.github.com/repos/{self.org}/{self.repo}/releases"
        response = requests.get(
            url,
            headers=self.headers,
            params={'per_page': limit},
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to list releases: {response.status_code}")

    def download_asset(
        self,
        asset_url: str,
        output_path: Path,
        asset_name: Optional[str] = None
    ) -> Path:
        """
        リリースアセットをダウンロード

        Args:
            asset_url: アセットのダウンロードURL
            output_path: 保存先ディレクトリ
            asset_name: アセット名（オプション）

        Returns:
            ダウンロードされたファイルのパス
        """
        headers = self.headers.copy()
        headers['Accept'] = 'application/octet-stream'

        response = requests.get(asset_url, headers=headers, stream=True, timeout=300)

        if response.status_code == 200:
            # ファイル名をレスポンスヘッダーから取得
            if not asset_name:
                content_disposition = response.headers.get('content-disposition', '')
                if 'filename=' in content_disposition:
                    asset_name = content_disposition.split('filename=')[1].strip('"')
                else:
                    asset_name = 'firmware.zip'

            file_path = output_path / asset_name
            output_path.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"✓ Downloaded: {asset_name} ({file_path.stat().st_size} bytes)")
            return file_path
        else:
            raise Exception(f"Download failed: {response.status_code}")

    def find_firmware_asset(
        self,
        release: Dict,
        board: str = "nrf9151dk",
        extension: str = ".zip"
    ) -> Optional[Dict]:
        """
        リリースからファームウェアアセットを検索

        Args:
            release: リリース情報
            board: ボード名
            extension: ファイル拡張子

        Returns:
            アセット情報（見つからない場合はNone）
        """
        for asset in release.get('assets', []):
            name = asset['name'].lower()
            if board in name and name.endswith(extension):
                return asset
        return None

    def download_firmware(
        self,
        version: Optional[str] = None,
        output_dir: Path = Path('downloads'),
        board: str = "nrf9151dk"
    ) -> Path:
        """
        ファームウェアをダウンロード

        Args:
            version: バージョン（Noneの場合は最新）
            output_dir: 保存先ディレクトリ
            board: ボード名

        Returns:
            ダウンロードされたファイルのパス
        """
        # リリースを取得
        if version:
            release = self.get_release_by_tag(version)
        else:
            release = self.get_latest_release()

        # ファームウェアアセットを検索
        asset = self.find_firmware_asset(release, board=board)
        if not asset:
            raise Exception(f"Firmware asset not found for {board} in release {release['tag_name']}")

        # ダウンロード
        logger.info(f"Downloading {asset['name']} from {release['tag_name']}...")
        return self.download_asset(
            asset['browser_download_url'],
            output_dir,
            asset['name']
        )
