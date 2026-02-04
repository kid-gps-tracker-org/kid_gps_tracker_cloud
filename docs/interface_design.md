# nRF Cloud ↔ AWS インターフェース設計書

## 文書情報

| 項目 | 内容 |
|---|---|
| 文書名 | nRF Cloud ↔ AWS インターフェース設計書 |
| バージョン | 1.0 |
| 作成日 | 2026-02-03 |
| 関連文書 | [システム仕様書](specification.md) |

---

## 1. 概要

本文書は、nRF Cloud REST API と AWS 間のインターフェースを定義する。
nRF9151DK デバイスが nRF Cloud に送信した GNSS 位置情報・温度情報を AWS Lambda で定期取得し、
DynamoDB に保存、セーフゾーン判定を行い、iPhone アプリに提供するまでの全データフローを規定する。

### 1.1 対象範囲

```
nRF Cloud REST API ←→ AWS Lambda (ポーリング)
AWS Lambda ←→ DynamoDB
AWS Lambda ←→ SNS ←→ APNs
API Gateway ←→ AWS Lambda ←→ DynamoDB
API Gateway ←→ AWS Lambda ←→ nRF Cloud REST API (FOTA)
```

---

## 2. nRF Cloud REST API インターフェース

### 2.1 認証

| 項目 | 値 |
|---|---|
| 認証方式 | Bearer Token |
| ヘッダー | `Authorization: Bearer {NRF_CLOUD_API_KEY}` |
| API キー管理 | AWS Secrets Manager に保存 |
| ベース URL | `https://api.nrfcloud.com/v1` |

### 2.2 使用するエンドポイント一覧

| # | メソッド | エンドポイント | 用途 | 呼び出し元 |
|---|---|---|---|---|
| 1 | GET | `/v1/messages` | デバイスメッセージ取得 | ポーリング Lambda |
| 2 | GET | `/v1/devices` | デバイス一覧取得 | API Lambda |
| 3 | GET | `/v1/devices/{deviceId}` | デバイス詳細（Shadow含む） | API Lambda |
| 4 | POST | `/v1/fota-jobs` | FOTA ジョブ作成 | API Lambda |
| 5 | GET | `/v1/fota-jobs/{jobId}` | FOTA ジョブステータス取得 | API Lambda |
| 6 | GET | `/v1/firmwares` | ファームウェア一覧取得 | API Lambda |

### 2.3 メッセージ取得 API 詳細

#### リクエスト

```
GET /v1/messages?inclusiveStart={ISO8601}&pageLimit=100
```

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `inclusiveStart` | String (ISO 8601) | Yes | この時刻以降のメッセージを取得 |
| `pageLimit` | Integer | No | 1ページあたりの最大件数 (デフォルト: 100) |
| `pageNextToken` | String | No | ページネーション用トークン |
| `appId` | String | No | フィルタ (GNSS, TEMP 等) |
| `deviceId` | String | No | 特定デバイスのみ取得 |

#### レスポンス

```json
{
  "items": [
    {
      "deviceId": "nrf-352656100123456",
      "receivedAt": "2026-02-03T10:30:00.000Z",
      "message": {
        "appId": "GNSS",
        "ts": 1738577400000,
        "data": {
          "pvt": {
            "lat": 35.6812,
            "lon": 139.7671,
            "acc": 10.5
          }
        }
      }
    },
    {
      "deviceId": "nrf-352656100123456",
      "receivedAt": "2026-02-03T10:30:05.000Z",
      "message": {
        "appId": "TEMP",
        "messageType": "DATA",
        "ts": 1738577405000,
        "data": 23.5
      }
    }
  ],
  "total": 150,
  "pageNextToken": "eyJhbGciOi..."
}
```

#### ページネーション処理

```
最初のリクエスト:
  GET /v1/messages?inclusiveStart={lastPollTimestamp}&pageLimit=100

pageNextToken が返された場合:
  GET /v1/messages?inclusiveStart={lastPollTimestamp}&pageLimit=100&pageNextToken={token}

pageNextToken が null になるまで繰り返す
```

---

## 3. デバイスメッセージ形式

### 3.1 GNSS メッセージ（デバイス → nRF Cloud）

```json
{
  "appId": "GNSS",
  "ts": 1738577400000,
  "data": {
    "pvt": {
      "lat": 35.6812,
      "lon": 139.7671,
      "acc": 10.5
    }
  }
}
```

| フィールド | 型 | 単位 | 説明 |
|---|---|---|---|
| `appId` | String | - | 固定値 `"GNSS"` |
| `ts` | Integer (int64) | ミリ秒 | Unix エポックからのミリ秒 |
| `data.pvt.lat` | Float | 度 | 緯度 (WGS-84) |
| `data.pvt.lon` | Float | 度 | 経度 (WGS-84) |
| `data.pvt.acc` | Float | メートル | 水平精度 (2D 1-sigma) |

**サンプリング間隔:** 300秒 (5分)

### 3.2 温度メッセージ（デバイス → nRF Cloud）

```json
{
  "appId": "TEMP",
  "messageType": "DATA",
  "ts": 1738577405000,
  "data": 23.5
}
```

| フィールド | 型 | 単位 | 説明 |
|---|---|---|---|
| `appId` | String | - | 固定値 `"TEMP"` |
| `messageType` | String | - | 固定値 `"DATA"` |
| `ts` | Integer (int64) | ミリ秒 | Unix エポックからのミリ秒 |
| `data` | Float | ℃ | 温度値 (摂氏) |

**サンプリング間隔:** 60秒 (1分)

### 3.3 アラートメッセージ（デバイス → nRF Cloud）

```json
{
  "appId": "ALERT",
  "ts": 1738577410000,
  "data": {
    "type": "TEMP",
    "value": 31.5,
    "description": "Temperature limit exceeded"
  }
}
```

---

## 4. データ変換仕様

### 4.1 GNSS メッセージ → DynamoDB レコード

```
入力 (nRF Cloud):
{
  "deviceId": "nrf-352656100123456",
  "receivedAt": "2026-02-03T10:30:00.000Z",
  "message": {
    "appId": "GNSS",
    "ts": 1738577400000,
    "data": {"pvt": {"lat": 35.6812, "lon": 139.7671, "acc": 10.5}}
  }
}

↓ 変換 ↓

出力 (DynamoDB DeviceMessages):
{
  "deviceId": "nrf-352656100123456",
  "timestamp": "2026-02-03T10:30:00.000Z",
  "messageType": "GNSS",
  "lat": 35.6812,
  "lon": 139.7671,
  "accuracy": 10.5,
  "deviceTs": 1738577400000,
  "receivedAt": "2026-02-03T10:30:00.000Z",
  "ttl": 1741169400
}

出力 (DynamoDB DeviceState - 同時更新):
{
  "deviceId": "nrf-352656100123456",
  "lastLocation": {
    "lat": 35.6812,
    "lon": 139.7671,
    "accuracy": 10.5,
    "timestamp": "2026-02-03T10:30:00.000Z"
  },
  "updatedAt": "2026-02-03T10:31:00.000Z"
}
```

### 4.2 温度メッセージ → DynamoDB レコード

```
入力 (nRF Cloud):
{
  "deviceId": "nrf-352656100123456",
  "receivedAt": "2026-02-03T10:30:05.000Z",
  "message": {
    "appId": "TEMP",
    "messageType": "DATA",
    "ts": 1738577405000,
    "data": 23.5
  }
}

↓ 変換 ↓

出力 (DynamoDB DeviceMessages):
{
  "deviceId": "nrf-352656100123456",
  "timestamp": "2026-02-03T10:30:05.000Z",
  "messageType": "TEMP",
  "temperature": 23.5,
  "deviceTs": 1738577405000,
  "receivedAt": "2026-02-03T10:30:05.000Z",
  "ttl": 1741169405
}

出力 (DynamoDB DeviceState - 同時更新):
{
  "deviceId": "nrf-352656100123456",
  "lastTemperature": {
    "value": 23.5,
    "timestamp": "2026-02-03T10:30:05.000Z"
  },
  "updatedAt": "2026-02-03T10:31:00.000Z"
}
```

### 4.3 変換ルール

| nRF Cloud フィールド | DynamoDB フィールド | 変換処理 |
|---|---|---|
| `message.ts` | `deviceTs` | そのまま保存 (ミリ秒) |
| `message.ts` | `timestamp` | ISO 8601 文字列に変換 (SK に使用) |
| `receivedAt` | `receivedAt` | そのまま保存 |
| `message.appId` | `messageType` | そのまま保存 |
| `message.data.pvt.lat` | `lat` | そのまま保存 |
| `message.data.pvt.lon` | `lon` | そのまま保存 |
| `message.data.pvt.acc` | `accuracy` | そのまま保存 |
| `message.data` (TEMP) | `temperature` | そのまま保存 |
| (計算値) | `ttl` | `deviceTs/1000 + 30*24*3600` (30日後の Unix 秒) |

---

## 5. DynamoDB テーブル設計

### 5.1 DeviceMessages テーブル

デバイスの位置・温度履歴を保存する。

| 属性 | 型 | キー | 説明 |
|---|---|---|---|
| `deviceId` | String | PK (Partition Key) | デバイス識別子 |
| `timestamp` | String | SK (Sort Key) | ISO 8601 タイムスタンプ |
| `messageType` | String | - | `GNSS` / `TEMP` |
| `lat` | Number | - | 緯度 (GNSS のみ) |
| `lon` | Number | - | 経度 (GNSS のみ) |
| `accuracy` | Number | - | 精度 m (GNSS のみ) |
| `temperature` | Number | - | 温度 ℃ (TEMP のみ) |
| `deviceTs` | Number | - | デバイス側タイムスタンプ (ミリ秒) |
| `receivedAt` | String | - | nRF Cloud 受信時刻 |
| `ttl` | Number | - | TTL (Unix 秒、30日後に自動削除) |

**GSI (Global Secondary Index):**

| GSI 名 | PK | SK | 用途 |
|---|---|---|---|
| `MessageTypeIndex` | `deviceId` | `messageType#timestamp` | 種別ごとの履歴取得 |

**容量見積もり (10台試作時):**
- GNSS: 10台 × 12回/時 × 24時間 = 2,880 レコード/日
- TEMP: 10台 × 60回/時 × 24時間 = 14,400 レコード/日
- 1レコード平均: 約 200 バイト
- 日次合計: 約 3.5 MB/日

### 5.2 DeviceState テーブル

デバイスの最新状態を保存する。

| 属性 | 型 | キー | 説明 |
|---|---|---|---|
| `deviceId` | String | PK | デバイス識別子 |
| `lastLocation` | Map | - | 最新位置 `{lat, lon, accuracy, timestamp}` |
| `lastTemperature` | Map | - | 最新温度 `{value, timestamp}` |
| `inSafeZone` | Boolean | - | セーフゾーン内か否か |
| `safeZoneStatus` | Map | - | ゾーンごとの状態 `{zoneId: boolean}` |
| `firmwareVersion` | String | - | 現在の FW バージョン |
| `lastSeen` | String | - | 最終通信時刻 |
| `updatedAt` | String | - | レコード更新時刻 |

### 5.3 SafeZones テーブル

セーフゾーン定義を保存する。

| 属性 | 型 | キー | 説明 |
|---|---|---|---|
| `deviceId` | String | PK | デバイス識別子 |
| `zoneId` | String | SK | ゾーン識別子 (UUID) |
| `name` | String | - | ゾーン名 (例: "自宅", "学校") |
| `center` | Map | - | 中心座標 `{lat, lon}` |
| `radius` | Number | - | 半径 (メートル) |
| `enabled` | Boolean | - | 有効/無効 |
| `createdAt` | String | - | 作成日時 |
| `updatedAt` | String | - | 更新日時 |

### 5.4 PollingState テーブル

ポーリングの状態管理。

| 属性 | 型 | キー | 説明 |
|---|---|---|---|
| `configKey` | String | PK | 固定値 `"polling"` |
| `lastPollTimestamp` | String | - | 最終取得メッセージの ISO 8601 タイムスタンプ |
| `lastPollExecutedAt` | String | - | 最終ポーリング実行時刻 |
| `messageCount` | Number | - | 累計取得メッセージ数 |

---

## 6. ポーリング Lambda 設計

### 6.1 基本仕様

| 項目 | 値 |
|---|---|
| ランタイム | Python 3.12 |
| トリガー | EventBridge (5分間隔) |
| タイムアウト | 60秒 |
| メモリ | 256 MB |
| 環境変数 | `NRF_CLOUD_API_KEY_SECRET_ARN` (Secrets Manager ARN) |

### 6.2 処理フロー

```
1. EventBridge トリガー (5分間隔)
   │
2. PollingState テーブルから lastPollTimestamp を取得
   │ (初回実行時は現在時刻 - 5分)
   │
3. nRF Cloud REST API 呼び出し
   │ GET /v1/messages?inclusiveStart={lastPollTimestamp}&pageLimit=100
   │ ※ pageNextToken がある限りループ
   │
4. メッセージを appId で分類
   │ ├── GNSS → GNSS 変換処理
   │ ├── TEMP → TEMP 変換処理
   │ └── その他 → ログ出力のみ (将来拡張用)
   │
5. DynamoDB 書き込み (BatchWriteItem)
   │ ├── DeviceMessages テーブルにレコード追加
   │ └── DeviceState テーブルの最新状態を更新
   │
6. GNSS メッセージがある場合 → セーフゾーン判定 (セクション7)
   │
7. PollingState テーブルの lastPollTimestamp を更新
   │ (取得したメッセージの最新 receivedAt + 1ミリ秒)
   │
8. 完了
```

### 6.3 重複排除

| 方式 | 説明 |
|---|---|
| タイムスタンプベース | `lastPollTimestamp` 以降のメッセージのみ取得 |
| DynamoDB 条件付き書き込み | 同一 PK+SK のレコードが存在する場合はスキップ |

### 6.4 メッセージ数の見積もり

| 条件 | 値 |
|---|---|
| デバイス数 | 10台 |
| GNSS 間隔 | 5分 → 5分間に約10メッセージ (全10台合計) |
| TEMP 間隔 | 1分 → 5分間に約50メッセージ (全10台合計) |
| 1回のポーリングで取得 | **約60メッセージ** |
| ページネーション | 不要 (pageLimit=100 で十分) |

---

## 7. セーフゾーン判定

### 7.1 判定フロー

```
1. ポーリングで新しい GNSS メッセージを検出
   │
2. 該当 deviceId の SafeZones を DynamoDB から取得
   │ (enabled=true のゾーンのみ)
   │
3. 各ゾーンについて距離計算
   │ Haversine 公式:
   │   a = sin²(Δlat/2) + cos(lat1) × cos(lat2) × sin²(Δlon/2)
   │   c = 2 × atan2(√a, √(1-a))
   │   distance = R × c  (R = 6,371,000 m)
   │
4. 判定: distance > radius → ゾーン外
   │
5. DeviceState の inSafeZone / safeZoneStatus を取得
   │
6. 状態遷移の検出:
   │ ├── true → false (ゾーン内 → ゾーン外): 離脱アラート送信
   │ ├── false → true (ゾーン外 → ゾーン内): 帰還通知送信
   │ └── 変化なし: 通知なし
   │
7. DeviceState を更新
```

### 7.2 通知メッセージ

**セーフゾーン離脱時:**

```json
{
  "alert": "ZONE_EXIT",
  "deviceId": "nrf-352656100123456",
  "zoneName": "自宅",
  "location": {
    "lat": 35.6900,
    "lon": 139.7600
  },
  "timestamp": "2026-02-03T10:30:00.000Z",
  "message": "デバイスがセーフゾーン「自宅」から離れました"
}
```

**セーフゾーン帰還時:**

```json
{
  "alert": "ZONE_ENTER",
  "deviceId": "nrf-352656100123456",
  "zoneName": "自宅",
  "timestamp": "2026-02-03T11:00:00.000Z",
  "message": "デバイスがセーフゾーン「自宅」に戻りました"
}
```

### 7.3 SNS → APNs 連携

| 項目 | 値 |
|---|---|
| SNS Platform Application | Apple Push Notification service (APNs) |
| SNS Topic | `kid-gps-tracker-alerts` |
| メッセージ形式 | JSON (APNs ペイロード) |

**APNs ペイロード:**

```json
{
  "aps": {
    "alert": {
      "title": "セーフゾーンアラート",
      "body": "デバイスがセーフゾーン「自宅」から離れました"
    },
    "sound": "default",
    "badge": 1
  },
  "data": {
    "type": "ZONE_EXIT",
    "deviceId": "nrf-352656100123456",
    "lat": 35.6900,
    "lon": 139.7600
  }
}
```

---

## 8. iPhone 向け REST API (API Gateway)

### 8.1 共通仕様

| 項目 | 値 |
|---|---|
| プロトコル | HTTPS |
| 認証 | API Key (試作初期) → Cognito (試作最終以降) |
| レスポンス形式 | JSON |
| エラー形式 | `{"error": {"code": "ERROR_CODE", "message": "説明"}}` |

### 8.2 エンドポイント詳細

#### GET /devices

デバイス一覧を取得する。

**レスポンス:**

```json
{
  "devices": [
    {
      "deviceId": "nrf-352656100123456",
      "lastLocation": {
        "lat": 35.6812,
        "lon": 139.7671,
        "accuracy": 10.5,
        "timestamp": "2026-02-03T10:30:00.000Z"
      },
      "lastTemperature": {
        "value": 23.5,
        "timestamp": "2026-02-03T10:30:05.000Z"
      },
      "inSafeZone": true,
      "firmwareVersion": "1.0.0",
      "lastSeen": "2026-02-03T10:30:05.000Z"
    }
  ]
}
```

**データソース:** DeviceState テーブル (Scan)

---

#### GET /devices/{deviceId}/location

指定デバイスの最新位置情報を取得する。

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "location": {
    "lat": 35.6812,
    "lon": 139.7671,
    "accuracy": 10.5,
    "timestamp": "2026-02-03T10:30:00.000Z"
  }
}
```

**データソース:** DeviceState テーブル (GetItem)

---

#### GET /devices/{deviceId}/temperature

指定デバイスの最新温度を取得する。

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "temperature": {
    "value": 23.5,
    "timestamp": "2026-02-03T10:30:05.000Z"
  }
}
```

**データソース:** DeviceState テーブル (GetItem)

---

#### GET /devices/{deviceId}/history

位置・温度の履歴を取得する。

**リクエストパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `type` | String | No | `GNSS` / `TEMP` / 省略で両方 |
| `start` | String | No | 開始時刻 (ISO 8601) |
| `end` | String | No | 終了時刻 (ISO 8601) |
| `limit` | Integer | No | 最大件数 (デフォルト: 100, 最大: 1000) |

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "history": [
    {
      "timestamp": "2026-02-03T10:30:00.000Z",
      "messageType": "GNSS",
      "lat": 35.6812,
      "lon": 139.7671,
      "accuracy": 10.5
    },
    {
      "timestamp": "2026-02-03T10:30:05.000Z",
      "messageType": "TEMP",
      "temperature": 23.5
    }
  ],
  "count": 2
}
```

**データソース:** DeviceMessages テーブル (Query, PK=deviceId, SK between start and end)

---

#### GET /devices/{deviceId}/safezones

セーフゾーン一覧を取得する。

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "safezones": [
    {
      "zoneId": "zone-001",
      "name": "自宅",
      "center": {"lat": 35.6812, "lon": 139.7671},
      "radius": 200,
      "enabled": true,
      "createdAt": "2026-02-01T00:00:00.000Z"
    },
    {
      "zoneId": "zone-002",
      "name": "学校",
      "center": {"lat": 35.6850, "lon": 139.7700},
      "radius": 300,
      "enabled": true,
      "createdAt": "2026-02-01T00:00:00.000Z"
    }
  ]
}
```

**データソース:** SafeZones テーブル (Query, PK=deviceId)

---

#### PUT /devices/{deviceId}/safezones

セーフゾーンを作成・更新する。

**リクエストボディ:**

```json
{
  "name": "自宅",
  "center": {"lat": 35.6812, "lon": 139.7671},
  "radius": 200,
  "enabled": true
}
```

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "zoneId": "zone-001",
  "name": "自宅",
  "center": {"lat": 35.6812, "lon": 139.7671},
  "radius": 200,
  "enabled": true,
  "createdAt": "2026-02-03T12:00:00.000Z"
}
```

**データソース:** SafeZones テーブル (PutItem)

**バリデーション:**

| フィールド | 制約 |
|---|---|
| `name` | 1〜50文字 |
| `center.lat` | -90.0 〜 90.0 |
| `center.lon` | -180.0 〜 180.0 |
| `radius` | 50 〜 10,000 (メートル) |

---

#### DELETE /devices/{deviceId}/safezones/{zoneId}

セーフゾーンを削除する。

**レスポンス:**

```json
{
  "deleted": true,
  "zoneId": "zone-001"
}
```

**データソース:** SafeZones テーブル (DeleteItem)

---

#### GET /devices/{deviceId}/firmware

ファームウェア情報を取得する。

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "firmware": {
    "currentVersion": "1.0.0",
    "lastUpdated": "2026-01-15T00:00:00.000Z"
  }
}
```

**データソース:** DeviceState テーブル (GetItem)

---

#### POST /devices/{deviceId}/firmware/update（試作最終フェーズ）

FOTA ジョブを作成する。

**リクエストボディ:**

```json
{
  "firmwareId": "fw-bundle-id-12345"
}
```

**処理フロー:**

```
1. リクエスト受信
2. nRF Cloud REST API 呼び出し
   POST /v1/fota-jobs
   {
     "firmwareId": "fw-bundle-id-12345",
     "deviceIds": ["nrf-352656100123456"]
   }
3. nRF Cloud からのレスポンスを DeviceState に保存
4. レスポンス返却
```

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "fota": {
    "jobId": "fota-job-67890",
    "status": "QUEUED",
    "firmwareId": "fw-bundle-id-12345",
    "createdAt": "2026-02-03T12:00:00.000Z"
  }
}
```

---

#### GET /devices/{deviceId}/firmware/status（試作最終フェーズ）

FOTA ジョブのステータスを取得する。

**処理フロー:**

```
1. DeviceState から直近の FOTA jobId を取得
2. nRF Cloud REST API 呼び出し
   GET /v1/fota-jobs/{jobId}
3. ステータスを返却
```

**レスポンス:**

```json
{
  "deviceId": "nrf-352656100123456",
  "fota": {
    "jobId": "fota-job-67890",
    "status": "SUCCEEDED",
    "firmwareId": "fw-bundle-id-12345",
    "createdAt": "2026-02-03T12:00:00.000Z",
    "completedAt": "2026-02-03T12:05:00.000Z"
  }
}
```

**FOTA ステータス値:**

| ステータス | 説明 |
|---|---|
| `QUEUED` | ジョブ作成済み、デバイス未受信 |
| `IN_PROGRESS` | デバイスがダウンロード中 |
| `SUCCEEDED` | 更新成功 |
| `FAILED` | 更新失敗 |
| `TIMED_OUT` | タイムアウト |

---

## 9. エラー処理

### 9.1 ポーリング Lambda のエラー処理

| エラー | 対応 |
|---|---|
| nRF Cloud API 接続失敗 | lastPollTimestamp を更新しない → 次回リトライ |
| nRF Cloud API 401 | CloudWatch アラーム → API キー期限切れ通知 |
| nRF Cloud API 429 (レート制限) | 処理中断、次回ポーリングで再取得 |
| DynamoDB 書き込み失敗 | 個別メッセージのリトライ (最大3回) |
| Lambda タイムアウト | lastPollTimestamp を更新しない → 次回再取得 |

### 9.2 API Lambda のエラー処理

| HTTP ステータス | エラーコード | 説明 |
|---|---|---|
| 400 | `INVALID_REQUEST` | リクエストパラメータ不正 |
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 404 | `ZONE_NOT_FOUND` | セーフゾーンが存在しない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |
| 502 | `NRF_CLOUD_ERROR` | nRF Cloud API エラー (FOTA時) |
| 503 | `SERVICE_UNAVAILABLE` | 一時的なサービス停止 |

### 9.3 エラーレスポンス形式

```json
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "Device nrf-352656100123456 not found"
  }
}
```

---

## 10. シーケンス図

### 10.1 定期ポーリングフロー

```
EventBridge          Lambda(Polling)      nRF Cloud API       DynamoDB
    │                     │                    │                  │
    │─── 5分トリガー ──→│                    │                  │
    │                     │                    │                  │
    │                     │── GetItem ────────────────────────→│
    │                     │←── lastPollTimestamp ──────────────│
    │                     │                    │                  │
    │                     │── GET /messages ──→│                  │
    │                     │←── items[] ────────│                  │
    │                     │                    │                  │
    │                     │── (ページネーション繰り返し) ──→│     │
    │                     │←── items[] ────────│                  │
    │                     │                    │                  │
    │                     │── 変換処理          │                  │
    │                     │                    │                  │
    │                     │── BatchWriteItem (DeviceMessages) ─→│
    │                     │── UpdateItem (DeviceState) ────────→│
    │                     │                    │                  │
    │                     │── セーフゾーン判定   │                  │
    │                     │   (GNSS メッセージ時)│                  │
    │                     │                    │                  │
    │                     │── UpdateItem (PollingState) ───────→│
    │                     │                    │                  │
```

### 10.2 セーフゾーンアラートフロー

```
Lambda(Polling)      DynamoDB           SNS              APNs           iPhone
    │                  │                 │                 │               │
    │── Query ────────→│                 │                 │               │
    │   (SafeZones)    │                 │                 │               │
    │←── zones[] ──────│                 │                 │               │
    │                  │                 │                 │               │
    │── GetItem ──────→│                 │                 │               │
    │   (DeviceState)  │                 │                 │               │
    │←── inSafeZone ───│                 │                 │               │
    │                  │                 │                 │               │
    │── 距離計算        │                 │                 │               │
    │── 状態変化検出    │                 │                 │               │
    │                  │                 │                 │               │
    │── Publish ────────────────────────→│                 │               │
    │   (アラート)      │                 │                 │               │
    │                  │                 │── Push ────────→│               │
    │                  │                 │                 │── 通知表示 ──→│
    │                  │                 │                 │               │
    │── UpdateItem ───→│                 │                 │               │
    │   (inSafeZone)   │                 │                 │               │
    │                  │                 │                 │               │
```

### 10.3 iPhone データ取得フロー

```
iPhone              API Gateway        Lambda(API)        DynamoDB
  │                     │                  │                 │
  │── GET /devices ────→│                  │                 │
  │   /{id}/location    │                  │                 │
  │                     │── invoke ───────→│                 │
  │                     │                  │── GetItem ─────→│
  │                     │                  │   (DeviceState)  │
  │                     │                  │←── item ─────────│
  │                     │                  │                 │
  │                     │←── response ─────│                 │
  │←── JSON ────────────│                  │                 │
  │                     │                  │                 │
```

### 10.4 FOTA トリガーフロー（試作最終フェーズ）

```
iPhone              API Gateway        Lambda(API)     nRF Cloud API     DynamoDB
  │                     │                  │                │               │
  │── POST /devices ───→│                  │                │               │
  │   /{id}/firmware    │                  │                │               │
  │   /update           │                  │                │               │
  │                     │── invoke ───────→│                │               │
  │                     │                  │── POST ───────→│               │
  │                     │                  │   /fota-jobs    │               │
  │                     │                  │←── jobId ───────│               │
  │                     │                  │                │               │
  │                     │                  │── UpdateItem ──────────────────→│
  │                     │                  │   (DeviceState.fotaJob)         │
  │                     │                  │                │               │
  │                     │←── response ─────│                │               │
  │←── JSON ────────────│                  │                │               │
  │                     │                  │                │               │
  │                     │                  │                │               │
  │── GET /devices ────→│                  │                │               │
  │   /{id}/firmware    │                  │                │               │
  │   /status           │                  │                │               │
  │                     │── invoke ───────→│                │               │
  │                     │                  │── GET ────────→│               │
  │                     │                  │   /fota-jobs/   │               │
  │                     │                  │   {jobId}       │               │
  │                     │                  │←── status ──────│               │
  │                     │                  │                │               │
  │                     │←── response ─────│                │               │
  │←── JSON ────────────│                  │                │               │
  │                     │                  │                │               │
```

---

## 11. AWS インフラ構成 (CDK)

### 11.1 スタック構成

```
KidGpsTrackerStack
├── Lambda Functions
│   ├── PollingFunction (nRF Cloud ポーリング + セーフゾーン判定)
│   └── ApiFunction (iPhone 向け REST API + FOTA)
├── DynamoDB Tables
│   ├── DeviceMessages (TTL 有効)
│   ├── DeviceState
│   ├── SafeZones
│   └── PollingState
├── API Gateway (REST API)
│   └── /devices/* ルート
├── EventBridge Rule (5分間隔)
├── SNS Topic (kid-gps-tracker-alerts)
├── SNS Platform Application (APNs)
└── Secrets Manager (nRF Cloud API Key)
```

### 11.2 Lambda 共通設定

| 項目 | PollingFunction | ApiFunction |
|---|---|---|
| ランタイム | Python 3.12 | Python 3.12 |
| メモリ | 256 MB | 128 MB |
| タイムアウト | 60秒 | 30秒 |
| 同時実行数 | 1 (予約) | 10 |

---

## 12. 量産時の考慮事項

| 項目 | 試作 (10台) | 量産 (10万台) |
|---|---|---|
| ポーリング方式 | 5分ごとに全メッセージ一括取得 | デバイスグループ分割 or Message Routing に移行 |
| DynamoDB | オンデマンドモード | プロビジョニングモード + Auto Scaling |
| API Gateway | API Key 認証 | Cognito User Pool |
| Lambda | 単一関数 | 機能ごとに分割 |
| SNS/APNs | 直接 Publish | SQS バッファリング |
