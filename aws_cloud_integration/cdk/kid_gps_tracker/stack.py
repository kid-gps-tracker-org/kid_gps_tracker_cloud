"""
Kid GPS Tracker AWS CDK Stack

interface_design.md セクション 11 に基づく AWS インフラ定義。
現段階ではポーリング Lambda と関連リソースのみデプロイ。
（API Lambda, API Gateway, SNS/APNs は後日追加）
"""
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as lambda_,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

# Lambda ビルド済みパッケージのパス（build_lambda.py で生成）
LAMBDA_POLLING_BUILD_DIR = str(Path(__file__).parent.parent / ".build" / "polling")


class KidGpsTrackerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================
        # Secrets Manager: nRF Cloud API Key
        # ============================================================
        api_key_secret = secretsmanager.Secret(
            self,
            "NrfCloudApiKey",
            secret_name="kid-gps-tracker/nrf-cloud-api-key",
            description="nRF Cloud REST API key for polling Lambda",
        )

        # ============================================================
        # DynamoDB Tables
        # ============================================================

        # DeviceMessages テーブル (TTL 有効)
        device_messages_table = dynamodb.Table(
            self,
            "DeviceMessages",
            table_name="DeviceMessages",
            partition_key=dynamodb.Attribute(
                name="deviceId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            time_to_live_attribute="ttl",
        )

        # GSI: MessageTypeIndex
        device_messages_table.add_global_secondary_index(
            index_name="MessageTypeIndex",
            partition_key=dynamodb.Attribute(
                name="deviceId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="messageType", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # DeviceState テーブル
        device_state_table = dynamodb.Table(
            self,
            "DeviceState",
            table_name="DeviceState",
            partition_key=dynamodb.Attribute(
                name="deviceId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # SafeZones テーブル
        safe_zones_table = dynamodb.Table(
            self,
            "SafeZones",
            table_name="SafeZones",
            partition_key=dynamodb.Attribute(
                name="deviceId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="zoneId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # PollingState テーブル
        polling_state_table = dynamodb.Table(
            self,
            "PollingState",
            table_name="PollingState",
            partition_key=dynamodb.Attribute(
                name="configKey", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ============================================================
        # Lambda: PollingFunction
        # ============================================================
        polling_function = lambda_.Function(
            self,
            "PollingFunction",
            function_name="kid-gps-tracker-polling",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(LAMBDA_POLLING_BUILD_DIR),
            memory_size=256,
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=1,
            environment={
                "NRF_CLOUD_API_KEY_SECRET_ARN": api_key_secret.secret_arn,
                "DEVICE_MESSAGES_TABLE": device_messages_table.table_name,
                "DEVICE_STATE_TABLE": device_state_table.table_name,
                "POLLING_STATE_TABLE": polling_state_table.table_name,
            },
        )

        # Lambda に Secrets Manager の読み取り権限を付与
        api_key_secret.grant_read(polling_function)

        # Lambda に DynamoDB テーブルの読み書き権限を付与
        device_messages_table.grant_read_write_data(polling_function)
        device_state_table.grant_read_write_data(polling_function)
        polling_state_table.grant_read_write_data(polling_function)

        # ============================================================
        # EventBridge: 5分間隔のポーリングルール
        # ============================================================
        polling_rule = events.Rule(
            self,
            "PollingSchedule",
            rule_name="kid-gps-tracker-polling-schedule",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            enabled=False,  # デプロイ後に手動で有効化
        )
        polling_rule.add_target(targets.LambdaFunction(polling_function))

        # ============================================================
        # Outputs
        # ============================================================
        cdk.CfnOutput(
            self,
            "PollingFunctionArn",
            value=polling_function.function_arn,
            description="Polling Lambda Function ARN",
        )
        cdk.CfnOutput(
            self,
            "ApiKeySecretArn",
            value=api_key_secret.secret_arn,
            description="nRF Cloud API Key Secret ARN",
        )
        cdk.CfnOutput(
            self,
            "DeviceMessagesTableName",
            value=device_messages_table.table_name,
        )
        cdk.CfnOutput(
            self,
            "DeviceStateTableName",
            value=device_state_table.table_name,
        )
        cdk.CfnOutput(
            self,
            "PollingStateTableName",
            value=polling_state_table.table_name,
        )
