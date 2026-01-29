# Kid GPS Tracker - Cloud Integration

このリポジトリは、Kid GPS Tracker のクラウド側統合を管理します。

## 概要

GitHub Releases から nRF Cloud へのファームウェア自動/手動アップロード機能を提供します。

## ディレクトリ構造

```
kid_gps_tracker_cloud/
├── nrf_cloud_integration/    # nRF Cloud 統合スクリプト
│   ├── nrf_cloud_api.py      # nRF Cloud REST API ラッパー
│   ├── github_fetcher.py     # GitHub Releases フェッチャー
│   ├── upload_firmware.py    # メインアップロードスクリプト
│   └── requirements.txt      # Python 依存関係
├── .env.example              # 環境変数テンプレート
└── README.md                 # このファイル
```

## セットアップ

### 1. 依存関係のインストール

```bash
cd nrf_cloud_integration
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、API キーを設定します。

```bash
cp .env.example .env
```

`.env` ファイルを編集：

```env
NRF_CLOUD_API_KEY=your_actual_api_key_here
GITHUB_TOKEN=your_github_token_here  # オプション
```

### 3. nRF Cloud API キーの取得

1. [nRF Cloud Portal](https://nrfcloud.com/) にログイン
2. **Account** → **API Keys** へ移動
3. **Create API Key** をクリック
4. 必要な権限を選択:
   - `firmware:write` - ファームウェアアップロード
   - `fota:write` - FOTA ジョブ作成
5. 生成されたキーをコピー（再表示不可なので注意）

## 使用方法

### 基本的な使用方法

最新のファームウェアを nRF Cloud にアップロード：

```bash
cd nrf_cloud_integration
python upload_firmware.py --nrf-cloud-api-key YOUR_API_KEY
```

### 特定のバージョンをアップロード

```bash
python upload_firmware.py --nrf-cloud-api-key YOUR_API_KEY --version v1.0.0
```

### 環境変数を使用

`.env` ファイルに API キーを設定している場合：

```bash
python upload_firmware.py
```

### FOTA ジョブも自動作成

```bash
python upload_firmware.py --create-fota-job --device-ids device1 device2
```

## コマンドラインオプション

| オプション | 説明 | デフォルト |
|---------|------|----------|
| `--nrf-cloud-api-key` | nRF Cloud API キー | 環境変数から取得 |
| `--github-token` | GitHub PAT | 環境変数から取得 |
| `--version` | アップロードするバージョン（例: v1.0.0） | 最新 |
| `--board` | ボード名 | nrf9151dk |
| `--create-fota-job` | FOTAジョブを自動作成 | なし |
| `--device-ids` | FOTAターゲットデバイスID | なし |

## 実行例

### 例1: 最新バージョンをアップロード

```bash
$ python upload_firmware.py
📦 GitHub Releases からファームウェアを取得中...
ℹ️  バージョン: 1.0.0
⬇️  ファームウェアをダウンロード中...
✓ Downloaded: kid_gps_tracker_v1.0.0_nrf9151dk.zip (302139 bytes)
⬆️  nRF Cloud にアップロード中...
✓ Firmware uploaded: v1.0.0 for nrf9151dk
✅ アップロード成功！
   Firmware ID: abc123...
✨ すべての処理が完了しました
```

### 例2: 特定バージョンをアップロードしてFOTAジョブ作成

```bash
$ python upload_firmware.py --version v1.0.1 --create-fota-job
📦 GitHub Releases からファームウェアを取得中...
ℹ️  バージョン: 1.0.1
⬇️  ファームウェアをダウンロード中...
✓ Downloaded: kid_gps_tracker_v1.0.1_nrf9151dk.zip (305241 bytes)
⬆️  nRF Cloud にアップロード中...
✓ Firmware uploaded: v1.0.1 for nrf9151dk
✅ アップロード成功！
   Firmware ID: xyz789...
🚀 FOTA ジョブを作成中...
✓ FOTA job created: job-abc-123
✅ FOTA ジョブ作成成功: job-abc-123
✨ すべての処理が完了しました
```

## トラブルシューティング

### エラー: "nRF Cloud API キーが指定されていません"

`.env` ファイルを作成して `NRF_CLOUD_API_KEY` を設定するか、コマンドラインで `--nrf-cloud-api-key` オプションを使用してください。

### エラー: "Upload failed: 403"

API キーの権限を確認してください。`firmware:write` 権限が必要です。

### エラー: "Firmware asset not found"

指定されたバージョンに対応するファームウェアファイルが GitHub Releases に存在しません。バージョン番号を確認してください。

## nRF Cloud でのファームウェア確認

1. [nRF Cloud Portal](https://nrfcloud.com/) にログイン
2. **Firmware Update** → **Firmware Bundles** へ移動
3. アップロードされたファームウェアを確認

## FOTA ジョブの実行

1. nRF Cloud Portal → **Firmware Update** → **FOTA Jobs**
2. ジョブを選択
3. **Start Job** をクリック
4. デバイスが接続されていれば自動的に更新が開始されます

## 関連リンク

- [nRF Cloud API ドキュメント](https://api.nrfcloud.com/)
- [kid_gps_tracker リポジトリ](https://github.com/kid-gps-tracker-org/kid_gps_tracker)
- [nRF Cloud Portal](https://nrfcloud.com/)

## ライセンス

MIT License
