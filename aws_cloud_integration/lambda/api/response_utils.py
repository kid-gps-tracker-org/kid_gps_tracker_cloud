"""
レスポンスユーティリティ
DecimalEncoder と共通レスポンスビルダーを提供する。
"""
import json
from decimal import Decimal
from typing import Any


class DecimalEncoder(json.JSONEncoder):
    """
    DynamoDB の Decimal を JSON Number に変換するカスタムエンコーダー。
    整数値の場合は int、小数値の場合は float に変換する。
    """

    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj == int(obj):
                return int(obj)
            return float(obj)
        return super().default(obj)


_COMMON_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-api-key",
    "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE,OPTIONS",
}


def success_response(status_code: int, body: Any) -> dict:
    """
    成功レスポンスを生成する。

    Args:
        status_code: HTTP ステータスコード (200, 201)
        body: レスポンスボディ（DecimalEncoder で JSON シリアライズ）

    Returns:
        API Gateway proxy レスポンス dict
    """
    response = {
        "statusCode": status_code,
        "headers": _COMMON_HEADERS.copy(),
    }
    if body is not None:
        response["body"] = json.dumps(body, cls=DecimalEncoder, ensure_ascii=False)
    return response


def error_response(status_code: int, code: str, message: str) -> dict:
    """
    エラーレスポンスを生成する。API 仕様書 3.9 ApiError 型に準拠。

    Args:
        status_code: HTTP ステータスコード (400, 403, 404, 500, 502)
        code: エラーコード (SCREAMING_SNAKE_CASE)
        message: 人間可読エラーメッセージ

    Returns:
        API Gateway proxy レスポンス dict
    """
    return {
        "statusCode": status_code,
        "headers": _COMMON_HEADERS.copy(),
        "body": json.dumps({
            "error": {
                "code": code,
                "message": message,
            }
        }, ensure_ascii=False),
    }
