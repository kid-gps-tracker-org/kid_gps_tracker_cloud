#!/usr/bin/env python3
"""
nRF Cloud REST API ラッパー
ドキュメント: https://api.nrfcloud.com/
"""
import requests
import json
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class NrfCloudAPI:
    """nRF Cloud REST API クライアント"""

    BASE_URL = "https://api.nrfcloud.com/v1"

    def __init__(self, api_key: str):
        """
        Args:
            api_key: nRF Cloud API キー
        """
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def upload_firmware(
        self,
        bundle_path: Path,
        version: str,
        board: str = "nrf9151dk",
        fw_type: str = "APP",
        description: str = None
    ) -> Dict:
        """
        ファームウェアバンドルを nRF Cloud にアップロード

        Args:
            bundle_path: dfu_application.zip へのパス
            version: ファームウェアバージョン（例: "1.0.0"）
            board: ターゲットボード
            fw_type: ファームウェアタイプ（APP, MODEM, BOOT）
            description: ファームウェアの説明

        Returns:
            API レスポンス（firmware ID を含む）
        """
        if not bundle_path.exists():
            raise FileNotFoundError(f"Bundle not found: {bundle_path}")

        # Step 1: Fix manifest.json to add fwversion
        logger.info("Fixing manifest.json...")
        import zipfile
        import tempfile
        import json

        fixed_bundle = Path(tempfile.gettempdir()) / f"{bundle_path.stem}_fixed.zip"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Extract ZIP
            with zipfile.ZipFile(bundle_path, 'r') as zip_in:
                zip_in.extractall(tmpdir_path)

            # Fix manifest.json
            manifest_path = tmpdir_path / 'manifest.json'
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)

            manifest['fwversion'] = version
            logger.info(f"✓ Added fwversion: {version}")

            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=4)

            # Repackage ZIP
            with zipfile.ZipFile(fixed_bundle, 'w', zipfile.ZIP_DEFLATED) as zip_out:
                for file_path in tmpdir_path.iterdir():
                    if file_path.is_file():
                        zip_out.write(file_path, file_path.name)

        # Step 2: Upload the fixed bundle
        logger.info("Uploading firmware...")

        with open(fixed_bundle, 'rb') as f:
            binary_data = f.read()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/zip"
        }

        response = requests.post(
            f"{self.BASE_URL}/firmwares",
            headers=headers,
            data=binary_data,
            timeout=300
        )

        # Cleanup
        fixed_bundle.unlink(missing_ok=True)

        if response.status_code not in [200, 201, 202]:
            logger.error(f"✗ Upload failed: {response.status_code} - {response.text}")
            raise Exception(f"Upload failed: {response.status_code} - {response.text}")

        result = response.json()
        uris = result.get('uris', [])

        logger.info(f"✓ Firmware uploaded: v{version} for {board}")
        if uris:
            logger.info(f"✓ Bundle URIs:")
            for uri in uris:
                logger.info(f"    {uri}")
        return result

    def list_firmwares(self, limit: int = 10) -> list:
        """
        nRF Cloud アカウントのファームウェア一覧を取得

        Args:
            limit: 取得する最大件数

        Returns:
            ファームウェアリスト
        """
        response = requests.get(
            f"{self.BASE_URL}/firmwares",
            headers=self.headers,
            params={'limit': limit},
            timeout=30
        )

        if response.status_code == 200:
            return response.json().get('items', [])
        else:
            logger.error(f"✗ Failed to list firmwares: {response.status_code}")
            return []

    def create_fota_job(
        self,
        firmware_id: str,
        device_ids: list = None,
        tag: str = None,
        description: str = None
    ) -> Dict:
        """
        FOTA ジョブを作成してデバイスに配信

        Args:
            firmware_id: アップロードしたファームウェアのID
            device_ids: デバイスIDのリスト（オプション）
            tag: デバイスタグ（オプション）
            description: ジョブの説明

        Returns:
            FOTA ジョブ詳細
        """
        payload = {
            'firmwareId': firmware_id,
            'description': description or f'FOTA job for firmware {firmware_id}'
        }

        if device_ids:
            payload['deviceIds'] = device_ids
        if tag:
            payload['tag'] = tag

        response = requests.post(
            f"{self.BASE_URL}/fota-jobs",
            headers=self.headers,
            json=payload,
            timeout=30
        )

        if response.status_code in [200, 201]:
            job = response.json()
            logger.info(f"✓ FOTA job created: {job.get('jobId')}")
            return job
        else:
            logger.error(f"✗ FOTA job creation failed: {response.status_code}")
            raise Exception(f"FOTA job creation failed: {response.status_code} - {response.text}")

    def get_firmware(self, firmware_id: str) -> Dict:
        """
        特定のファームウェア情報を取得

        Args:
            firmware_id: ファームウェアID

        Returns:
            ファームウェア情報
        """
        response = requests.get(
            f"{self.BASE_URL}/firmwares/{firmware_id}",
            headers=self.headers,
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get firmware: {response.status_code} - {response.text}")

    # ---- 位置情報管理 ----

    def get_location_history(
        self,
        device_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        page_limit: int = 100,
        page_next_token: Optional[str] = None
    ) -> Dict:
        """
        デバイスの位置情報履歴を取得

        Args:
            device_id: デバイスID
            start: 開始日時 (ISO 8601形式, 例: "2025-01-01T00:00:00.000Z")
            end: 終了日時 (ISO 8601形式)
            page_limit: 1ページあたりの最大件数
            page_next_token: ページネーショントークン

        Returns:
            位置情報履歴 (items, total, pageNextToken)
        """
        params = {
            "deviceId": device_id,
            "pageLimit": page_limit,
        }
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if page_next_token:
            params["pageNextToken"] = page_next_token

        response = requests.get(
            f"{self.BASE_URL}/location/history",
            headers=self.headers,
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(
                f"Failed to get location history: {response.status_code} - {response.text}"
            )

    def get_all_location_history(
        self,
        device_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> list:
        """
        ページネーションを自動処理して全位置情報履歴を取得

        Args:
            device_id: デバイスID
            start: 開始日時 (ISO 8601形式)
            end: 終了日時 (ISO 8601形式)

        Returns:
            全位置情報レコードのリスト
        """
        all_items = []
        page_next_token = None

        while True:
            result = self.get_location_history(
                device_id=device_id,
                start=start,
                end=end,
                page_limit=100,
                page_next_token=page_next_token
            )
            items = result.get("items", [])
            all_items.extend(items)

            page_next_token = result.get("pageNextToken")
            if not page_next_token:
                break

        return all_items

    def delete_location_record(self, device_id: str, record_id: str) -> bool:
        """
        位置情報レコードを削除

        Args:
            device_id: デバイスID
            record_id: レコードID (LocationTrackerId)

        Returns:
            削除成功の場合 True
        """
        response = requests.delete(
            f"{self.BASE_URL}/location/history/{device_id}/{record_id}",
            headers=self.headers,
            timeout=30
        )

        if response.status_code == 202:
            return True
        else:
            logger.error(
                f"Failed to delete location record {record_id}: "
                f"{response.status_code} - {response.text}"
            )
            return False
