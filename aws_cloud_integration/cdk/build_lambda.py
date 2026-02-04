#!/usr/bin/env python3
"""
Lambda デプロイパッケージのビルドスクリプト
Docker なしで Lambda コードと依存パッケージをバンドルする。
"""
import shutil
import subprocess
import sys
from pathlib import Path

# パス定義
CDK_DIR = Path(__file__).parent
LAMBDA_SRC = CDK_DIR.parent / "lambda" / "polling"
BUILD_DIR = CDK_DIR / ".build" / "polling"


def build():
    print(f"Building Lambda package...")
    print(f"  Source: {LAMBDA_SRC}")
    print(f"  Output: {BUILD_DIR}")

    # ビルドディレクトリをクリーンアップ
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # pip で依存パッケージをインストール
    requirements_file = LAMBDA_SRC / "requirements.txt"
    if requirements_file.exists():
        print("  Installing dependencies...")
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_file),
                "-t",
                str(BUILD_DIR),
                "--quiet",
            ]
        )

    # Lambda ソースコードをコピー
    print("  Copying Lambda source files...")
    for src_file in LAMBDA_SRC.glob("*.py"):
        shutil.copy2(src_file, BUILD_DIR / src_file.name)

    print(f"  Done. Package contents:")
    py_files = list(BUILD_DIR.glob("*.py"))
    dirs = [d for d in BUILD_DIR.iterdir() if d.is_dir()]
    print(f"    Python files: {len(py_files)}")
    print(f"    Directories: {len(dirs)}")


if __name__ == "__main__":
    build()
