#!/usr/bin/env python3
"""发版脚本：打 tag 并推送，由 GitHub Actions 自动打包 + 建 Release。

用法：
    python3 tools/release.py 1.2.3              # 正式版
    python3 tools/release.py 1.2.3-rc1          # 预发布（Release 会标记 prerelease）
    python3 tools/release.py 1.2.3 --dry-run    # 只体检 + 试打包，不动 git
    python3 tools/release.py 1.2.3 -m "修复 x"  # 自定义 tag 说明
    python3 tools/release.py 1.2.3 --skip-build # 跳过本地试打包
    python3 tools/release.py 1.2.3 --no-push    # 只创建本地 tag，不推送

脚本做的事：
    1. 校验版本号格式、工作区是否干净、tag 是否已存在
    2. 本地跑一遍 build.py 试打包，确认两个包能生成且版本号正确
    3. git tag -a v1.2.3 → 推送 tag → CI 自动建 Release

只用标准库。
"""

import argparse
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")

OK = "  ✓"
BAD = "  ✗"
WARN = "  !"


class ReleaseError(Exception):
    pass


def run(cmd, check=True, capture=True, cwd=BASE_DIR):
    """跑一条命令，失败时抛 ReleaseError 并带上 stderr。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise ReleaseError(f"找不到命令 {cmd[0]}，请确认已安装")
    except subprocess.SubprocessError as exc:
        raise ReleaseError(f"执行 {' '.join(cmd)} 失败：{exc}")

    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ReleaseError(f"命令失败（退出码 {proc.returncode}）：{' '.join(cmd)}\n{detail}")
    return proc


def git(*args, **kwargs):
    return run(["git", *args], **kwargs)


def out(*args):
    return git(*args).stdout.strip()


def parse_version(raw):
    """接受 1.2.3 / v1.2.3 / 1.2.3-rc1，返回 (version, is_prerelease)。"""
    text = (raw or "").strip()
    if text.startswith("v"):
        text = text[1:]
    if not VERSION_RE.match(text):
        raise ReleaseError(
            f"版本号 '{raw}' 不合法，应形如 1.2.3 或 1.2.3-rc1（可带前导 v）"
        )
    return text, "-" in text


def version_key(version):
    m = VERSION_RE.match(version)
    return tuple(int(x) for x in m.groups()[:3])


def check_repo():
    if not os.path.isdir(os.path.join(BASE_DIR, ".git")):
        raise ReleaseError(f"{BASE_DIR} 不是 git 仓库根目录")
    print(f"{OK} 仓库 {BASE_DIR}")


def check_branch(allowed_dirty):
    branch = out("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise ReleaseError("当前处于 detached HEAD，请先切回分支再发版")
    print(f"{OK} 分支 {branch}")

    if not allowed_dirty:
        dirty = out("status", "--porcelain", "--untracked-files=normal")
        if dirty:
            lines = dirty.splitlines()
            preview = "\n".join("      " + ln for ln in lines[:10])
            more = f"\n      …… 另外 {len(lines) - 10} 个文件" if len(lines) > 10 else ""
            raise ReleaseError(
                "工作区有未提交的改动，发布出去的 tag 会和当前代码不一致：\n"
                f"{preview}{more}\n"
                "  先 commit 再发版；确需忽略可加 --allow-dirty"
            )
        print(f"{OK} 工作区干净")

    return branch


def check_tag_free(tag):
    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        raise ReleaseError(f"本地已存在 tag {tag}，换个版本号（不要覆盖已发布的 tag）")
    print(f"{OK} 本地无同名 tag")

    remote = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
    if remote.returncode != 0:
        print(f"{WARN} 无法查询远端 tag（{remote.stderr.strip().splitlines()[:1]}），跳过该检查")
        return
    if remote.stdout.strip():
        raise ReleaseError(f"远端已存在 tag {tag}，说明这个版本发过了，换个版本号")
    print(f"{OK} 远端无同名 tag")


def warn_if_not_latest(version):
    """版本号比已有 tag 小时提醒一下，不阻断（可能要补发老版本）。"""
    tags = git("tag", "--list", "v[0-9]*", check=False).stdout.split()
    valid = [t[1:] for t in tags if VERSION_RE.match(t[1:])] if tags else []
    if not valid:
        return
    latest = max(valid, key=version_key)
    if version_key(version) < version_key(latest):
        print(f"{WARN} {version} 低于已有最高版本 v{latest}，确认不是手滑？")


def trial_build(version):
    """本地跑一遍打包，提前暴露缺文件、清单写错之类的问题。"""
    proc = run(
        [sys.executable, os.path.join(BASE_DIR, "build.py"), "--tar", "--version", version],
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ReleaseError(f"试打包失败，先修好再发版：\n{detail}")

    dist = os.path.join(BASE_DIR, "dist")
    for pkg in ("send-ip-server", "send-ip-client"):
        tar_path = os.path.join(dist, f"{pkg}.tar.gz")
        if not os.path.isfile(tar_path):
            raise ReleaseError(f"试打包缺少 {tar_path}")
        # 包内 VERSION 必须和要发的版本一致，避免 CI 里才发现
        ver = run(
            ["tar", "-xzOf", tar_path, f"{pkg}/VERSION"], check=False
        )
        if ver.returncode != 0 or ver.stdout.strip() != version:
            raise ReleaseError(f"{pkg} 包内版本不是 {version}，打包流程有问题")
    print(f"{OK} 试打包通过（dist/send-ip-*.tar.gz）")


def create_tag(tag, message, dry_run):
    if dry_run:
        print(f"{OK} [dry-run] 将创建 tag {tag}：{message}")
        return
    git("tag", "-a", tag, "-m", message)
    print(f"{OK} 已创建 tag {tag}")


def push_everything(tag, branch, upstream, dry_run):
    """先推分支（保证代码在远端），再推 tag（触发 CI）。"""
    if dry_run:
        if upstream:
            print(f"{OK} [dry-run] 将执行 git push（{branch} → {upstream}）")
        print(f"{OK} [dry-run] 将执行 git push origin {tag}")
        return

    if upstream:
        ahead = git("rev-list", "--count", f"{upstream}..HEAD", check=False).stdout.strip()
        if ahead and ahead != "0":
            print(f"  推送分支 {branch}（领先 {ahead} 个提交）……")
            git("push")
            print(f"{OK} 分支已推送")
        else:
            print(f"{OK} 分支无新提交，跳过")
    else:
        print(f"{WARN} 当前分支没有上游，跳过分支推送（记得自己 push 代码）")

    print(f"  推送 tag {tag} ……")
    pushed = git("push", "origin", tag, check=False)
    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout or "").strip()
        raise ReleaseError(
            f"推送 tag 失败：\n{detail}\n"
            f"  本地 tag 已创建，修好网络/权限后重试：git push origin {tag}\n"
            f"  想撤销：git tag -d {tag}"
        )
    print(f"{OK} tag 已推送，CI 开始打包")


def repo_url():
    remote = git("remote", "get-url", "origin", check=False)
    if remote.returncode != 0:
        return None
    url = remote.stdout.strip()
    # git@github.com:owner/repo.git 或 https://github.com/owner/repo.git
    m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}"


def main():
    parser = argparse.ArgumentParser(description="打 tag 触发 GitHub Actions 发版")
    parser.add_argument("version", help="版本号，如 1.2.3 或 1.2.3-rc1")
    parser.add_argument("-m", "--message", default=None, help="tag 说明，默认为 release vX.Y.Z")
    parser.add_argument("--dry-run", action="store_true", help="只体检和试打包，不创建/推送 tag")
    parser.add_argument("--skip-build", action="store_true", help="跳过本地试打包")
    parser.add_argument("--no-push", action="store_true", help="只创建本地 tag，不推送")
    parser.add_argument("--allow-dirty", action="store_true", help="允许工作区有未提交改动")
    args = parser.parse_args()

    try:
        version, is_pre = parse_version(args.version)
        tag = f"v{version}"
        message = args.message or f"release {tag}"

        print(f"发版 {tag}{'（预发布）' if is_pre else ''}\n")
        check_repo()
        check_branch(args.allow_dirty)
        check_tag_free(tag)
        warn_if_not_latest(version)

        if args.skip_build:
            print(f"{WARN} 已跳过本地试打包")
        else:
            trial_build(version)

        branch = out("rev-parse", "--abbrev-ref", "HEAD")
        upstream_proc = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
        upstream = upstream_proc.stdout.strip() if upstream_proc.returncode == 0 else ""

        print()
        create_tag(tag, message, args.dry_run)
        if args.no_push:
            print(f"{OK} 已按 --no-push 停在本地，稍后手动执行：git push origin {tag}")
        else:
            push_everything(tag, branch, upstream, args.dry_run)

        url = repo_url()
        print()
        if url:
            print(f"查看进度：{url}/actions")
            print(f"发布页：  {url}/releases/tag/{tag}")
        print("CI 跑完后，Release 里会有两个包和 SHA256SUMS.txt。")
        print("服务端解压到 /opt/send-ip，客户端解压到 /opt/send-ip-agent。")
        return 0
    except ReleaseError as exc:
        print(f"\n{BAD} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
