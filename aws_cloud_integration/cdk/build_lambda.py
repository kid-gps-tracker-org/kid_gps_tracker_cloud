#!/usr/bin/env python3
"""
Lambda デプロイパッケージのビルドスクリプト
Docker なしで Lambda コードと依存パッケージをバンドルする。

ビルド対象:
- polling: nRF Cloud ポーリング Lambda
- api: iPhone 向け REST API Lambda
"""
import shutil
import subprocess
import sys
from pathlib import Path

# パス定義
CDK_DIR = Path(__file__).parent
LAMBDA_BASE = CDK_DIR.parent / "lambda"
BUILD_BASE = CDK_DIR / ".build"

# Lambda 定義: (名前, ソースディレクトリ)
LAMBDAS = [
    ("polling", LAMBDA_BASE / "polling"),
    ("api", LAMBDA_BASE / "api"),
]


def build_lambda(name: str, src_dir: Path):
    """単一の Lambda パッケージをビルドする。"""
    build_dir = BUILD_BASE / name
    print(f"\nBuilding Lambda package: {name}")
    print(f"  Source: {src_dir}")
    print(f"  Output: {build_dir}")

    # ビルドディレクトリをクリーンアップ
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    # pip で依存パッケージをインストール
    requirements_file = src_dir / "requirements.txt"
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
                str(build_dir),
                "--quiet",
            ]
        )

    # Lambda ソースコードをコピー
    print("  Copying Lambda source files...")
    for src_file in src_dir.glob("*.py"):
        shutil.copy2(src_file, build_dir / src_file.name)

    py_files = list(build_dir.glob("*.py"))
    dirs = [d for d in build_dir.iterdir() if d.is_dir()]
    print(f"  Done. Python files: {len(py_files)}, Directories: {len(dirs)}")


def build():
    """すべての Lambda パッケージをビルドする。"""
    print("=" * 60)
    print("  Lambda Package Builder")
    print("=" * 60)

    for name, src_dir in LAMBDAS:
        if src_dir.exists():
            build_lambda(name, src_dir)
        else:
            print(f"\n  SKIP: {name} (source directory not found: {src_dir})")

    print("\n" + "=" * 60)
    print("  Build complete!")
    print("=" * 60)


if __name__ == "__main__":
    build()
