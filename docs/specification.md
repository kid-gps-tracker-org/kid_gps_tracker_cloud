# Kid GPS Tracker システム仕様書

## 文書情報

| 項目 | 内容 |
|---|---|
| 文書名 | Kid GPS Tracker システム仕様書 |
| バージョン | 1.1 |
| 作成日 | 2026-02-03 |
| 更新日 | 2026-02-10 |
| ステータス | 試作仕様確定 |

---

## 1. システム概要

子供の見守りを目的とした GPS トラッカーシステム。nRF9151DK を搭載した端末が位置情報と温度情報を取得し、nRF Cloud 経由で AWS に転送、iPhone アプリで保護者に情報を提供する。

---

## 2. システムアーキテクチャ

### 2.1 全体構成図

```
nRF9151DK (GNSS/温度センサー)
    │
    │ MQTT
    ▼
nRF Cloud
    │
    │ Message Routing (Webhook)
    ▼
AWS
├── Lambda (Webhook受信 / API / セーフゾーン判定)
├── DynamoDB (データ保存)
├── API Gateway (REST API)
└── SNS → APNs (プッシュ通知)
    │
    │ REST API / プッシュ通知
    ▼
iPhone アプリ (Swift)
```

### 2.2 データフロー

| データ | フロー |
|---|---|
| GNSS 位置情報 | nRF9151DK → nRF Cloud → (Webhook) → AWS Lambda → DynamoDB → iPhone |
| 温度情報 | nRF9151DK → nRF Cloud → (Webhook) → AWS Lambda → DynamoDB → iPhone |
| セーフゾーンアラート | AWS Lambda (判定) → SNS → APNs → iPhone |
| セーフゾーン設定 | iPhone → API Gateway → Lambda → DynamoDB |
| FOTA | nRF Cloud で管理 |

---

## 3. コンポーネント仕様

### 3.1 デバイス (nRF9151DK)

| 項目 | 仕様 |
|---|---|
| ハードウェア | nRF9151DK |
| SDK | nRF Connect SDK v2.9.2 |
| RTOS | Zephyr |
| クラウドプロトコル | MQTT (nRF Cloud 接続) |
| GNSS サンプリング間隔 | 300秒 (5分) |
| 温度サンプリング間隔 | 60秒 (1分) |
| 測位方式 | GNSS (主) + セルラー測位 (副) |
| 測位補助 | A-GNSS / P-GPS (nRF Cloud 経由) |
| 省電力 | LTE PSM (20秒アクティブタイム) |
| 外部フラッシュ | GD25WB256 (SPI NOR) |
| APN | IIJ Mobile (iijmobile.biz) |

### 3.2 nRF Cloud

| 項目 | 仕様 |
|---|---|
| 接続方式 | Device-to-Cloud (MQTT) |
| 利用サービス | デバイスメッセージ、Message Routing (Webhook)、A-GNSS、P-GPS、FOTA |
| プラン | 試作: Developer (10台無料) |
| 量産プラン | Enterprise (Nordic と個別契約、10万台以上想定) |
| メッセージ保持期間 | 30日 |

### 3.3 AWS

#### 3.3.1 使用サービス一覧

| サービス | 用途 |
|---|---|
| Lambda | nRF Cloud Webhook 受信 / REST API ハンドラ / セーフゾーン判定 |
| API Gateway (REST) | iPhone 向け REST API |
| DynamoDB | 位置履歴・温度履歴・セーフゾーン定義・デバイス状態 |
| SNS | APNs へのプッシュ通知送信 |

#### 3.3.2 nRF Cloud → AWS 連携方式

| 項目 | 仕様 |
|---|---|
| 方式 | nRF Cloud Message Routing (Webhook) |
| データ配信 | nRF Cloud → Lambda Function URL (リアルタイム HTTP POST) |
| 配信カテゴリ | `device_messages`, `location` |
| 認証 | `x-nrfcloud-team-id` レスポンスヘッダーによる自動検証 |
| 重複排除 | DynamoDB 条件付き書き込み (同一 PK+SK はスキップ) |
| AWS側遅延 | 約1〜2秒（ポーリング方式の最大5分から大幅改善） |

#### 3.3.3 DynamoDB テーブル設計 (概要)

**DeviceMessages テーブル**

| キー | 型 | 説明 |
|---|---|---|
| deviceId (PK) | String | デバイス識別子 (例: nrf-352656100123456) |
| timestamp (SK) | String | ISO 8601 タイムスタンプ |
| messageType | String | GNSS / TEMP / ZONE_ENTER / ZONE_EXIT |
| data | Map | メッセージデータ (位置座標、温度値等) |
| zoneId | String | ゾーン識別子 (ZONE_ENTER / ZONE_EXIT のみ) |
| zoneName | String | ゾーン名 (ZONE_ENTER / ZONE_EXIT のみ) |

**SafeZones テーブル**

| キー | 型 | 説明 |
|---|---|---|
| deviceId (PK) | String | デバイス識別子 |
| zoneId (SK) | String | ゾーン識別子 |
| center | Map | 中心座標 (lat, lng) |
| radius | Number | 半径 (メートル) |

**DeviceState テーブル**

| キー | 型 | 説明 |
|---|---|---|
| deviceId (PK) | String | デバイス識別子 |
| lastLocation | Map | 最終位置情報 |
| lastTemperature | Number | 最終温度 |
| inSafeZone | Boolean | セーフゾーン内か否か |
| firmwareVersion | String | 現在の FW バージョン |

#### 3.3.4 REST API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET | /devices | デバイス一覧取得 |
| GET | /devices/{deviceId}/location | 最新位置情報取得 |
| GET | /devices/{deviceId}/temperature | 最新温度情報取得 |
| GET | /devices/{deviceId}/history | 位置・温度・セーフゾーン入退場履歴取得 |
| GET | /devices/{deviceId}/safezones | セーフゾーン一覧取得 |
| PUT | /devices/{deviceId}/safezones | セーフゾーン設定・更新 |
| DELETE | /devices/{deviceId}/safezones/{zoneId} | セーフゾーン削除 |
| GET | /devices/{deviceId}/firmware | FW バージョン取得 |
| POST | /devices/{deviceId}/firmware/update | FOTA トリガー (試作最終フェーズ) |

#### 3.3.5 セーフゾーン判定ロジック

```
1. Lambda が Webhook で新しい位置情報を受信
2. 該当デバイスのセーフゾーン定義を DynamoDB から取得
3. 位置座標とセーフゾーン中心座標の距離を計算
4. 距離 > 半径 の場合、ゾーン外と判定
5. DeviceState の inSafeZone の状態遷移を検出:
   - true → false (ゾーン離脱): DeviceMessages に ZONE_EXIT レコードを書き込み
                                → SNS 経由で APNs プッシュ通知を送信
   - false → true (ゾーン帰還): DeviceMessages に ZONE_ENTER レコードを書き込み
                                → SNS 経由で APNs 帰還通知を送信
6. DeviceState を更新
```

### 3.4 iPhone アプリ

| 項目 | 仕様 |
|---|---|
| 開発環境 | Xcode |
| 言語 | Swift |
| 通信方式 | REST API (API Gateway) + APNs プッシュ通知 |
| 地図表示 | Apple MapKit (予定) |

#### 3.4.1 iPhone アプリ機能

| 機能 | 説明 |
|---|---|
| 地図表示 | デバイスの現在位置を地図上に表示 |
| 温度表示 | デバイスの最新温度を表示 |
| 履歴表示 | 位置・温度の履歴を表示 |
| セーフゾーン設定 | 地図上でセーフゾーンを設定・編集 |
| セーフゾーン通知 | ゾーン離脱時にプッシュ通知を受信 |
| FW バージョン表示 | デバイスの現在のファームウェアバージョンを表示 |
| FOTA トリガー | ファームウェア更新の開始 (試作最終フェーズ) |
| FOTA 結果表示 | 更新の成功/失敗を表示 (試作最終フェーズ) |

---

## 4. FOTA 仕様

| 項目 | 仕様 |
|---|---|
| 管理基盤 | nRF Cloud |
| ブートローダー | MCUboot |
| FW 格納先 | 外部フラッシュ (SPI NOR) |
| FW 配信フロー | GitHub Releases → nRF Cloud → nRF9151DK |
| iPhone 対応 (初期) | FW バージョン表示のみ |
| iPhone 対応 (最終) | FOTA トリガー + 成功/失敗表示 (進捗バーは不要) |

---

## 5. 試作スコープ

### 5.1 試作台数

10台

### 5.2 段階的実装計画

| フェーズ | 実装内容 |
|---|---|
| **初期** | GNSS/温度データの nRF Cloud → AWS → iPhone 表示、FW バージョン表示 |
| **中期** | セーフゾーン設定・判定、プッシュ通知 |
| **最終** | FOTA トリガー (iPhone から)、FOTA 成功/失敗表示 |

---

## 6. 量産方針

| 項目 | 方針 |
|---|---|
| 想定台数 | 10万台以上 |
| nRF Cloud | 継続利用 (Enterprise プラン) |
| アーキテクチャ | 試作時と同一構成を維持 (Message Routing を引き続き使用) |

---

## 7. リポジトリ構成

| # | リポジトリ | 内容 | 言語 |
|---|---|---|---|
| 1 | kid_gps_tracker (仮称) | nRF9151DK ファームウェア | C (Zephyr/NCS) |
| 2 | kid_gps_tracker_cloud → **kid_gps_tracker_backend** | nRF Cloud スクリプト + AWS インフラ (CDK, Lambda) | Python / TypeScript |
| 3 | (iPhone リポジトリ) | iPhone アプリ | Swift |

### 7.1 backend リポジトリ構成 (計画)

```
kid_gps_tracker_backend/
├── nrf_cloud/                  # 既存: nRF Cloud 連携スクリプト
│   ├── nrf_cloud_api.py
│   ├── upload_firmware.py
│   ├── github_fetcher.py
│   ├── location_data_manager.py
│   └── ...
├── aws/                        # 新規: AWS インフラ + Lambda
│   ├── cdk/                    # AWS CDK インフラ定義
│   ├── lambda/
│   │   ├── polling/            # nRF Cloud Webhook 受信 Lambda
│   │   ├── api/                # iPhone 向け REST API Lambda
│   │   └── geofence/           # セーフゾーン判定 Lambda
│   └── ...
├── docs/                       # 仕様書
│   └── specification.md
├── .env.example
└── README.md
```
