# Kid GPS Tracker - Cloud Integration

このリポジトリは、Kid GPS Tracker のクラウド側統合を管理します。

## 概要

GitHub Releases から nRF Cloud へのファームウェア管理機能を提供します。

### 現在の状態

**動作確認済み:**
- ✅ GitHub API接続とファームウェア取得
- ✅ nRF Cloud API接続テスト
- ✅ GitHub Releasesからのファームウェアダウンロード
- ✅ nRF Cloud REST API経由のファームウェアアップロード

**注意事項:**
- ZIPファイル内の `manifest.json` に `fwversion` フィールドが必要です（スクリプトが自動追加します）
- アップロードには `Content-Type: application/zip` を使用します

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

### 方法1: 手動アップロード（Developer プラン推奨）

#### ステップ1: API接続テスト

```bash
cd nrf_cloud_integration
python test_api.py
```

成功すると、GitHubとnRF CloudのAPI接続が確認できます。

#### ステップ2: GitHub Releasesから最新ファームウェアを確認

1. https://github.com/kid-gps-tracker-org/kid_gps_tracker/releases にアクセス
2. 最新リリースから `kid_gps_tracker_v*.*.0_nrf9151dk.zip` をダウンロード

#### ステップ3: nRF Cloud ポータルでアップロード

1. [nRF Cloud Portal](https://nrfcloud.com/) にログイン
2. 左メニューから **Firmware Update** → **Firmware Bundles** を選択
3. **Upload Bundle** をクリック
4. ダウンロードした `.zip` ファイルを選択してアップロード
5. 以下の情報を入力:
   - **Name**: `kid_gps_tracker_nrf9151dk_v1.0.0` (バージョンに合わせて変更)
   - **Version**: `1.0.0` (v なし)
   - **Firmware Type**: `APP`
   - **Description**: `Kid GPS Tracker firmware v1.0.0 for nRF9151dk`

#### ステップ4: デバイスグループの作成（初回のみ）

1. nRF Cloud Portal → **Device Management** → **Device Groups**
2. **Create Device Group** をクリック
3. グループ名を入力（例: `kid_gps_tracker_production`）
4. デバイスを追加

#### ステップ5: FOTA ジョブの作成

1. **Firmware Update** → **FOTA Jobs** → **Create FOTA Job**
2. アップロードしたファームウェアを選択
3. ターゲットデバイスグループを選択
4. **Create Job** をクリック
5. **Start Job** でFOTAを開始

### 方法2: REST API自動アップロード（推奨）

#### 基本的な使用方法

```bash
cd nrf_cloud_integration
python upload_firmware.py --version v1.0.0
```

#### FOTA ジョブも自動作成

```bash
python upload_firmware.py --version v1.0.0 --create-fota-job --device-ids device1 device2
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

### エラー: "ValidationError[enum]: request.headers['content-type'] should be equal to one of the allowed values"

**原因**: nRF Cloud API は特定の Content-Type のみ受け付けます。

**許可される値**: `application/zip`, `application/octet-stream`, `text/plain`, `text/plain;charset=UTF8`, `text/plain;charset=ASCII`

**解決策**: `upload_firmware.py` は `application/zip` を使用しています。直接 API を呼び出す場合は上記の値を使用してください。

### エラー: "Invalid value undefined supplied to : FirmwareVersionValue"

**原因**: ZIPファイル内の `manifest.json` に `fwversion` フィールドがありません。

**解決策**: `upload_firmware.py` は自動的に `fwversion` を追加します。手動でアップロードする場合は、ZIPを展開して `manifest.json` に `"fwversion": "1.0.0"` を追加してください。

### エラー: "nRF Cloud API キーが指定されていません"

`.env` ファイルを作成して `NRF_CLOUD_API_KEY` を設定するか、コマンドラインで `--nrf-cloud-api-key` オプションを使用してください。

### エラー: "Upload failed: 403"

API キーの権限を確認してください。`firmware:write` 権限が必要です。

### エラー: "Firmware asset not found"

指定されたバージョンに対応するファームウェアファイルが GitHub Releases に存在しません。バージョン番号を確認してください。

### アップロードは成功したが "Firmware ID: None" と表示される

nRF Cloud API は `uris` フィールドでバンドル情報を返します。最新の `upload_firmware.py` ではURIから Bundle ID を自動抽出します。

## nRF Cloud でのファームウェア確認

1. [nRF Cloud Portal](https://nrfcloud.com/) にログイン
2. **Firmware Update** → **Firmware Bundles** へ移動
3. アップロードされたファームウェアを確認

## FOTA ジョブの実行

1. nRF Cloud Portal → **Firmware Update** → **FOTA Jobs**
2. ジョブを選択
3. **Start Job** をクリック
4. デバイスが接続されていれば自動的に更新が開始されます

## 実装済み機能

### Phase 1-2: デバイス側 CI/CD（完了）
- ✅ GitHub Actions による自動ビルド
- ✅ Git tag によるバージョン管理
- ✅ GitHub Releases への自動公開
- ✅ 日本語リリースノート自動生成

### Phase 3: クラウド統合（完了）
- ✅ nRF Cloud API 接続テスト
- ✅ GitHub API 経由でのファームウェア取得
- ✅ REST API ラッパー実装
- ✅ REST API ファームウェアアップロード（manifest.json の fwversion 自動追加対応）
- ✅ 手動/自動アップロードワークフロー文書化

## 推奨ワークフロー

1. **開発**: デバイスコードを変更・コミット
2. **リリース**: Git tag を作成 → GitHub Actions が自動ビルド・公開
3. **配信**: `python upload_firmware.py --version v1.0.0` で nRF Cloud へアップロード
4. **デバイス更新**: FOTA ジョブを作成・実行

## 関連リンク

- [nRF Cloud Portal](https://nrfcloud.com/)
- [nRF Cloud API ドキュメント](https://api-docs.nrfcloud.com/)
- [kid_gps_tracker リポジトリ](https://github.com/kid-gps-tracker-org/kid_gps_tracker)
- [kid_gps_tracker Releases](https://github.com/kid-gps-tracker-org/kid_gps_tracker/releases)

## ライセンス

MIT License
