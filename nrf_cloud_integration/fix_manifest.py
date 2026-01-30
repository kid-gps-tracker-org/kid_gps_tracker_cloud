#!/usr/bin/env python3
"""
ZIPファイル内のmanifest.jsonにfwversionフィールドを追加
"""
import json
import zipfile
import tempfile
import shutil
from pathlib import Path
import sys

def fix_manifest(zip_path: Path, version: str, output_path: Path = None):
    """
    ZIPファイル内のmanifest.jsonにfwversionを追加

    Args:
        zip_path: 元のZIPファイルパス
        version: ファームウェアバージョン (例: "1.0.0")
        output_path: 出力先 (Noneの場合は元のファイルを上書き)
    """
    if output_path is None:
        output_path = zip_path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # ZIPを展開
        with zipfile.ZipFile(zip_path, 'r') as zip_in:
            zip_in.extractall(tmpdir_path)

        # manifest.jsonを読み込み
        manifest_path = tmpdir_path / 'manifest.json'
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)

        # fwversionを追加
        manifest['fwversion'] = version

        # manifest.jsonを書き込み
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)

        print(f"✓ Added fwversion: {version}")

        # 新しいZIPを作成
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for file_path in tmpdir_path.iterdir():
                if file_path.is_file():
                    zip_out.write(file_path, file_path.name)

        print(f"✓ Created: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python fix_manifest.py <zip_file> <version>")
        print("Example: python fix_manifest.py firmware.zip 1.0.0")
        sys.exit(1)

    zip_file = Path(sys.argv[1])
    version = sys.argv[2]

    if not zip_file.exists():
        print(f"Error: {zip_file} not found")
        sys.exit(1)

    fix_manifest(zip_file, version)
    print("✨ Done!")
