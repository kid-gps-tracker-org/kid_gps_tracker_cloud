# iPhone ↔ AWS REST API 仕様書

## 文書情報

| 項目 | 内容 |
|---|---|
| 文書名 | iPhone ↔ AWS REST API 仕様書 |
| バージョン | 1.2 |
| 作成日 | 2026-02-05 |
| 更新日 | 2026-02-12 |
| 関連文書 | [システム仕様書](specification.md), [インターフェース設計書](interface_design.md) |

**変更履歴:**

| バージョン | 日付 | 変更内容 |
|---|---|---|
| 1.0 | 2026-02-05 | 初版作成 |
| 1.1 | 2026-02-12 | GNSS/GROUND_FIX の表示ルールを追加。セーフゾーン判定は GNSS のみ使用する旨を明記。 |
| 1.2 | 2026-02-12 | GNSS データが 10 分以上古い場合に GROUND_FIX へフォールバックする仕様を追加。 |

### 本文書の目的

本文書は AWS バックエンド (Python Lambda) と iPhone アプリ (Swift) の間の REST API インターフェースを**厳密に定義**する。
AWS 側と iPhone 側を別々の開発環境で実装する際に、本文書のみを参照すればソースコードの不整合が発生しないことを目的とする。

**AWS 側の実装者へ**: 本文書のレスポンス形式をそのまま返却すること。フィールド名・型・null ルールを厳守すること。
**iPhone 側の実装者へ**: 本文書のレスポンス形式に基づいてデータモデル (Codable struct) を定義すること。

---

## 1. 共通規約

### 1.1 命名規則

| 対象 | 規則 | 例 |
|---|---|---|
| JSON キー | camelCase | `deviceId`, `lastLocation`, `messageType` |
| エンドポイントパス | 小文字 + ハイフン | `/devices/{deviceId}/safezones` |
| エラーコード | SCREAMING_SNAKE_CASE | `DEVICE_NOT_FOUND` |
| 列挙値 | SCREAMING_SNAKE_CASE | `GNSS`, `GROUND_FIX`, `TEMP` |

### 1.2 タイムスタンプ形式

**全 API で統一**: ISO 8601 / UTC / ミリ秒精度

```
2026-02-05T12:34:56.789Z
```

- タイムゾーン: 常に UTC (`Z` サフィックス)
- 精度: ミリ秒 (3桁)
- リクエストで送信する場合も同じ形式

### 1.3 null ハンドリング

| 方向 | ルール |
|---|---|
| レスポンス (AWS → iPhone) | 値が存在しないフィールドは `null` を返す。**キー自体を省略しない。** |
| リクエスト (iPhone → AWS) | 任意フィールドはキーごと省略可能。 |

### 1.4 座標系

| 項目 | 値 |
|---|---|
| 測地系 | WGS 84 (EPSG:4326) |
| 緯度 (lat) | Number: -90.0 〜 90.0 |
| 経度 (lon) | Number: -180.0 〜 180.0 |
| フィールド名 | `lat` / `lon` (すべてのエンドポイントで統一) |

### 1.5 Content-Type

```
Content-Type: application/json; charset=utf-8
```

リクエスト・レスポンスともに上記を使用する。`204 No Content` のレスポンスのみボディなし。

---

## 2. ベース URL・認証

### 2.1 ベース URL

```
https://{api-id}.execute-api.ap-northeast-1.amazonaws.com/{stage}
```

| 環境 | stage |
|---|---|
| 開発 | `dev` |
| 本番 | `prod` |

### 2.2 認証（試作フェーズ）

| 項目 | 値 |
|---|---|
| 方式 | API Key |
| ヘッダー名 | `x-api-key` |
| 値 | API Gateway で発行された文字列 |

**リクエスト例:**

```
GET /devices HTTP/1.1
Host: {api-id}.execute-api.ap-northeast-1.amazonaws.com
x-api-key: abcdef1234567890
```

**認証エラーレスポンス:**

| 状況 | HTTP ステータス | エラーコード |
|---|---|---|
| ヘッダーなし | 403 | `MISSING_API_KEY` |
| 無効なキー | 403 | `INVALID_API_KEY` |

```json
{
  "error": {
    "code": "MISSING_API_KEY",
    "message": "x-api-key header is required"
  }
}
```

---

## 3. 共有データ型

**全エンドポイントで使用するデータ型をここで一度だけ定義する。**
各エンドポイントの仕様 (セクション4) からは型名で参照する。

### 3.1 Location 型

デバイスの位置情報。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `lat` | Number | Yes | 緯度 (-90.0 〜 90.0) |
| `lon` | Number | Yes | 経度 (-180.0 〜 180.0) |
| `accuracy` | Number | Yes | 精度 (メートル、>= 0) |
| `source` | String | Yes | 測位方式。値: `"GNSS"` / `"GROUND_FIX"` |
| `timestamp` | String | Yes | 測位時刻 (ISO 8601) |

```json
{
  "lat": 35.681236,
  "lon": 139.767125,
  "accuracy": 10.5,
  "source": "GNSS",
  "timestamp": "2026-02-05T12:30:00.000Z"
}
```

**source の値と iPhone 表示ルール:**

| 値 | 説明 | iPhone 表示 |
|---|---|---|
| `GNSS` | GPS/GNSS 衛星測位。精度 5〜15m。 | デバイスアイコン（ピン）を表示する。軌跡に追加する。 |
| `GROUND_FIX` | セルラー基地局測位 (屋内等で GNSS 不可時)。誤差 100〜数百m。 | デバイスアイコンを**表示しない**。`accuracy` の値 (m) を半径とした在圏可能性円を表示する。軌跡には**追加しない**。 |

> **Note (フォールバック仕様)**: AWS は GNSS データが**最終取得から 10 分以上経過**している場合、代わりに最新の `GROUND_FIX` データを返す。これにより、デバイスが屋内に入って GNSS が取得できない状況でも約 5 分間隔でセルラー測位の位置情報が iPhone に届く。GNSS が再取得されると自動的に GNSS データに戻る。

### 3.2 Temperature 型

デバイスの温度情報。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `value` | Number | Yes | 温度 (℃、小数点以下1桁) |
| `timestamp` | String | Yes | 計測時刻 (ISO 8601) |

```json
{
  "value": 23.5,
  "timestamp": "2026-02-05T12:30:05.000Z"
}
```

### 3.3 Coordinate 型

座標 (緯度・経度のみ)。セーフゾーンの中心座標等に使用。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `lat` | Number | Yes | 緯度 (-90.0 〜 90.0) |
| `lon` | Number | Yes | 経度 (-180.0 〜 180.0) |

```json
{
  "lat": 35.681236,
  "lon": 139.767125
}
```

### 3.4 SafeZone 型

セーフゾーン定義。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `zoneId` | String | Yes | ゾーン識別子 (UUID) |
| `name` | String | Yes | ゾーン名 (1〜50文字) |
| `center` | Coordinate | Yes | 中心座標 |
| `radius` | Number | Yes | 半径 (メートル、整数、50〜10000) |
| `enabled` | Boolean | Yes | 有効/無効 |
| `createdAt` | String | Yes | 作成日時 (ISO 8601) |
| `updatedAt` | String | Yes | 更新日時 (ISO 8601) |

```json
{
  "zoneId": "550e8400-e29b-41d4-a716-446655440000",
  "name": "自宅",
  "center": {"lat": 35.681236, "lon": 139.767125},
  "radius": 200,
  "enabled": true,
  "createdAt": "2026-02-01T00:00:00.000Z",
  "updatedAt": "2026-02-01T00:00:00.000Z"
}
```

### 3.5 Device 型

デバイスの最新状態。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `deviceId` | String | Yes | デバイス識別子 (形式: `nrf-{IMEI 15桁}`) |
| `lastLocation` | Location \| null | Yes | 最新位置情報。データなしの場合 `null` |
| `lastTemperature` | Temperature \| null | Yes | 最新温度情報。データなしの場合 `null` |
| `inSafeZone` | Boolean | Yes | いずれかのセーフゾーン内にいるか |
| `firmwareVersion` | String \| null | Yes | 現在の FW バージョン (例: `"1.0.0"`)。不明時 `null` |
| `lastSeen` | String \| null | Yes | 最終通信時刻 (ISO 8601)。未通信時 `null` |

```json
{
  "deviceId": "nrf-352656100123456",
  "lastLocation": {
    "lat": 35.681236,
    "lon": 139.767125,
    "accuracy": 10.5,
    "source": "GNSS",
    "timestamp": "2026-02-05T12:30:00.000Z"
  },
  "lastTemperature": {
    "value": 23.5,
    "timestamp": "2026-02-05T12:30:05.000Z"
  },
  "inSafeZone": true,
  "firmwareVersion": "1.0.0",
  "lastSeen": "2026-02-05T12:30:05.000Z"
}
```

### 3.6 HistoryEntry 型

位置・温度・セーフゾーン入退場の履歴1件。`messageType` によって含まれるフィールドが異なる。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `timestamp` | String | Yes | 計測/検出時刻 (ISO 8601) |
| `messageType` | String | Yes | `"GNSS"` / `"GROUND_FIX"` / `"TEMP"` / `"ZONE_ENTER"` / `"ZONE_EXIT"` |
| `lat` | Number \| null | Yes | 緯度。TEMP の場合 `null` |
| `lon` | Number \| null | Yes | 経度。TEMP の場合 `null` |
| `accuracy` | Number \| null | Yes | 精度 (m)。TEMP の場合 `null` |
| `temperature` | Number \| null | Yes | 温度 (℃)。位置系・ゾーン系の場合 `null` |
| `zoneId` | String \| null | Yes | ゾーン識別子。ZONE_ENTER / ZONE_EXIT の場合のみ値あり。それ以外は `null` |
| `zoneName` | String \| null | Yes | ゾーン名。ZONE_ENTER / ZONE_EXIT の場合のみ値あり。それ以外は `null` |

**messageType の値:**

| 値 | 説明 | iPhone 表示 |
|---|---|---|
| `GNSS` | GPS/GNSS 衛星測位による位置データ | ピンを表示、軌跡に追加 |
| `GROUND_FIX` | セルラー基地局測位による位置データ (屋内等で GNSS 不可時) | ピン非表示、`accuracy` 半径の在圏可能性円を表示、軌跡に追加しない |
| `TEMP` | 温度データ | — |
| `ZONE_ENTER` | セーフゾーンへの入場イベント (GNSS 判定のみ) | 入場通知 |
| `ZONE_EXIT` | セーフゾーンからの退場イベント (GNSS 判定のみ) | 退場通知 |

**位置系 (GNSS / GROUND_FIX) の例:**

```json
{
  "timestamp": "2026-02-05T12:30:00.000Z",
  "messageType": "GNSS",
  "lat": 35.681236,
  "lon": 139.767125,
  "accuracy": 10.5,
  "temperature": null,
  "zoneId": null,
  "zoneName": null
}
```

**温度 (TEMP) の例:**

```json
{
  "timestamp": "2026-02-05T12:30:05.000Z",
  "messageType": "TEMP",
  "lat": null,
  "lon": null,
  "accuracy": null,
  "temperature": 23.5,
  "zoneId": null,
  "zoneName": null
}
```

**セーフゾーン退場 (ZONE_EXIT) の例:**

```json
{
  "timestamp": "2026-02-05T12:35:00.000Z",
  "messageType": "ZONE_EXIT",
  "lat": 35.690000,
  "lon": 139.760000,
  "accuracy": 15.0,
  "temperature": null,
  "zoneId": "550e8400-e29b-41d4-a716-446655440000",
  "zoneName": "自宅"
}
```

**セーフゾーン入場 (ZONE_ENTER) の例:**

```json
{
  "timestamp": "2026-02-05T13:00:00.000Z",
  "messageType": "ZONE_ENTER",
  "lat": 35.681236,
  "lon": 139.767125,
  "accuracy": 8.0,
  "temperature": null,
  "zoneId": "550e8400-e29b-41d4-a716-446655440000",
  "zoneName": "自宅"
}
```

### 3.7 FirmwareInfo 型

ファームウェア情報。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `currentVersion` | String | Yes | 現在の FW バージョン (例: `"1.0.0"`) |
| `lastUpdated` | String \| null | Yes | 最終更新日時 (ISO 8601)。更新歴なし時 `null` |

```json
{
  "currentVersion": "1.0.0",
  "lastUpdated": "2026-01-15T00:00:00.000Z"
}
```

### 3.8 FotaJob 型

FOTA ジョブの状態。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `jobId` | String | Yes | nRF Cloud FOTA ジョブ ID |
| `status` | String | Yes | ジョブステータス (下記参照) |
| `firmwareId` | String | Yes | ファームウェアバンドル ID |
| `createdAt` | String | Yes | ジョブ作成日時 (ISO 8601) |
| `completedAt` | String \| null | Yes | 完了日時。未完了時 `null` |

**status の値:**

| 値 | 説明 |
|---|---|
| `QUEUED` | ジョブ作成済み、デバイス未受信 |
| `IN_PROGRESS` | デバイスがダウンロード中 |
| `SUCCEEDED` | 更新成功 |
| `FAILED` | 更新失敗 |
| `TIMED_OUT` | タイムアウト |

```json
{
  "jobId": "fota-job-67890",
  "status": "SUCCEEDED",
  "firmwareId": "fw-bundle-id-12345",
  "createdAt": "2026-02-03T12:00:00.000Z",
  "completedAt": "2026-02-03T12:05:00.000Z"
}
```

### 3.9 ApiError 型

全エラーレスポンスの共通形式。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `error.code` | String | Yes | 機械可読エラーコード (SCREAMING_SNAKE_CASE) |
| `error.message` | String | Yes | 人間可読エラーメッセージ |

```json
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "Device nrf-352656100123456 not found"
  }
}
```

---

## 4. エンドポイント仕様

### 4.1 GET /devices

デバイス一覧と各デバイスの最新状態を取得する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices` |
| ヘッダー | `x-api-key` (必須) |
| クエリパラメータ | なし |
| ボディ | なし |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "devices": [
    {
      "deviceId": "nrf-352656100123456",
      "lastLocation": {
        "lat": 35.681236,
        "lon": 139.767125,
        "accuracy": 10.5,
        "source": "GNSS",
        "timestamp": "2026-02-05T12:30:00.000Z"
      },
      "lastTemperature": {
        "value": 23.5,
        "timestamp": "2026-02-05T12:30:05.000Z"
      },
      "inSafeZone": true,
      "firmwareVersion": "1.0.0",
      "lastSeen": "2026-02-05T12:30:05.000Z"
    }
  ]
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `devices` | Device[] | Device 型 (3.5) の配列。デバイスがない場合は空配列 `[]` |

**エラーレスポンス:**

| HTTP ステータス | エラーコード |
|---|---|
| 403 | `MISSING_API_KEY` / `INVALID_API_KEY` |
| 500 | `INTERNAL_ERROR` |

---

### 4.2 GET /devices/{deviceId}/location

指定デバイスの最新位置情報を取得する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices/{deviceId}/location` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "deviceId": "nrf-352656100123456",
  "location": {
    "lat": 35.681236,
    "lon": 139.767125,
    "accuracy": 10.5,
    "source": "GNSS",
    "timestamp": "2026-02-05T12:30:00.000Z"
  }
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `location` | Location | Location 型 (3.1) |

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 404 | `NO_LOCATION_DATA` | デバイスは存在するが位置データがない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.3 GET /devices/{deviceId}/temperature

指定デバイスの最新温度情報を取得する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices/{deviceId}/temperature` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "deviceId": "nrf-352656100123456",
  "temperature": {
    "value": 23.5,
    "timestamp": "2026-02-05T12:30:05.000Z"
  }
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `temperature` | Temperature | Temperature 型 (3.2) |

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 404 | `NO_TEMPERATURE_DATA` | デバイスは存在するが温度データがない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.4 GET /devices/{deviceId}/history

位置・温度・セーフゾーン入退場の履歴を取得する。

> **Note**: セーフゾーン入退場イベント (ZONE_ENTER / ZONE_EXIT) は **GNSS 測位のみ**を使用して判定される。GROUND_FIX（セルラー測位）は誤差が大きいため判定対象外。GROUND_FIX の位置データ自体は履歴に含まれる。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices/{deviceId}/history` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |

**クエリパラメータ:**

| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `type` | String | No | なし (全種別) | `GNSS` / `GROUND_FIX` / `TEMP` / `ZONE_ENTER` / `ZONE_EXIT`。省略時は全種別を返す |
| `start` | String | No | 24時間前 | 開始時刻 (ISO 8601) |
| `end` | String | No | 現在時刻 | 終了時刻 (ISO 8601) |
| `limit` | Integer | No | 100 | 最大件数 (1〜1000) |

**バリデーション:**

- `start` は `end` より前であること
- `start` は過去30日以内であること
- `type` は `GNSS` / `GROUND_FIX` / `TEMP` / `ZONE_ENTER` / `ZONE_EXIT` のいずれかであること
- `limit` は 1〜1000 の整数であること

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "deviceId": "nrf-352656100123456",
  "history": [
    {
      "timestamp": "2026-02-05T12:30:00.000Z",
      "messageType": "GNSS",
      "lat": 35.681236,
      "lon": 139.767125,
      "accuracy": 10.5,
      "temperature": null
    },
    {
      "timestamp": "2026-02-05T12:30:05.000Z",
      "messageType": "TEMP",
      "lat": null,
      "lon": null,
      "accuracy": null,
      "temperature": 23.5
    }
  ],
  "count": 2
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `history` | HistoryEntry[] | HistoryEntry 型 (3.6) の配列。timestamp 降順 (新しい順) |
| `count` | Integer | 返却件数 |

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 400 | `INVALID_PARAMETER` | type/limit の値が不正 |
| 400 | `INVALID_TIME_RANGE` | start >= end |
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.5 GET /devices/{deviceId}/safezones

指定デバイスのセーフゾーン一覧を取得する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices/{deviceId}/safezones` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "deviceId": "nrf-352656100123456",
  "safezones": [
    {
      "zoneId": "550e8400-e29b-41d4-a716-446655440000",
      "name": "自宅",
      "center": {"lat": 35.681236, "lon": 139.767125},
      "radius": 200,
      "enabled": true,
      "createdAt": "2026-02-01T00:00:00.000Z",
      "updatedAt": "2026-02-01T00:00:00.000Z"
    },
    {
      "zoneId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "name": "学校",
      "center": {"lat": 35.685000, "lon": 139.770000},
      "radius": 300,
      "enabled": true,
      "createdAt": "2026-02-01T00:00:00.000Z",
      "updatedAt": "2026-02-01T00:00:00.000Z"
    }
  ]
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `safezones` | SafeZone[] | SafeZone 型 (3.4) の配列。ゾーンがない場合は空配列 `[]` |

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.6 PUT /devices/{deviceId}/safezones

セーフゾーンを作成または更新する。

- `zoneId` を省略 → 新規作成 (サーバーが UUID を生成)
- `zoneId` を指定 → 既存ゾーンの更新

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | PUT |
| パス | `/devices/{deviceId}/safezones` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須), `Content-Type: application/json` |

**リクエストボディ:**

| フィールド | 型 | 新規作成時 | 更新時 | バリデーション |
|---|---|---|---|---|
| `zoneId` | String | 省略 | 必須 | UUID 形式 |
| `name` | String | 必須 | 任意 | 1〜50文字 |
| `center` | Coordinate | 必須 | 任意 | 有効な lat/lon |
| `radius` | Number | 必須 | 任意 | 整数、50〜10000 |
| `enabled` | Boolean | 任意 (デフォルト: true) | 任意 | - |

**新規作成リクエスト例:**

```json
{
  "name": "自宅",
  "center": {"lat": 35.681236, "lon": 139.767125},
  "radius": 200,
  "enabled": true
}
```

**更新リクエスト例:**

```json
{
  "zoneId": "550e8400-e29b-41d4-a716-446655440000",
  "radius": 300
}
```

**成功レスポンス (新規作成):**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 201 Created |

```json
{
  "deviceId": "nrf-352656100123456",
  "safezone": {
    "zoneId": "550e8400-e29b-41d4-a716-446655440000",
    "name": "自宅",
    "center": {"lat": 35.681236, "lon": 139.767125},
    "radius": 200,
    "enabled": true,
    "createdAt": "2026-02-05T12:00:00.000Z",
    "updatedAt": "2026-02-05T12:00:00.000Z"
  }
}
```

**成功レスポンス (更新):**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

レスポンス形式は新規作成と同一 (`updatedAt` が更新される)。

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 400 | `INVALID_REQUEST` | JSON パースエラー |
| 400 | `MISSING_REQUIRED_FIELD` | 新規作成時の必須フィールド不足 |
| 400 | `INVALID_COORDINATE` | lat/lon が範囲外 |
| 400 | `INVALID_RADIUS` | radius が 50〜10000 の範囲外 |
| 400 | `INVALID_ZONE_NAME` | name が空文字 or 50文字超 |
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 404 | `ZONE_NOT_FOUND` | 更新時に指定 zoneId が存在しない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.7 DELETE /devices/{deviceId}/safezones/{zoneId}

指定セーフゾーンを削除する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | DELETE |
| パス | `/devices/{deviceId}/safezones/{zoneId}` |
| パスパラメータ | `deviceId` (String, 必須), `zoneId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |
| ボディ | なし |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "deleted": true,
  "zoneId": "550e8400-e29b-41d4-a716-446655440000"
}
```

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 404 | `ZONE_NOT_FOUND` | 指定 zoneId が存在しない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.8 GET /devices/{deviceId}/firmware

ファームウェア情報を取得する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices/{deviceId}/firmware` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

```json
{
  "deviceId": "nrf-352656100123456",
  "firmware": {
    "currentVersion": "1.0.0",
    "lastUpdated": "2026-01-15T00:00:00.000Z"
  }
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `firmware` | FirmwareInfo | FirmwareInfo 型 (3.7) |

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.9 POST /devices/{deviceId}/firmware/update

FOTA ジョブを作成し、ファームウェア更新を開始する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | POST |
| パス | `/devices/{deviceId}/firmware/update` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須), `Content-Type: application/json` |

**リクエストボディ:**

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `firmwareId` | String | Yes | nRF Cloud のファームウェアバンドル ID |

```json
{
  "firmwareId": "fw-bundle-id-12345"
}
```

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 201 Created |

```json
{
  "deviceId": "nrf-352656100123456",
  "fota": {
    "jobId": "fota-job-67890",
    "status": "QUEUED",
    "firmwareId": "fw-bundle-id-12345",
    "createdAt": "2026-02-05T12:00:00.000Z",
    "completedAt": null
  }
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `fota` | FotaJob | FotaJob 型 (3.8) |

**AWS 側の処理フロー:**

```
1. リクエスト受信・バリデーション
2. nRF Cloud REST API 呼び出し: POST /v1/fota-jobs
   {"firmwareId": "...", "deviceIds": ["nrf-..."]}
3. nRF Cloud のレスポンスから jobId を取得
4. DeviceState テーブルに FOTA ジョブ情報を保存
5. レスポンス返却
```

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 400 | `INVALID_REQUEST` | JSON パースエラー or firmwareId 欠落 |
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 502 | `NRF_CLOUD_ERROR` | nRF Cloud API 呼び出し失敗 |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

### 4.10 GET /devices/{deviceId}/firmware/status

直近の FOTA ジョブのステータスを取得する。

**リクエスト:**

| 項目 | 値 |
|---|---|
| メソッド | GET |
| パス | `/devices/{deviceId}/firmware/status` |
| パスパラメータ | `deviceId` (String, 必須) |
| ヘッダー | `x-api-key` (必須) |

**成功レスポンス:**

| 項目 | 値 |
|---|---|
| HTTP ステータス | 200 OK |

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

| フィールド | 型 | 説明 |
|---|---|---|
| `deviceId` | String | デバイス識別子 |
| `fota` | FotaJob | FotaJob 型 (3.8) |

**AWS 側の処理フロー:**

```
1. DeviceState テーブルから直近の FOTA jobId を取得
2. nRF Cloud REST API 呼び出し: GET /v1/fota-jobs/{jobId}
3. ステータスを変換して返却
```

**エラーレスポンス:**

| HTTP ステータス | エラーコード | 条件 |
|---|---|---|
| 404 | `DEVICE_NOT_FOUND` | デバイスが存在しない |
| 404 | `NO_FOTA_JOB` | FOTA ジョブが存在しない |
| 502 | `NRF_CLOUD_ERROR` | nRF Cloud API 呼び出し失敗 |
| 500 | `INTERNAL_ERROR` | サーバー内部エラー |

---

## 5. エラーコード一覧

全エンドポイント横断のエラーコード完全リスト。

| HTTP ステータス | エラーコード | メッセージ | 使用箇所 |
|---|---|---|---|
| 400 | `INVALID_REQUEST` | Request body is not valid JSON | PUT/POST 全般 |
| 400 | `MISSING_REQUIRED_FIELD` | Required field '{field}' is missing | 4.6 safezone 作成 |
| 400 | `INVALID_PARAMETER` | Parameter '{param}' is invalid | 4.4 history |
| 400 | `INVALID_TIME_RANGE` | Start time must be before end time | 4.4 history |
| 400 | `INVALID_COORDINATE` | Latitude must be -90 to 90, longitude -180 to 180 | 4.6 safezone |
| 400 | `INVALID_RADIUS` | Radius must be between 50 and 10000 meters | 4.6 safezone |
| 400 | `INVALID_ZONE_NAME` | Zone name must be 1 to 50 characters | 4.6 safezone |
| 403 | `MISSING_API_KEY` | x-api-key header is required | 全エンドポイント |
| 403 | `INVALID_API_KEY` | The provided API key is not valid | 全エンドポイント |
| 404 | `DEVICE_NOT_FOUND` | Device '{deviceId}' not found | デバイス指定の全エンドポイント |
| 404 | `ZONE_NOT_FOUND` | Safe zone '{zoneId}' not found | 4.6 更新, 4.7 削除 |
| 404 | `NO_LOCATION_DATA` | No location data available for device | 4.2 location |
| 404 | `NO_TEMPERATURE_DATA` | No temperature data available for device | 4.3 temperature |
| 404 | `NO_FOTA_JOB` | No FOTA job found for device | 4.10 firmware/status |
| 500 | `INTERNAL_ERROR` | An internal error occurred | 全エンドポイント |
| 502 | `NRF_CLOUD_ERROR` | nRF Cloud API error | 4.9, 4.10 FOTA |

**エラーレスポンスの形式** (常に同一構造):

```json
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "Device 'nrf-352656100123456' not found"
  }
}
```

---

## 6. プッシュ通知ペイロード

セーフゾーンの出入りを検出した場合、AWS Lambda が SNS → APNs 経由で iPhone にプッシュ通知を送信する。

> **Note**: プッシュ通知は **GNSS 測位**によるセーフゾーン判定でのみ発生する。GROUND_FIX（セルラー測位）は誤差が大きいため判定対象外であり、GROUND_FIX による位置更新ではプッシュ通知は送信されない。

### 6.1 セーフゾーン離脱通知 (ZONE_EXIT)

**トリガー**: GNSS 測位でデバイスの位置がセーフゾーン内 → ゾーン外に変化した場合。

**APNs ペイロード** (iPhone アプリが受信する JSON):

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
    "zoneId": "550e8400-e29b-41d4-a716-446655440000",
    "zoneName": "自宅",
    "location": {
      "lat": 35.690000,
      "lon": 139.760000,
      "accuracy": 15.0,
      "source": "GNSS",
      "timestamp": "2026-02-05T12:30:00.000Z"
    },
    "detectedAt": "2026-02-05T12:30:05.000Z"
  }
}
```

### 6.2 セーフゾーン帰還通知 (ZONE_ENTER)

**トリガー**: GNSS 測位でデバイスの位置がセーフゾーン外 → ゾーン内に変化した場合。

**APNs ペイロード:**

```json
{
  "aps": {
    "alert": {
      "title": "セーフゾーン通知",
      "body": "デバイスがセーフゾーン「自宅」に戻りました"
    },
    "sound": "default"
  },
  "data": {
    "type": "ZONE_ENTER",
    "deviceId": "nrf-352656100123456",
    "zoneId": "550e8400-e29b-41d4-a716-446655440000",
    "zoneName": "自宅",
    "location": {
      "lat": 35.681236,
      "lon": 139.767125,
      "accuracy": 8.0,
      "source": "GNSS",
      "timestamp": "2026-02-05T13:00:00.000Z"
    },
    "detectedAt": "2026-02-05T13:00:05.000Z"
  }
}
```

### 6.3 プッシュ通知データ型

`data` フィールドの定義:

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `type` | String | Yes | `"ZONE_EXIT"` / `"ZONE_ENTER"` |
| `deviceId` | String | Yes | デバイス識別子 |
| `zoneId` | String | Yes | セーフゾーン識別子 |
| `zoneName` | String | Yes | セーフゾーン名 |
| `location` | Location | Yes | 検出時のデバイス位置 (Location 型 3.1) |
| `detectedAt` | String | Yes | AWS 側での検出時刻 (ISO 8601) |

---

## 7. バリデーションルール一覧

全エンドポイント横断のバリデーション規則。

| 対象 | パラメータ | ルール | エラーコード |
|---|---|---|---|
| 全エンドポイント | `x-api-key` ヘッダー | 必須、非空文字列 | `MISSING_API_KEY` |
| デバイス指定の全エンドポイント | `deviceId` パスパラメータ | `nrf-` + 数字15桁 | `DEVICE_NOT_FOUND` |
| 4.4 history | `type` クエリ | `GNSS` / `GROUND_FIX` / `TEMP` / `ZONE_ENTER` / `ZONE_EXIT` のいずれか | `INVALID_PARAMETER` |
| 4.4 history | `start` クエリ | 有効な ISO 8601、過去30日以内 | `INVALID_PARAMETER` |
| 4.4 history | `end` クエリ | 有効な ISO 8601 | `INVALID_PARAMETER` |
| 4.4 history | `limit` クエリ | 整数 1〜1000 | `INVALID_PARAMETER` |
| 4.4 history | `start` vs `end` | start < end | `INVALID_TIME_RANGE` |
| 4.6 safezone 作成 | `name` | 必須、1〜50文字 | `MISSING_REQUIRED_FIELD` / `INVALID_ZONE_NAME` |
| 4.6 safezone 作成 | `center.lat` | 必須、-90.0 〜 90.0 | `INVALID_COORDINATE` |
| 4.6 safezone 作成 | `center.lon` | 必須、-180.0 〜 180.0 | `INVALID_COORDINATE` |
| 4.6 safezone 作成 | `radius` | 必須、整数 50〜10000 | `INVALID_RADIUS` |
| 4.9 firmware/update | `firmwareId` | 必須、非空文字列 | `INVALID_REQUEST` |

---

## 8. 実装マッピング

### 8.1 API フィールド ↔ DynamoDB 属性の対応

**DeviceState テーブル → Device 型 (GET /devices):**

| API フィールド | DynamoDB 属性 | 変換 |
|---|---|---|
| `deviceId` | `deviceId` (PK) | そのまま |
| `lastLocation.lat` | `lastLocation.lat` | Decimal → Number |
| `lastLocation.lon` | `lastLocation.lon` | Decimal → Number |
| `lastLocation.accuracy` | `lastLocation.accuracy` | Decimal → Number |
| `lastLocation.source` | `lastLocation.source` | そのまま (`GNSS` / `GROUND_FIX`) |
| `lastLocation.timestamp` | `lastLocation.timestamp` | そのまま |
| `lastTemperature.value` | `lastTemperature.value` | Decimal → Number |
| `lastTemperature.timestamp` | `lastTemperature.timestamp` | そのまま |
| `inSafeZone` | `inSafeZone` | そのまま |
| `firmwareVersion` | `firmwareVersion` | そのまま |
| `lastSeen` | `lastSeen` | そのまま |

**DeviceMessages テーブル → HistoryEntry 型 (GET /history):**

| API フィールド | DynamoDB 属性 | 変換 |
|---|---|---|
| `timestamp` | `timestamp` (SK) | そのまま |
| `messageType` | `messageType` | そのまま (`GNSS` / `GROUND_FIX` / `TEMP` / `ZONE_ENTER` / `ZONE_EXIT`) |
| `lat` | `lat` | Decimal → Number (TEMP の場合は `null` を返す) |
| `lon` | `lon` | Decimal → Number (TEMP の場合は `null` を返す) |
| `accuracy` | `accuracy` | Decimal → Number (TEMP の場合は `null` を返す) |
| `temperature` | `temperature` | Decimal → Number (位置系・ゾーン系の場合は `null` を返す) |
| `zoneId` | `zoneId` | そのまま (GNSS / GROUND_FIX / TEMP の場合は `null` を返す) |
| `zoneName` | `zoneName` | そのまま (GNSS / GROUND_FIX / TEMP の場合は `null` を返す) |

**SafeZones テーブル → SafeZone 型:**

| API フィールド | DynamoDB 属性 | 変換 |
|---|---|---|
| `zoneId` | `zoneId` (SK) | そのまま |
| `name` | `name` | そのまま |
| `center.lat` | `center.lat` | Decimal → Number |
| `center.lon` | `center.lon` | Decimal → Number |
| `radius` | `radius` | Decimal → Number |
| `enabled` | `enabled` | そのまま |
| `createdAt` | `createdAt` | そのまま |
| `updatedAt` | `updatedAt` | そのまま |

### 8.2 AWS 側の注意事項

- DynamoDB の数値は `Decimal` 型で保存されている。API レスポンスでは JSON の `Number` として返却すること。Python の `json.dumps` は `Decimal` を直接シリアライズできないため、カスタムエンコーダーが必要。
- `lastLocation` / `lastTemperature` が DynamoDB に存在しない場合は `null` を返すこと。キーを省略しない。
- `inSafeZone` が未設定の場合は `false` をデフォルトとする。

### 8.3 iPhone 側の注意事項

- 全レスポンスの `null` フィールドに対応するため、Swift の Codable struct では `Optional` 型を使用すること。
- タイムスタンプのパースには `ISO8601DateFormatter` を使用し、`.withFractionalSeconds` オプションを有効にすること。
- プッシュ通知の `data` フィールドは `[String: Any]` で受け取り、`type` フィールドで分岐すること。

#### GNSS / GROUND_FIX の表示ルール

`location.source` または `messageType` の値に応じて表示を切り替えること。

| 条件 | デバイスアイコン (ピン) | 在圏可能性円 | 軌跡 |
|---|---|---|---|
| `source == "GNSS"` | 表示する | 表示しない | 追加する |
| `source == "GROUND_FIX"` | 表示しない | `accuracy` (m) を半径として表示 | 追加しない |

**実装例 (概念コード):**

```swift
func updateMapDisplay(location: Location) {
    if location.source == "GNSS" {
        // デバイスアイコン（ピン）を表示
        showDevicePin(at: location)
        // 軌跡に追加
        addTrackPoint(location)
        // 在圏可能性円を非表示
        hidePossibilityCircle()
    } else if location.source == "GROUND_FIX" {
        // デバイスアイコンは非表示
        hideDevicePin()
        // 在圏可能性円を表示 (accuracy が半径)
        let radiusMeters = location.accuracy ?? 500.0
        showPossibilityCircle(center: location, radius: radiusMeters)
        // 軌跡には追加しない
    }
}
```

**GROUND_FIX の `accuracy` の目安:**

| 測位方式 | 説明 | accuracy の目安 |
|---|---|---|
| MCELL (複数基地局) | 複数セルで三角測位 | 100〜500m |
| SCELL (単一基地局) | 1セルのサービスエリア中心 | 500〜数km |

`accuracy` が `null` の場合はデフォルト値 (例: 500m) を使用すること。
