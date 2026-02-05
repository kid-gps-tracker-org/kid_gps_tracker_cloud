"""
nRF Cloud FOTA クライアント
FOTA ジョブの作成とステータス取得を担当する。
既存の polling/nrf_cloud_client.py のパターンに準拠。
"""
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class NrfCloudFotaClient:
    """nRF Cloud REST API クライアント（FOTA 操作用）"""

    BASE_URL = "https://api.nrfcloud.com/v1"

    def __init__(self, api_key: str):
        """
        クライアントを初期化する。

        Args:
            api_key: nRF Cloud API キー
        """
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def create_fota_job(
        self,
        firmware_id: str,
        device_ids: List[str],
        description: Optional[str] = None,
    ) -> Dict:
        """
        FOTA ジョブを作成する。

        Args:
            firmware_id: ファームウェアバンドル ID
            device_ids: 対象デバイス ID のリスト
            description: ジョブの説明（オプション）

        Returns:
            FOTA ジョブ情報 (jobId, createdAt 等を含む)

        Raises:
            Exception: API 呼び出しに失敗した場合
        """
        payload = {
            "bundleId": firmware_id,
            "deviceIds": device_ids,
        }
        if description:
            payload["description"] = description

        response = requests.post(
            f"{self.BASE_URL}/fota-jobs",
            headers=self.headers,
            json=payload,
            timeout=30,
        )

        if response.status_code in [200, 201, 202]:
            return response.json()
        else:
            logger.error(f"FOTA job creation failed: {response.status_code} - {response.text}")
            raise Exception(f"FOTA job creation failed: {response.status_code}")

    def get_fota_job(self, job_id: str) -> Dict:
        """
        FOTA ジョブのステータスを取得する。

        Args:
            job_id: FOTA ジョブ ID

        Returns:
            FOTA ジョブ情報 (status, completedAt 等を含む)

        Raises:
            Exception: API 呼び出しに失敗した場合
        """
        response = requests.get(
            f"{self.BASE_URL}/fota-jobs/{job_id}",
            headers=self.headers,
            timeout=30,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Get FOTA job failed: {response.status_code} - {response.text}")
            raise Exception(f"Get FOTA job failed: {response.status_code}")
