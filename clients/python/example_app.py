from __future__ import annotations

from pathlib import Path

from keydesk_client import KeyDeskApp, KeyDeskError


def main() -> int:
    app = KeyDeskApp.from_file(Path(__file__).with_name("keydesk-client.json"))
    try:
        update = app.check_update()
        if update.get("force"):
            print(f"需要强制更新到 {update.get('version')}: {update.get('url') or '请联系管理员获取安装包'}")
            return 1

        card = app.require_license()
        variables = app.cloud_variables()
        print(f"授权通过，到期时间: {card.get('endTime') or '永久'}")
        print(f"云变量: {variables}")
        return 0
    except KeyDeskError as exc:
        print(f"授权失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
