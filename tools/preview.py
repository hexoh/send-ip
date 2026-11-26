"""用示例数据渲染 templates/index.html，生成可直接预览的静态快照。

用途：templates/index.html 是 Jinja2 模板，直接用浏览器/编辑器预览会看到
未渲染的 {{ }} 和 {% %}。想预览真实效果时运行本脚本：

    python tools/preview.py            # 输出到 preview.html
    python tools/preview.py --empty    # 预览"尚未接收 IP"的空状态

注意：快照里的时间是相对当前时间生成的，仅供看版式，不参与线上服务。
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
