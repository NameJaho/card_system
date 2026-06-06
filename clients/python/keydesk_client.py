#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class KeyDeskError(RuntimeError):
    pass


@dataclass
class KeyDeskClient:
    base_url: str
    timeout: int = 10

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise KeyDeskError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise KeyDeskError(f"Network error: {exc.reason}") from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KeyDeskError(f"Invalid JSON response: {raw[:200]}") from exc
        if not result.get("success"):
            raise KeyDeskError(result.get("message") or "request failed")
        return result

    def check_update(self, software_id: str, version: str, macid: str = "") -> dict[str, Any]:
        return self._post("/api/client/software/checkUpdate", {"softwareId": software_id, "version": version, "macid": macid})

    def activate(self, software_id: str, auth_id: str, macid: str) -> dict[str, Any]:
        return self._post("/api/client/auth/activate", {"softwareId": software_id, "authId": auth_id, "macid": macid})

    def verify(self, software_id: str, auth_id: str, macid: str) -> dict[str, Any]:
        return self._post("/api/client/auth/verify", {"softwareId": software_id, "authId": auth_id, "macid": macid})

    def unbind(self, software_id: str, auth_id: str, macid: str) -> dict[str, Any]:
        return self._post("/api/client/auth/unbind", {"softwareId": software_id, "authId": auth_id, "macid": macid})

    def cloud_variables(self, software_id: str) -> dict[str, Any]:
        return self._post("/api/client/cloudVariables/list", {"softwareId": software_id})

    def register_user(self, software_id: str, email: str, password: str, nick_name: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/user/register",
            {"softwareId": software_id, "email": email, "password": password, "nickName": nick_name or email},
        )

    def login_user(self, software_id: str, email: str, password: str) -> dict[str, Any]:
        return self._post("/api/client/user/login", {"softwareId": software_id, "email": email, "password": password})

    def heartbeat(self, software_id: str, customer_id: str = "", macid: str = "") -> dict[str, Any]:
        return self._post("/api/client/user/heartbeat", {"softwareId": software_id, "customerId": customer_id, "macid": macid})

    def logout_user(self, software_id: str, customer_id: str = "") -> dict[str, Any]:
        return self._post("/api/client/user/logout", {"softwareId": software_id, "customerId": customer_id})


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_demo(client: KeyDeskClient, args: argparse.Namespace) -> None:
    print("1. check update")
    print_json(client.check_update(args.software_id, args.version, args.macid))
    if args.auth_id:
        print("2. verify license")
        print_json(client.verify(args.software_id, args.auth_id, args.macid))
    print("3. cloud variables")
    print_json(client.cloud_variables(args.software_id))
    if args.email and args.password:
        print("4. login user")
        user = client.login_user(args.software_id, args.email, args.password)
        print_json(user)
        customer_id = (user.get("data") or {}).get("customerId", "")
        print("5. heartbeat")
        print_json(client.heartbeat(args.software_id, customer_id, args.macid))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyDesk client API example")
    parser.add_argument("--base-url", required=True, help="例如 http://127.0.0.1:8000 或 http://服务器IP:8080")
    parser.add_argument("--software-id", required=True, help="后台实例 ID")
    parser.add_argument("--auth-id", default="", help="卡密，activate/verify/unbind 需要")
    parser.add_argument("--macid", default="DEMO-MACHINE-1", help="客户端设备码")
    parser.add_argument("--version", default="1.0.0", help="当前客户端版本")
    parser.add_argument("--email", default="", help="软件侧用户邮箱")
    parser.add_argument("--password", default="", help="软件侧用户密码")
    parser.add_argument("--nick-name", default="", help="软件侧用户昵称")
    parser.add_argument("--customer-id", default="", help="软件侧用户编号，heartbeat/logout 可直接传")
    parser.add_argument("--interval", type=int, default=0, help="heartbeat 循环间隔秒数，0 表示只执行一次")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ["check-update", "activate", "verify", "unbind", "vars", "register", "login", "heartbeat", "logout", "demo"]:
        subparsers.add_parser(command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    client = KeyDeskClient(args.base_url)
    try:
        if args.command == "check-update":
            print_json(client.check_update(args.software_id, args.version, args.macid))
        elif args.command == "activate":
            print_json(client.activate(args.software_id, args.auth_id, args.macid))
        elif args.command == "verify":
            print_json(client.verify(args.software_id, args.auth_id, args.macid))
        elif args.command == "unbind":
            print_json(client.unbind(args.software_id, args.auth_id, args.macid))
        elif args.command == "vars":
            print_json(client.cloud_variables(args.software_id))
        elif args.command == "register":
            print_json(client.register_user(args.software_id, args.email, args.password, args.nick_name))
        elif args.command == "login":
            print_json(client.login_user(args.software_id, args.email, args.password))
        elif args.command == "heartbeat":
            while True:
                print_json(client.heartbeat(args.software_id, args.customer_id, args.macid))
                if args.interval <= 0:
                    break
                time.sleep(args.interval)
        elif args.command == "logout":
            print_json(client.logout_user(args.software_id, args.customer_id))
        elif args.command == "demo":
            run_demo(client, args)
    except KeyDeskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
