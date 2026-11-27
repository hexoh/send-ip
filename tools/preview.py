"""Render templates/index.html with sample data to produce a static snapshot that can be previewed directly.

Why: templates/index.html is a Jinja2 template, so opening it in a browser/editor shows raw
{{ }} and {% %}. Run this script when you want to preview the real output:

    python tools/preview.py            # write to preview.html
    python tools/preview.py --empty    # preview the "no IP received yet" empty state

Note: timestamps in the snapshot are generated relative to the current time; they are for
layout preview only and are not used by the live service.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT_DIR, "server", "templates")
CST = timezone(timedelta(hours=8))


def main():
    parser = argparse.ArgumentParser(description="渲染模板快照用于预览")
    parser.add_argument("--empty", action="store_true", help="渲染空状态（尚无 IP）")
    parser.add_argument("--out", default=os.path.join(ROOT_DIR, "preview.html"))
    args = parser.parse_args()

    app = Flask(__name__, template_folder=TEMPLATE_DIR)
    now = datetime.now(CST)

    if args.empty:
        data = {"ip": None, "first_seen": None, "last_seen": None}
    else:
        data = {
            "ip": "203.0.113.55",
            "first_seen": (now - timedelta(days=3, hours=2)).isoformat(timespec="seconds"),
            "last_seen": (now - timedelta(minutes=24)).isoformat(timespec="seconds"),
        }

    with app.app_context():
        html = render_template("index.html", **data)

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"已生成 {args.out}，用浏览器打开即可预览")
    return 0


if __name__ == "__main__":
    sys.exit(main())
