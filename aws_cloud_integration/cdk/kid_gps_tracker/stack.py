"""
Kid GPS Tracker AWS CDK Stack

interface_design.md セクション 11 に基づく AWS インフラ定義。
- Webhook Lambda: nRF Cloud Message Routing からリアルタイムにメッセージ受信
- API Lambda: iPhone アプリ向け REST API
- API Gateway: REST API エンドポイント (x-api-key 認証)
"""
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigateway,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

# Lambda ビルド済みパッケージのパス（build_lambda.py で生成）
LAMBDA_WEBHOOK_BUILD_DIR = str(Path(__file__).parent.parent / ".build" / "polling")
LAMBDA_API_BUILD_DIR = str(Path(__file__).parent.parent / ".build" / "api")


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

        # ============================================================
        # Lambda: WebhookFunction (nRF Cloud Message Routing 受信)
        # ============================================================
        webhook_function = lambda_.Function(
            self,
            "PollingFunction",
            function_name="kid-gps-tracker-polling",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(LAMBDA_WEBHOOK_BUILD_DIR),
            memory_size=256,
            timeout=Duration.seconds(30),
            reserved_concurrent_executions=1,
            environment={
                "NRF_CLOUD_TEAM_ID": "80ea9eb0-c769-4deb-9a97-06ef4e91aff7",
                "NRF_CLOUD_API_KEY_SECRET_ARN": api_key_secret.secret_arn,
                "DEVICE_MESSAGES_TABLE": device_messages_table.table_name,
                "DEVICE_STATE_TABLE": device_state_table.table_name,
            },
        )

        # Lambda に Secrets Manager の読み取り権限を付与（将来のFOTA用）
        api_key_secret.grant_read(webhook_function)

        # Lambda に DynamoDB テーブルの読み書き権限を付与
        device_messages_table.grant_read_write_data(webhook_function)
        device_state_table.grant_read_write_data(webhook_function)

        # Function URL（nRF Cloud からの直接HTTP POST用）
        webhook_url = webhook_function.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # ============================================================
        # Lambda: ApiFunction
        # ============================================================
        api_function = lambda_.Function(
            self,
            "ApiFunction",
            function_name="kid-gps-tracker-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(LAMBDA_API_BUILD_DIR),
            memory_size=256,
            timeout=Duration.seconds(30),
            environment={
                "NRF_CLOUD_API_KEY_SECRET_ARN": api_key_secret.secret_arn,
                "DEVICE_MESSAGES_TABLE": device_messages_table.table_name,
                "DEVICE_STATE_TABLE": device_state_table.table_name,
                "SAFE_ZONES_TABLE": safe_zones_table.table_name,
            },
        )

        # API Lambda に権限を付与
        api_key_secret.grant_read(api_function)
        device_messages_table.grant_read_data(api_function)
        device_state_table.grant_read_data(api_function)
        safe_zones_table.grant_read_write_data(api_function)

        # ============================================================
        # API Gateway: REST API
        # ============================================================
        api = apigateway.RestApi(
            self,
            "KidGpsTrackerApi",
            rest_api_name="kid-gps-tracker-api",
            description="Kid GPS Tracker REST API for iPhone app",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=100,
                throttling_burst_limit=50,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "x-api-key"],
            ),
        )

        # API Key 認証
        api_key = api.add_api_key(
            "KidGpsTrackerApiKey",
            api_key_name="kid-gps-tracker-api-key",
        )

        usage_plan = api.add_usage_plan(
            "KidGpsTrackerUsagePlan",
            name="kid-gps-tracker-usage-plan",
            throttle=apigateway.ThrottleSettings(
                rate_limit=100,
                burst_limit=50,
            ),
        )
        usage_plan.add_api_key(api_key)
        usage_plan.add_api_stage(stage=api.deployment_stage)

        # Lambda インテグレーション
        api_integration = apigateway.LambdaIntegration(api_function)

        # ルート定義
        # GET /devices
        devices = api.root.add_resource("devices")
        devices.add_method("GET", api_integration, api_key_required=True)

        # /devices/{deviceId}
        device = devices.add_resource("{deviceId}")

        # GET /devices/{deviceId}/location
        location = device.add_resource("location")
        location.add_method("GET", api_integration, api_key_required=True)

        # GET /devices/{deviceId}/temperature
        temperature = device.add_resource("temperature")
        temperature.add_method("GET", api_integration, api_key_required=True)

        # GET /devices/{deviceId}/history
        history = device.add_resource("history")
        history.add_method("GET", api_integration, api_key_required=True)

        # GET/PUT /devices/{deviceId}/safezones
        safezones = device.add_resource("safezones")
        safezones.add_method("GET", api_integration, api_key_required=True)
        safezones.add_method("PUT", api_integration, api_key_required=True)

        # DELETE /devices/{deviceId}/safezones/{zoneId}
        safezone = safezones.add_resource("{zoneId}")
        safezone.add_method("DELETE", api_integration, api_key_required=True)

        # /devices/{deviceId}/firmware
        firmware = device.add_resource("firmware")
        firmware.add_method("GET", api_integration, api_key_required=True)

        # POST /devices/{deviceId}/firmware/update
        firmware_update = firmware.add_resource("update")
        firmware_update.add_method("POST", api_integration, api_key_required=True)

        # GET /devices/{deviceId}/firmware/status
        firmware_status = firmware.add_resource("status")
        firmware_status.add_method("GET", api_integration, api_key_required=True)

        # ============================================================
        # Outputs
        # ============================================================
        cdk.CfnOutput(
            self,
            "WebhookUrl",
            value=webhook_url.url,
            description="Webhook Function URL (for nRF Cloud Message Routing)",
        )
        cdk.CfnOutput(
            self,
            "WebhookFunctionArn",
            value=webhook_function.function_arn,
            description="Webhook Lambda Function ARN",
        )
        cdk.CfnOutput(
            self,
            "ApiFunctionArn",
            value=api_function.function_arn,
            description="API Lambda Function ARN",
        )
        cdk.CfnOutput(
            self,
            "ApiUrl",
            value=api.url,
            description="API Gateway URL",
        )
        cdk.CfnOutput(
            self,
            "ApiKeyId",
            value=api_key.key_id,
            description="API Key ID (retrieve value via AWS CLI: aws apigateway get-api-key --api-key <id> --include-value)",
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
            "SafeZonesTableName",
            value=safe_zones_table.table_name,
        )
