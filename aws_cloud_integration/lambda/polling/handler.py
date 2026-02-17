#!/usr/bin/env python3
"""
Webhook Lambda ハンドラ
nRF Cloud Message Routing からのWebhookを受信し、DynamoDB に保存する。

nRF Cloud がデバイスメッセージをリアルタイムにPOSTしてくる。
Function URL 経由で受信し、既存の message_transformer で変換後、DynamoDB に書き込む。
"""
import os
import json
import logging
import math
from datetime import datetime, timezone

from message_transformer import transform_message, extract_device_state_update

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TEAM_ID = os.environ.get("NRF_CLOUD_TEAM_ID", "")


def lambda_handler(event, context):
    """
    Lambda エントリーポイント (Function URL)

    nRF Cloud Message Routing からのPOSTリクエストを処理する。
    - type: "system.verification" → 検証応答
    - type: "device.messages" → メッセージ処理・DynamoDB書き込み
    """
    logger.info(f"Received webhook event")

    body = event.get("body", "")
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse body: {e}")
        return _response(400, {"error": "Invalid JSON"})

    payload_type = payload.get("type", "")
    logger.info(f"Payload type: {payload_type}")

    # 検証リクエスト
    if payload_type == "system.verification":
        logger.info("Handling system verification request")
        return _response(200, {"message": "OK"})

    # デバイスメッセージ
    if payload_type == "device.messages":
        return _process_device_messages(payload)

    logger.warning(f"Unknown payload type: {payload_type}")
    return _response(200, {"message": "OK", "skipped": True})


def _process_device_messages(payload: dict) -> dict:
    """デバイスメッセージを処理してDynamoDBに保存する"""
    messages = payload.get("messages", [])
    logger.info(f"Processing {len(messages)} messages")

    records = []
    device_state_updates = {}

    for raw_message in messages:
        try:
            record = transform_message(raw_message)
        except Exception as e:
            logger.warning(f"Failed to transform message: {e}")
            record = None

        if record:
            records.append(record)

            state_update = extract_device_state_update(record)
            if state_update:
                # GROUND_FIX の位置は lastLocation を上書きしない。
                # 別フィールド lastGroundFixLocation に保存し、GNSS を優先する。
                # GNSS と GROUND_FIX がほぼ同時に届くが、GROUND_FIX が後着して
                # GNSS の lastLocation を上書きする問題を防ぐ。
                if record["messageType"] == "GROUND_FIX" and "lastLocation" in state_update:
                    state_update["lastGroundFixLocation"] = state_update.pop("lastLocation")
                device_id = state_update["deviceId"]
                if device_id not in device_state_updates:
                    device_state_updates[device_id] = state_update
                else:
                    _merge_device_state(device_state_updates[device_id], state_update)

    gnss_count = sum(1 for r in records if r["messageType"] == "GNSS")
    ground_fix_count = sum(1 for r in records if r["messageType"] == "GROUND_FIX")
    temp_count = sum(1 for r in records if r["messageType"] == "TEMP")
    logger.info(
        f"Transformed {len(records)} records "
        f"(GNSS: {gnss_count}, GROUND_FIX: {ground_fix_count}, TEMP: {temp_count})"
    )

    if records:
        _write_to_dynamodb(records, device_state_updates)

        # セーフゾーン判定: 位置情報の更新があったデバイスのみ実行
        location_updates = {
            device_id: state["lastLocation"]
            for device_id, state in device_state_updates.items()
            if "lastLocation" in state
        }
        if location_updates:
            _check_safezones_for_devices(location_updates)

    return _response(200, {
        "message": "OK",
        "messagesProcessed": len(records),
        "devicesUpdated": len(device_state_updates),
    })


def _response(status_code: int, body: dict) -> dict:
    """Function URL レスポンスを構築する（nRF Cloud検証用ヘッダー付き）"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "x-nrfcloud-team-id": TEAM_ID,
        },
        "body": json.dumps(body),
    }


def _write_to_dynamodb(records, device_state_updates):
    """DynamoDB にレコードを書き込む"""
    import boto3
    from botocore.exceptions import ClientError

    dynamodb = boto3.resource("dynamodb")

    # DeviceMessages テーブルへの書き込み
    messages_table_name = os.environ.get("DEVICE_MESSAGES_TABLE", "DeviceMessages")
    messages_table = dynamodb.Table(messages_table_name)

    written = 0
    for record in records:
        try:
            messages_table.put_item(
                Item=record,
                ConditionExpression="attribute_not_exists(deviceId) AND attribute_not_exists(#ts)",
                ExpressionAttributeNames={"#ts": "timestamp"},
            )
            written += 1
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.debug(f"Duplicate record skipped: {record['deviceId']} {record['timestamp']}")
            else:
                logger.error(f"DynamoDB write error: {e}")

    logger.info(f"Wrote {written}/{len(records)} records to {messages_table_name}")

    # DeviceState テーブルの更新
    state_table_name = os.environ.get("DEVICE_STATE_TABLE", "DeviceState")
    state_table = dynamodb.Table(state_table_name)

    for device_id, state in device_state_updates.items():
        try:
            update_expr_parts = ["#updatedAt = :updatedAt", "#lastSeen = :lastSeen"]
            expr_names = {
                "#updatedAt": "updatedAt",
                "#lastSeen": "lastSeen",
            }
            expr_values = {
                ":updatedAt": state["updatedAt"],
                ":lastSeen": state["lastSeen"],
            }

            if "lastLocation" in state:
                update_expr_parts.append("#lastLocation = :lastLocation")
                expr_names["#lastLocation"] = "lastLocation"
                expr_values[":lastLocation"] = state["lastLocation"]

            if "lastGroundFixLocation" in state:
                update_expr_parts.append("#lastGroundFixLocation = :lastGroundFixLocation")
                expr_names["#lastGroundFixLocation"] = "lastGroundFixLocation"
                expr_values[":lastGroundFixLocation"] = state["lastGroundFixLocation"]

            if "lastTemperature" in state:
                update_expr_parts.append("#lastTemperature = :lastTemperature")
                expr_names["#lastTemperature"] = "lastTemperature"
                expr_values[":lastTemperature"] = state["lastTemperature"]

            state_table.update_item(
                Key={"deviceId": device_id},
                UpdateExpression="SET " + ", ".join(update_expr_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
        except ClientError as e:
            logger.error(f"DeviceState update error for {device_id}: {e}")

    logger.info(f"Updated {len(device_state_updates)} device states")


def _merge_device_state(existing: dict, new: dict):
    """同一デバイスの DeviceState 更新をマージする（最新のみ保持）"""
    if "lastLocation" in new:
        existing["lastLocation"] = new["lastLocation"]
    if "lastGroundFixLocation" in new:
        existing["lastGroundFixLocation"] = new["lastGroundFixLocation"]
    if "lastTemperature" in new:
        existing["lastTemperature"] = new["lastTemperature"]
    existing["lastSeen"] = new["lastSeen"]
    existing["updatedAt"] = new["updatedAt"]


# ============================================================
# セーフゾーン判定
# interface_design.md Section 7 に基づく。
# ============================================================

def _check_safezones_for_devices(location_updates: dict):
    """
    位置情報の更新があったデバイスごとにセーフゾーン判定を実行する。

    Args:
        location_updates: {deviceId: lastLocation} の辞書
            lastLocation は extract_device_state_update() が返す location dict
            (lat/lon は Decimal 型)
    """
    import boto3
    dynamodb = boto3.resource("dynamodb")

    safezones_table = dynamodb.Table(os.environ.get("SAFE_ZONES_TABLE", "SafeZones"))
    messages_table = dynamodb.Table(os.environ.get("DEVICE_MESSAGES_TABLE", "DeviceMessages"))
    state_table = dynamodb.Table(os.environ.get("DEVICE_STATE_TABLE", "DeviceState"))
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN", "")

    for device_id, location in location_updates.items():
        try:
            _check_safezone_for_device(
                safezones_table, messages_table, state_table,
                sns_topic_arn, device_id, location,
            )
        except Exception as e:
            logger.error(f"Safe zone check failed for {device_id}: {e}")


def _check_safezone_for_device(
    safezones_table, messages_table, state_table,
    sns_topic_arn: str, device_id: str, location: dict,
):
    """
    1デバイスのセーフゾーン判定を実行する。

    処理フロー (interface_design.md Section 7.1):
    1. GNSS のみ判定対象（GROUND_FIX は誤差が大きいためスキップ）
    2. 有効なセーフゾーン一覧を取得
    3. 旧 safeZoneStatus を取得
    4. 各ゾーンとの距離をヒステリシス付きで計算し新 safeZoneStatus を決定
    5. 状態変化があったゾーンに ZONE_ENTER/ZONE_EXIT を書き込み + SNS 通知
    6. DeviceState の inSafeZone / safeZoneStatus を更新
    """
    from boto3.dynamodb.conditions import Key as DynamoKey
    from botocore.exceptions import ClientError

    # GROUND_FIX は誤差が大きく(MCELL で数百m)誤検知の原因となるためスキップ
    if location.get("source") == "GROUND_FIX":
        logger.debug(f"Skipping zone check for GROUND_FIX location: device={device_id}")
        return

    # 有効なセーフゾーンを取得
    zones_response = safezones_table.query(
        KeyConditionExpression=DynamoKey("deviceId").eq(device_id)
    )
    enabled_zones = [z for z in zones_response.get("Items", []) if z.get("enabled", False)]

    if not enabled_zones:
        return

    # 旧 safeZoneStatus を取得
    state_response = state_table.get_item(Key={"deviceId": device_id})
    old_zone_status = state_response.get("Item", {}).get("safeZoneStatus", {})

    device_lat = float(location["lat"])
    device_lon = float(location["lon"])

    # ヒステリシス: GPS精度のゆらぎによる境界オシレーションを防ぐ
    # 入場判定: radius * (1 - HYSTERESIS) 以内で確定
    # 退場判定: radius * (1 + HYSTERESIS) 以上で確定
    HYSTERESIS_RATIO = 0.15

    new_zone_status = {}
    zone_events = []  # [(event_type, zone)]

    for zone in enabled_zones:
        zone_id = zone["zoneId"]
        center = zone.get("center", {})
        zone_lat = float(center.get("lat", 0))
        zone_lon = float(center.get("lon", 0))
        radius_m = float(zone.get("radius", 0))

        distance_m = _haversine_distance_m(device_lat, device_lon, zone_lat, zone_lon)

        old_status = old_zone_status.get(zone_id)
        # old_status が None (初回) は状態変化なし扱いとする
        if old_status is True:
            # ゾーン内 → radius * 1.15 を超えた場合のみ退場と判定
            if distance_m > radius_m * (1 + HYSTERESIS_RATIO):
                new_zone_status[zone_id] = False
                zone_events.append(("ZONE_EXIT", zone))
            else:
                new_zone_status[zone_id] = True
        elif old_status is False:
            # ゾーン外 → radius * 0.85 以内に入った場合のみ入場と判定
            if distance_m <= radius_m * (1 - HYSTERESIS_RATIO):
                new_zone_status[zone_id] = True
                zone_events.append(("ZONE_ENTER", zone))
            else:
                new_zone_status[zone_id] = False
        else:
            # 初回: イベントなし、現在位置でステータスを初期化
            new_zone_status[zone_id] = distance_m <= radius_m

    # イベント書き込み + SNS 通知
    if zone_events:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        now_unix = int(datetime.now(timezone.utc).timestamp())
        ttl = now_unix + (30 * 24 * 3600)

        for event_type, zone in zone_events:
            record = {
                "deviceId": device_id,
                "timestamp": now_iso,
                "messageType": event_type,
                "lat": location["lat"],
                "lon": location["lon"],
                "zoneId": zone["zoneId"],
                "zoneName": zone.get("name", ""),
                "receivedAt": now_iso,
                "ttl": ttl,
            }
            if location.get("accuracy") is not None:
                record["accuracy"] = location["accuracy"]

            try:
                messages_table.put_item(
                    Item=record,
                    ConditionExpression="attribute_not_exists(deviceId) AND attribute_not_exists(#ts)",
                    ExpressionAttributeNames={"#ts": "timestamp"},
                )
                logger.info(f"{event_type}: device={device_id}, zone={zone['zoneId']}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    logger.debug(f"Zone event duplicate skipped: {device_id} {now_iso}")
                else:
                    logger.error(f"Zone event write error: {e}")

            if sns_topic_arn:
                _send_zone_notification(sns_topic_arn, device_id, event_type, zone, location, now_iso)

    # DeviceState の inSafeZone / safeZoneStatus を更新
    new_in_safe_zone = any(new_zone_status.values())
    try:
        state_table.update_item(
            Key={"deviceId": device_id},
            UpdateExpression="SET #inSafeZone = :inSafeZone, #safeZoneStatus = :safeZoneStatus",
            ExpressionAttributeNames={
                "#inSafeZone": "inSafeZone",
                "#safeZoneStatus": "safeZoneStatus",
            },
            ExpressionAttributeValues={
                ":inSafeZone": new_in_safe_zone,
                ":safeZoneStatus": new_zone_status,
            },
        )
    except ClientError as e:
        logger.error(f"DeviceState inSafeZone update error for {device_id}: {e}")


def _haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    2点間の距離をメートルで返す (Haversine 公式)。
    interface_design.md Section 7.1 の計算式に準拠。
    """
    R = 6_371_000  # 地球半径 (m)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _send_zone_notification(
    sns_topic_arn: str, device_id: str, event_type: str,
    zone: dict, location: dict, detected_at: str,
):
    """
    SNS 経由で APNs プッシュ通知を送信する。
    api_specification.md Section 6 のペイロード形式に準拠。
    """
    import boto3

    zone_name = zone.get("name", "")
    if event_type == "ZONE_EXIT":
        title = "セーフゾーンアラート"
        body_text = f"デバイスがセーフゾーン「{zone_name}」から離れました"
    else:
        title = "セーフゾーン通知"
        body_text = f"デバイスがセーフゾーン「{zone_name}」に戻りました"

    accuracy = float(location["accuracy"]) if location.get("accuracy") is not None else None
    apns_payload = {
        "aps": {
            "alert": {"title": title, "body": body_text},
            "sound": "default",
        },
        "data": {
            "type": event_type,
            "deviceId": device_id,
            "zoneId": zone["zoneId"],
            "zoneName": zone_name,
            "location": {
                "lat": float(location["lat"]),
                "lon": float(location["lon"]),
                "accuracy": accuracy,
                "source": location.get("source", "GNSS"),
                "timestamp": location.get("timestamp", detected_at),
            },
            "detectedAt": detected_at,
        },
    }
    if event_type == "ZONE_EXIT":
        apns_payload["aps"]["badge"] = 1

    try:
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=sns_topic_arn,
            Message=json.dumps({
                "default": json.dumps(apns_payload, ensure_ascii=False),
                "APNS": json.dumps(apns_payload, ensure_ascii=False),
                "APNS_SANDBOX": json.dumps(apns_payload, ensure_ascii=False),
            }),
            MessageStructure="json",
            MessageAttributes={
                "deviceId": {
                    "DataType": "String",
                    "StringValue": device_id,
                },
            },
        )
        logger.info(f"SNS notification sent: {event_type} for {device_id} zone={zone['zoneId']}")
    except Exception as e:
        logger.error(f"SNS publish error for {device_id}: {e}")
