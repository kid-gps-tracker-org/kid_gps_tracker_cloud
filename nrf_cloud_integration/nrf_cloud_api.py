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

        # Step 1: Create firmware entry with JSON metadata
        logger.info("Creating firmware entry...")
        metadata = {
            'name': f'kid_gps_tracker_{board}_v{version}',
            'version': version,
            'fwType': fw_type,
            'description': description or f'Kid GPS Tracker v{version} for {board}',
        }

        response = requests.post(
            f"{self.BASE_URL}/firmwares",
            headers=self.headers,  # application/json
            json=metadata,
            timeout=30
        )

        if response.status_code not in [200, 201]:
            logger.error(f"✗ Failed to create firmware entry: {response.status_code} - {response.text}")
            raise Exception(f"Failed to create firmware entry: {response.status_code} - {response.text}")

        result = response.json()
        firmware_id = result.get('id') or result.get('bundleId') or result.get('firmwareId')
        upload_url = result.get('uploadUrl') or result.get('url')

        logger.info(f"✓ Firmware entry created: {firmware_id}")

        # Step 2: Upload the binary file if upload URL is provided
        if upload_url:
            logger.info(f"Uploading binary to {upload_url}...")
            with open(bundle_path, 'rb') as f:
                binary_data = f.read()

            upload_response = requests.put(
                upload_url,
                data=binary_data,
                headers={'Content-Type': 'application/zip'},
                timeout=300
            )

            if upload_response.status_code not in [200, 201, 204]:
                logger.error(f"✗ Binary upload failed: {upload_response.status_code}")
                raise Exception(f"Binary upload failed: {upload_response.status_code}")

            logger.info(f"✓ Binary uploaded successfully")
        else:
            logger.info("No upload URL provided - firmware entry created without binary")

        logger.info(f"✓ Firmware uploaded: v{version} for {board}")
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
