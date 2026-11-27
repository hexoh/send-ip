"""Render templates/index.html with sample data to produce a static snapshot that can be previewed directly.

Why: templates/index.html is a Jinja2 template, so opening it in a browser/editor shows raw
{{ }} and {% %}. Run this script when you want to preview the real output:

    python tools/preview.py            # write to ui/preview.html
    python tools/preview.py --empty    # preview the "no IP received yet" empty state
    python tools/preview.py --lang zh  # preview the Chinese version (the switch still works in the file)
    python tools/preview.py --login    # write to ui/preview-login.html (the password prompt)
    python tools/preview.py --login --error  # preview the wrong-password error state

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
UI_DIR = os.path.join(ROOT_DIR, "ui")
CST = timezone(timedelta(hours=8))


def main():
    parser = argparse.ArgumentParser(description="Render a template snapshot for preview")
    parser.add_argument("--empty", action="store_true", help="Render the empty state (no IP yet)")
    parser.add_argument("--login", action="store_true", help="Render the password prompt (APP_PASSWORD set)")
    parser.add_argument("--error", action="store_true", help="With --login: also show the wrong-password message")
    parser.add_argument("--lang", choices=("en", "zh"), default="en", help="Page language (default: en)")
    parser.add_argument("--out", default=None, help="Output path (default: ui/preview.html, ui/preview-login.html with --login)")
    args = parser.parse_args()

    out = args.out or os.path.join(UI_DIR, "preview-login.html" if args.login else "preview.html")

    app = Flask(__name__, template_folder=TEMPLATE_DIR)
    now = datetime.now(CST)

    if args.login or args.empty:
        data = {"ip": None, "first_seen": None, "last_seen": None}
    else:
        data = {
            "ip": "203.0.113.55",
            "first_seen": (now - timedelta(days=3, hours=2)).isoformat(timespec="seconds"),
            "last_seen": (now - timedelta(minutes=24)).isoformat(timespec="seconds"),
        }

    with app.app_context():
        html = render_template(
            "index.html",
            lang=args.lang,
            authed=not args.login,
            error="wrongPassword" if (args.login and args.error) else None,
            **data,
        )

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"Generated {out}; open it in a browser to preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
