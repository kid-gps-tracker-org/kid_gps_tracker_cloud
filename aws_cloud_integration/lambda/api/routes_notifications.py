"""
通知トークンエンドポイント
API 仕様書 4.11 に基づく。

POST /devices/{deviceId}/notification-token
"""
import os
import json
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


def _get_or_create_platform_application():
    """
    SNS Platform Application ARN を取得する。
    存在しなければ Secrets Manager から APNs 証明書を取得して作成する。
    """
    sns_client = boto3.client("sns")

    app_name = "kid-gps-tracker-apns"

    # 既存の Platform Application を検索
    paginator = sns_client.get_paginator("list_platform_applications")
    for page in paginator.paginate():
        for app in page.get("PlatformApplications", []):
            arn = app["PlatformApplicationArn"]
            if app_name in arn:
                return arn

    # 存在しない場合は作成
    sm_client = boto3.client("secretsmanager")

    cert_arn = os.environ.get("APNS_CERT_SECRET_ARN")
    key_arn = os.environ.get("APNS_KEY_SECRET_ARN")
    if not cert_arn or not key_arn:
        raise RuntimeError("APNs certificate/key secret ARN not configured")

    cert_pem = sm_client.get_secret_value(SecretId=cert_arn)["SecretString"]
    key_pem = sm_client.get_secret_value(SecretId=key_arn)["SecretString"]

    # APNS_SANDBOX (開発) または APNS (本番)
    platform = "APNS_SANDBOX"

    response = sns_client.create_platform_application(
        Name=app_name,
        Platform=platform,
        Attributes={
            "PlatformCredential": key_pem,
            "PlatformPrincipal": cert_pem,
        },
    )
    arn = response["PlatformApplicationArn"]
    logger.info(f"Created SNS Platform Application: {arn}")
    return arn


def post_notification_token(event: dict) -> dict:
    """
    POST /devices/{deviceId}/notification-token
    APNs デバイストークンを登録し、セーフゾーンアラートを受信可能にする。
    API 仕様書 4.11 に基づく。

    Request body: { "token": "<APNs device token>" }
    Response: {
        "deviceId": "...",
        "notification": { "enabled": true, "endpointArn": "..." }
    }
    """
    device_id = get_device_id(event)
    if not device_id:
        return error_response(400, "INVALID_REQUEST", "deviceId is required")

    # リクエストボディパース
    body, parse_error = parse_json_body(event)
    if parse_error:
        return error_response(400, "INVALID_REQUEST", parse_error)

    token = body.get("token")
    if not token:
        return error_response(400, "INVALID_REQUEST",
                              "Required field 'token' is missing")

    # デバイス存在チェック
    table = _get_device_state_table()
    response = table.get_item(Key={"deviceId": device_id})
    item = response.get("Item")
    if not item:
        return error_response(404, "DEVICE_NOT_FOUND",
                              f"Device {device_id} not found")

    try:
        sns_client = boto3.client("sns")

        # 1. SNS Platform Application の取得/作成
        platform_app_arn = _get_or_create_platform_application()

        # 2. デバイストークンを SNS Platform Endpoint として登録
        #    create_platform_endpoint は冪等: 同じトークンなら既存の endpoint を返す
        endpoint_response = sns_client.create_platform_endpoint(
            PlatformApplicationArn=platform_app_arn,
            Token=token,
            CustomUserData=device_id,
        )
        endpoint_arn = endpoint_response["EndpointArn"]

        # トークンが更新された場合（アプリ再インストールなど）は属性を更新
        sns_client.set_endpoint_attributes(
            EndpointArn=endpoint_arn,
            Attributes={
                "Token": token,
                "Enabled": "true",
                "CustomUserData": device_id,
            },
        )

        # 3. アラートトピックにサブスクライブ（フィルターポリシー付き）
        topic_arn = os.environ.get("SNS_TOPIC_ARN")
        if not topic_arn:
            logger.error("SNS_TOPIC_ARN not configured")
            return error_response(500, "INTERNAL_ERROR",
                                  "SNS topic not configured")

        # 既存サブスクリプションがあれば解除してから再登録（フィルター更新のため）
        old_sub_arn = item.get("snsSubscriptionArn")
        if old_sub_arn and old_sub_arn.startswith("arn:"):
            try:
                sns_client.unsubscribe(SubscriptionArn=old_sub_arn)
            except Exception:
                pass  # 既に削除済みの場合は無視

        subscribe_response = sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="application",
            Endpoint=endpoint_arn,
            Attributes={
                "FilterPolicy": json.dumps({"deviceId": [device_id]}),
            },
            ReturnSubscriptionArn=True,
        )
        subscription_arn = subscribe_response["SubscriptionArn"]

        # 4. DeviceState にエンドポイント情報を保存
        table.update_item(
            Key={"deviceId": device_id},
            UpdateExpression="SET #ep = :ep, #sub = :sub",
            ExpressionAttributeNames={
                "#ep": "snsEndpointArn",
                "#sub": "snsSubscriptionArn",
            },
            ExpressionAttributeValues={
                ":ep": endpoint_arn,
                ":sub": subscription_arn,
            },
        )

        return success_response(201, {
            "deviceId": device_id,
            "notification": {
                "enabled": True,
                "endpointArn": endpoint_arn,
            },
        })

    except Exception as e:
        logger.exception(f"Failed to register notification token: {e}")
        return error_response(500, "INTERNAL_ERROR",
                              "Failed to register notification token")
