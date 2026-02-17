"""
ファームウェア/FOTA エンドポイント
API 仕様書 4.8, 4.9, 4.10 に基づく。

GET  /devices/{deviceId}/firmware
POST /devices/{deviceId}/firmware/update
GET  /devices/{deviceId}/firmware/status
"""
import os
import logging

import boto3

from response_utils import success_response, error_response
from validators import get_device_id, parse_json_body

logger = logging.getLogger(__name__)


def _get_device_state_table():
    """DeviceState テーブルリソースを取得する。"""
    table_name = os.environ.get("DEVICE_STATE_TABLE", "DeviceState")
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def _get_api_key() -> str:
    """
    nRF Cloud API キーを取得する。
    既存の polling/handler.py のパターンに準拠。
    """
    local_mode = os.environ.get("LOCAL_MODE", "false").lower() == "true"

    if local_mode:
        return os.environ.get("NRF_CLOUD_API_KEY", "")

    # AWS モード: Secrets Manager から取得
    secret_arn = os.environ.get("NRF_CLOUD_API_KEY_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        return response["SecretString"]

    return os.environ.get("NRF_CLOUD_API_KEY", "")


def get_firmware(event: dict) -> dict:
    """
    GET /devices/{deviceId}/firmware
    ファームウェア情報を取得する。
    API 仕様書 4.8 に基づく。

    Response: {
        "deviceId": "...",
        "firmware": { "currentVersion": "1.0.0", "lastUpdated": "..." }
    }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    table = _get_device_state_table()
    response = table.get_item(Key={"deviceId": device_id})
    item = response.get("Item")

    if not item:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    return success_response(200, {
        "deviceId": device_id,
        "firmware": {
            "currentVersion": item.get("firmwareVersion", None),
            "lastUpdated": item.get("firmwareLastUpdated", None),
        },
    })


def post_firmware_update(event: dict) -> dict:
    """
    POST /devices/{deviceId}/firmware/update
    FOTA ジョブを作成し、ファームウェア更新を開始する。
    API 仕様書 4.9 に基づく。

    Request body: { "firmwareId": "..." }
    Response: {
        "deviceId": "...",
        "fota": { "jobId", "status", "firmwareId", "createdAt", "completedAt" }
    }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    # リクエストボディパース
    body, parse_error = parse_json_body(event)
    if parse_error:
        return error_response(400, "INVALID_REQUEST", parse_error)

    firmware_id = body.get("firmwareId")
    if not firmware_id:
        return error_response(400, "INVALID_REQUEST",
                              "Required field 'firmwareId' is missing")

    # デバイス存在チェック
    table = _get_device_state_table()
    response = table.get_item(Key={"deviceId": device_id})
    if "Item" not in response:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    # nRF Cloud FOTA ジョブ作成
    try:
        api_key = _get_api_key()
        if not api_key:
            logger.error("nRF Cloud API key not configured")
            return error_response(500, "INTERNAL_ERROR",
                                  "nRF Cloud API key not configured")

        from nrf_cloud_client import NrfCloudFotaClient
        client = NrfCloudFotaClient(api_key)
        result = client.create_fota_job(firmware_id, [device_id])

        fota_info = {
            "jobId": result.get("jobId"),
            "status": "QUEUED",
            "firmwareId": firmware_id,
            "createdAt": result.get("createdAt"),
            "completedAt": None,
        }

        # DeviceState に FOTA ジョブ情報を保存（仕様書 4.9 ステップ4）
        try:
            table.update_item(
                Key={"deviceId": device_id},
                UpdateExpression="SET #lastFota = :lastFota",
                ExpressionAttributeNames={"#lastFota": "lastFota"},
                ExpressionAttributeValues={":lastFota": fota_info},
            )
        except Exception as save_err:
            logger.error(f"Failed to save FOTA job to DeviceState: {save_err}")

        return success_response(201, {
            "deviceId": device_id,
            "fota": fota_info,
        })
    except Exception as e:
        logger.exception(f"Failed to create FOTA job: {e}")
        return error_response(502, "NRF_CLOUD_ERROR", f"nRF Cloud API error")


def get_firmware_status(event: dict) -> dict:
    """
    GET /devices/{deviceId}/firmware/status
    直近の FOTA ジョブのステータスを取得する。
    API 仕様書 4.10 に基づく。

    Response: {
        "deviceId": "...",
        "fota": { "jobId", "status", "firmwareId", "createdAt", "completedAt" }
    }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    # デバイス存在チェック + 最新 FOTA jobId 取得
    table = _get_device_state_table()
    response = table.get_item(Key={"deviceId": device_id})
    item = response.get("Item")

    if not item:
        return error_response(404, "DEVICE_NOT_FOUND", f"Device {device_id} not found")

    # lastFotaJobId から FOTA ジョブ情報を取得
    last_fota = item.get("lastFota")
    if not last_fota:
        return error_response(404, "NO_FOTA_JOB", "No FOTA job found for device")

    job_id = last_fota.get("jobId")
    if not job_id:
        return error_response(404, "NO_FOTA_JOB", "No FOTA job found for device")

    # nRF Cloud から最新ステータスを取得
    try:
        api_key = _get_api_key()
        if not api_key:
            logger.error("nRF Cloud API key not configured")
            return error_response(500, "INTERNAL_ERROR",
                                  "nRF Cloud API key not configured")

        from nrf_cloud_client import NrfCloudFotaClient
        client = NrfCloudFotaClient(api_key)
        result = client.get_fota_job(job_id)

        return success_response(200, {
            "deviceId": device_id,
            "fota": {
                "jobId": result.get("jobId", job_id),
                "status": result.get("status", "UNKNOWN"),
                "firmwareId": result.get("bundleId") or last_fota.get("firmwareId"),
                "createdAt": result.get("createdAt") or last_fota.get("createdAt"),
                "completedAt": result.get("completedAt"),
            },
        })
    except Exception as e:
        logger.exception(f"Failed to get FOTA status: {e}")
        return error_response(502, "NRF_CLOUD_ERROR", f"nRF Cloud API error")
