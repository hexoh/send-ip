#!/usr/bin/env python3
"""Release script: create and push a tag; GitHub Actions handles packaging and creating the Release.

Usage:
    python3 tools/release.py 1.2.3              # stable release
    python3 tools/release.py 1.2.3-rc1          # pre-release (the Release is marked prerelease)
    python3 tools/release.py 1.2.3 --dry-run    # checks + trial build only, no git changes
    python3 tools/release.py 1.2.3 -m "fix x"   # custom tag message
    python3 tools/release.py 1.2.3 --skip-build # skip the local trial build
    python3 tools/release.py 1.2.3 --no-push    # create the local tag only, do not push

What the script does:
    1. Validate the version format, a clean working tree, and that the tag does not already exist
    2. Run build.py locally as a trial build to confirm both bundles build with the right version
    3. git tag -a v1.2.3 -> push the tag -> CI creates the Release automatically

Standard library only.
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
    """Run a command; on failure raise ReleaseError with stderr attached."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise ReleaseError(f"Command not found: {cmd[0]}; make sure it is installed")
    except subprocess.SubprocessError as exc:
        raise ReleaseError(f"Failed to run {' '.join(cmd)}: {exc}")

    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ReleaseError(f"Command failed (exit code {proc.returncode}): {' '.join(cmd)}\n{detail}")
    return proc


def git(*args, **kwargs):
    return run(["git", *args], **kwargs)


def out(*args):
    return git(*args).stdout.strip()


def parse_version(raw):
    """Accept 1.2.3 / v1.2.3 / 1.2.3-rc1 and return (version, is_prerelease)."""
    text = (raw or "").strip()
    if text.startswith("v"):
        text = text[1:]
    if not VERSION_RE.match(text):
        raise ReleaseError(
            f"Invalid version '{raw}'; expected something like 1.2.3 or 1.2.3-rc1 (a leading v is allowed)"
        )
    return text, "-" in text


def version_key(version):
    m = VERSION_RE.match(version)
    return tuple(int(x) for x in m.groups()[:3])


def check_repo():
    if not os.path.isdir(os.path.join(BASE_DIR, ".git")):
        raise ReleaseError(f"{BASE_DIR} is not a git repository root")
    print(f"{OK} repository {BASE_DIR}")


def check_branch(allowed_dirty):
    branch = out("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise ReleaseError("Currently in detached HEAD; switch back to a branch before releasing")
    print(f"{OK} branch {branch}")

    if not allowed_dirty:
        dirty = out("status", "--porcelain", "--untracked-files=normal")
        if dirty:
            lines = dirty.splitlines()
            preview = "\n".join("      " + ln for ln in lines[:10])
            more = f"\n      ... and {len(lines) - 10} more files" if len(lines) > 10 else ""
            raise ReleaseError(
                "The working tree has uncommitted changes; the released tag would not match the current code:\n"
                f"{preview}{more}\n"
                "  Commit first, then release; add --allow-dirty to ignore this check"
            )
        print(f"{OK} working tree clean")

    return branch


def check_tag_free(tag):
    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        raise ReleaseError(f"Local tag {tag} already exists; choose another version (do not overwrite a released tag)")
    print(f"{OK} no local tag with that name")

    remote = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
    if remote.returncode != 0:
        print(f"{WARN} cannot query remote tags ({remote.stderr.strip().splitlines()[:1]}); skipping this check")
        return
    if remote.stdout.strip():
        raise ReleaseError(f"Remote tag {tag} already exists, so this version was already released; choose another version")
    print(f"{OK} no remote tag with that name")


def warn_if_not_latest(version):
    """Warn (without blocking) when the version is lower than an existing tag, since a backport may be intentional."""
    tags = git("tag", "--list", "v[0-9]*", check=False).stdout.split()
    valid = [t[1:] for t in tags if VERSION_RE.match(t[1:])] if tags else []
    if not valid:
        return
    latest = max(valid, key=version_key)
    if version_key(version) < version_key(latest):
        print(f"{WARN} {version} is lower than the highest existing version v{latest}; sure this is intentional?")


def trial_build(version):
    """Run a local trial build to surface missing files, bad manifests, and similar problems early."""
    proc = run(
        [sys.executable, os.path.join(BASE_DIR, "build.py"), "--tar", "--version", version],
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ReleaseError(f"Trial build failed; fix it before releasing:\n{detail}")

    dist = os.path.join(BASE_DIR, "dist")
    for pkg in ("send-ip-server", "send-ip-client"):
        tar_path = os.path.join(dist, f"{pkg}.tar.gz")
        if not os.path.isfile(tar_path):
            raise ReleaseError(f"Trial build is missing {tar_path}")
        # The bundled VERSION must match the version being released, to catch problems before CI
        ver = run(
            ["tar", "-xzOf", tar_path, f"{pkg}/VERSION"], check=False
        )
        if ver.returncode != 0 or ver.stdout.strip() != version:
            raise ReleaseError(f"{pkg} bundle version is not {version}; the packaging flow is broken")
    print(f"{OK} trial build passed (dist/send-ip-*.tar.gz)")


def create_tag(tag, message, dry_run):
    if dry_run:
        print(f"{OK} [dry-run] would create tag {tag}: {message}")
        return
    git("tag", "-a", tag, "-m", message)
    print(f"{OK} created tag {tag}")


def push_everything(tag, branch, upstream, dry_run):
    """Push the branch first (ensure the code is on the remote), then push the tag (which triggers CI)."""
    if dry_run:
        if upstream:
            print(f"{OK} [dry-run] would run git push ({branch} -> {upstream})")
        print(f"{OK} [dry-run] would run git push origin {tag}")
        return

    if upstream:
        ahead = git("rev-list", "--count", f"{upstream}..HEAD", check=False).stdout.strip()
        if ahead and ahead != "0":
            print(f"  Pushing branch {branch} ({ahead} commits ahead)...")
            git("push")
            print(f"{OK} branch pushed")
        else:
            print(f"{OK} no new commits on the branch; skipping")
    else:
        print(f"{WARN} current branch has no upstream; skipping branch push (remember to push your code)")

    print(f"  Pushing tag {tag} ...")
    pushed = git("push", "origin", tag, check=False)
    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout or "").strip()
        raise ReleaseError(
            f"Failed to push tag:\n{detail}\n"
            f"  The local tag was created; retry after fixing network/permissions: git push origin {tag}\n"
            f"  To undo: git tag -d {tag}"
        )
    print(f"{OK} tag pushed; CI is building")


def repo_url():
    remote = git("remote", "get-url", "origin", check=False)
    if remote.returncode != 0:
        return None
    url = remote.stdout.strip()
    # git@github.com:owner/repo.git or https://github.com/owner/repo.git
    m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}"


def main():
    parser = argparse.ArgumentParser(description="Create a tag to trigger a GitHub Actions release")
    parser.add_argument("version", help="Version, e.g. 1.2.3 or 1.2.3-rc1")
    parser.add_argument("-m", "--message", default=None, help="Tag message, defaults to release vX.Y.Z")
    parser.add_argument("--dry-run", action="store_true", help="Run checks and a trial build only; do not create/push a tag")
    parser.add_argument("--skip-build", action="store_true", help="Skip the local trial build")
    parser.add_argument("--no-push", action="store_true", help="Create the local tag only; do not push")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes in the working tree")
    args = parser.parse_args()

    try:
        version, is_pre = parse_version(args.version)
        tag = f"v{version}"
        message = args.message or f"release {tag}"

        print(f"Releasing {tag}{' (pre-release)' if is_pre else ''}\n")
        check_repo()
        check_branch(args.allow_dirty)
        check_tag_free(tag)
        warn_if_not_latest(version)

        if args.skip_build:
            print(f"{WARN} skipped local trial build")
        else:
            trial_build(version)

        branch = out("rev-parse", "--abbrev-ref", "HEAD")
        upstream_proc = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
        upstream = upstream_proc.stdout.strip() if upstream_proc.returncode == 0 else ""

        print()
        create_tag(tag, message, args.dry_run)
        if args.no_push:
            print(f"{OK} stopped locally due to --no-push; run later: git push origin {tag}")
        else:
            push_everything(tag, branch, upstream, args.dry_run)

        url = repo_url()
        print()
        if url:
            print(f"Progress: {url}/actions")
            print(f"Release:  {url}/releases/tag/{tag}")
        print("When CI finishes, the Release will contain both bundles and SHA256SUMS.txt.")
        print("Extract the server bundle to /opt/send-ip and the client bundle to /opt/send-ip-agent.")
        return 0
    except ReleaseError as exc:
        print(f"\n{BAD} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
