#!/usr/bin/env python3
"""Packaging script: split the repository into two ready-to-upload folders, server and client.

Usage:
    python3 build.py                 # produce dist/send-ip-server and dist/send-ip-client
    python3 build.py --tar           # also produce the two .tar.gz archives
    python3 build.py --out /tmp/pkg  # set the output directory
    python3 build.py --version 1.2.0 # set the version (defaults to git describe)
    python3 build.py --clean         # clean only, do not build

Standard library only, no dependencies needed; just run python3 build.py.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(BASE_DIR, "dist")

SERVER_NAME = "send-ip-server"
CLIENT_NAME = "send-ip-client"

# Files to package for each side: source (relative to repo root) -> target path inside the bundle
# The repo keeps server/ and client/ separate; bundles are flattened into the real deployment layout
SERVER_FILES = [
    ("server/app.py", "app.py"),
    ("server/templates/index.html", "templates/index.html"),
    ("server/requirements.txt", "requirements.txt"),
    ("server/.env.example", ".env.example"),
    ("server/sendip.service", "deploy/sendip.service"),
    ("server/nginx.conf", "deploy/nginx.conf"),
    ("server/Dockerfile", "Dockerfile"),
]

CLIENT_FILES = [
    ("client/index.py", "index.py"),
    ("client/requirements.txt", "requirements.txt"),
    ("client/sendip-agent.service", "deploy/sendip-agent.service"),
    ("client/sendip-agent.env.example", "deploy/sendip-agent.env.example"),
]

def detect_version():
    """Fall back to the current tag when no version is given; otherwise mark it as dev.

    git describe returns v1.2.0 on a tagged commit, and v1.2.0-3-gabc1234 afterwards.
    """
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "dev"
    if out.returncode != 0:
        return "dev"
    return out.stdout.strip() or "dev"


def normalize_version(raw):
    """v1.2.0 -> 1.2.0, ensuring the VERSION file has no leading v."""
    v = (raw or "").strip()
    if v.startswith("v"):
        v = v[1:]
    return v or "dev"


def write_version(bundle_dir, version):
    path = os.path.join(bundle_dir, "VERSION")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(version + "\n")
    return path


def copy_files(bundle_dir, files):
    missing = []
    for src_rel, dst_rel in files:
        src = os.path.join(BASE_DIR, src_rel)
        if not os.path.isfile(src):
            missing.append(src_rel)
            continue
        dst = os.path.join(bundle_dir, dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return missing


def make_tar(bundle_dir, out_dir):
    name = os.path.basename(bundle_dir)
    tar_path = os.path.join(out_dir, f"{name}.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=name)
    return tar_path


def tree(bundle_dir):
    lines = []
    for root, dirs, files in os.walk(bundle_dir):
        dirs.sort()
        rel = os.path.relpath(root, bundle_dir)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if rel != ".":
            lines.append("  " * (depth - 1) + os.path.basename(root) + "/")
        for f in sorted(files):
            size = os.path.getsize(os.path.join(root, f))
            lines.append("  " * depth + f"{f}  ({size:,} B)")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="打包 server / client 两个部署包")
    parser.add_argument("--out", default=DEFAULT_OUT, help="输出目录，默认 ./dist")
    parser.add_argument("--tar", action="store_true", help="额外生成 .tar.gz 压缩包")
    parser.add_argument(
        "--version",
        default=None,
        help="版本号，写入包内 VERSION 文件；默认取 git describe 结果",
    )
    parser.add_argument("--clean", action="store_true", help="只清理输出目录")
    args = parser.parse_args()

    version = normalize_version(args.version or detect_version())

    server_dir = os.path.join(args.out, SERVER_NAME)
    client_dir = os.path.join(args.out, CLIENT_NAME)

    # Clean the old bundle directories first so no stale files are left behind
    for d in (server_dir, client_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)
    for name in (SERVER_NAME, CLIENT_NAME):
        old_tar = os.path.join(args.out, name + ".tar.gz")
        if os.path.isfile(old_tar):
            os.remove(old_tar)

    if args.clean:
        print(f"已清理 {args.out}")
        return 0

    os.makedirs(server_dir, exist_ok=True)
    os.makedirs(client_dir, exist_ok=True)

    missing = []
    missing += copy_files(server_dir, SERVER_FILES)
    missing += copy_files(client_dir, CLIENT_FILES)

    if missing:
        print("以下文件缺失，打包中止：", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1

    write_version(server_dir, version)
    write_version(client_dir, version)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"打包完成（{stamp}）  版本 {version} → {args.out}\n")

    for d in (server_dir, client_dir):
        print(f"[{os.path.basename(d)}]")
        print(tree(d))
        print()

    if args.tar:
        print("压缩包：")
        for d in (server_dir, client_dir):
            p = make_tar(d, args.out)
            print(f"  {p}  ({os.path.getsize(p):,} B)")
        print()

    print("用法：把对应文件夹整个上传到目标机器即可，")
    print("      服务端 → /opt/send-ip，客户端 → /opt/send-ip-agent。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
