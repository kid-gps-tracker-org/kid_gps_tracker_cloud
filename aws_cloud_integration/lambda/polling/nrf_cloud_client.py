#!/usr/bin/env python3
"""
nRF Cloud メッセージ取得クライアント
ポーリング Lambda 用。既存の nrf_cloud_api.py のパターンを踏襲。

ドキュメント: https://api.nrfcloud.com/
"""
import requests
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class NrfCloudClient:
    """nRF Cloud REST API クライアント（メッセージ取得特化）"""

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

    def get_messages(
        self,
        inclusive_start: Optional[str] = None,
        app_id: Optional[str] = None,
        device_id: Optional[str] = None,
        page_limit: int = 100,
        page_next_token: Optional[str] = None
    ) -> Dict:
        """
        デバイスメッセージを取得

        Args:
            inclusive_start: この時刻以降のメッセージを取得 (ISO 8601)
            app_id: フィルタ ("GNSS", "TEMP" 等)
            device_id: 特定デバイスのみ取得
            page_limit: 1ページあたりの最大件数
            page_next_token: ページネーショントークン

        Returns:
            メッセージレスポンス (items, total, pageNextToken)
        """
        params = {
            "pageLimit": page_limit,
        }
        if inclusive_start:
            params["inclusiveStart"] = inclusive_start
        if app_id:
            params["appId"] = app_id
        if device_id:
            params["deviceId"] = device_id
        if page_next_token:
            params["pageNextToken"] = page_next_token

        response = requests.get(
            f"{self.BASE_URL}/messages",
            headers=self.headers,
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                f"Failed to get messages: {response.status_code} - {response.text}"
            )
            raise Exception(
                f"Failed to get messages: {response.status_code} - {response.text}"
            )

    def get_all_messages(
        self,
        inclusive_start: Optional[str] = None,
        app_id: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> List[Dict]:
        """
        ページネーションを自動処理して全メッセージを取得

        Args:
            inclusive_start: この時刻以降のメッセージを取得 (ISO 8601)
            app_id: フィルタ ("GNSS", "TEMP" 等)
            device_id: 特定デバイスのみ取得

        Returns:
            全メッセージのリスト
        """
        all_items = []
        page_next_token = None

        while True:
            result = self.get_messages(
                inclusive_start=inclusive_start,
                app_id=app_id,
                device_id=device_id,
                page_limit=100,
                page_next_token=page_next_token
            )
            items = result.get("items", [])
            all_items.extend(items)

            page_next_token = result.get("pageNextToken")
            if not page_next_token:
                break

            logger.info(f"Fetched {len(all_items)} messages, getting next page...")

        return all_items

    def get_devices(self) -> List[Dict]:
        """
        アカウントのデバイス一覧を取得

        Returns:
            デバイスリスト
        """
        response = requests.get(
            f"{self.BASE_URL}/devices",
            headers=self.headers,
            timeout=30
        )

        if response.status_code == 200:
            return response.json().get("items", [])
        else:
            logger.error(
                f"Failed to get devices: {response.status_code} - {response.text}"
            )
            return []
