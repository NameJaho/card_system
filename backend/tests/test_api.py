import json
import io
import os
import sys
import tempfile
import urllib.error
import zipfile
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["CARD_DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/keydesk_api_test.db"
os.environ["CARD_ALLOW_DEV_RESET_LINK"] = "true"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import Base, SessionLocal, engine
from app.config import get_settings, validate_production_settings
from app.main import app
from app.models import AuthCard, PasswordResetToken


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    yield


def login_payload(client: TestClient, user: str = "admin", password: str = "admin123456") -> dict:
    response = client.post("/api/adm/login", json={"user": user, "password": password})
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["token"]
    return payload


def login(client: TestClient) -> dict:
    payload = login_payload(client)
    assert payload["data"]["role"] == "developer"
    assert payload["data"]["roleLabel"] == "超级管理员"
    assert "accountToken" in payload["data"]
    assert "openId" in payload["data"]
    return {"token": payload["data"]["token"]}


def assert_ok(response, path: str = "") -> dict:
    assert response.status_code == 200, path
    payload = response.json()
    assert payload["success"] is True, f"{path}: {payload}"
    return payload


def test_admin_and_client_auth_flow():
    with TestClient(app) as client:
        headers = login(client)

        software = client.post("/api/adm/softwareSelect", json={}, headers=headers).json()
        assert software["success"] is True
        assert software["data"]
        software_id = software["data"][0]["softwareId"]
        instance_key = software["data"][0]["instanceKey"]
        assert instance_key.startswith("IK")

        created = client.post(
            "/api/adm/createAuth",
            json={"softwareId": software_id, "createNumber": 1, "day": 1, "hour": 0, "minute": 0, "remark": "pytest"},
            headers=headers,
        ).json()
        assert created["success"] is True
        auth_id = created["data"][0]["authId"]

        verify = client.post(
            "/api/client/v1/license/validate",
            json={"softwareId": software_id, "licenseKey": auth_id, "installationId": "PYTEST-MACHINE", "clientVersion": "1.0.0"},
        ).json()
        assert verify["success"] is True
        assert verify["data"]["status"] == "active"

        wrong_key = client.post(
            "/api/client/auth/verify",
            json={"softwareId": software_id, "instanceKey": "IK-WRONG", "authId": auth_id, "macid": "PYTEST-MACHINE"},
        ).json()
        assert wrong_key["success"] is False
        assert wrong_key["message"] == "实例密钥错误"

        events = client.post("/api/adm/message/event", json={"page": {"pageNum": 1, "limit": 10}, "keyword": "verify"}, headers=headers).json()
        assert events["success"] is True
        assert events["data"]["list"]

        unbound = client.post(
            "/api/client/auth/unbind",
            json={"softwareId": software_id, "instanceKey": instance_key, "authId": auth_id, "macid": "PYTEST-MACHINE"},
        ).json()
        assert unbound["success"] is True
        assert unbound["data"]["macid"] is None

        heartbeat = client.post(
            "/api/client/user/heartbeat",
            json={"softwareId": software_id, "instanceKey": instance_key, "customerId": "CU-DEMO", "macid": "PYTEST-MACHINE"},
        ).json()
        assert heartbeat["success"] is True
        assert heartbeat["data"]["serverTime"]

        logout = client.post("/api/client/user/logout", json={"softwareId": software_id, "instanceKey": instance_key, "customerId": "CU-DEMO"}).json()
        assert logout["success"] is True


def test_admin_page_interfaces_and_auth_search_filters():
    with TestClient(app) as client:
        headers = login(client)
        software = client.post("/api/adm/softwareSelect", json={}, headers=headers).json()["data"][0]
        software_id = software["softwareId"]

        created = client.post(
            "/api/adm/createAuth",
            json={"softwareId": software_id, "createNumber": 2, "day": 7, "remark": "search-batch"},
            headers=headers,
        ).json()
        assert created["success"] is True
        active_auth_id = created["data"][0]["authId"]
        unused_auth_id = created["data"][1]["authId"]

        verify = client.post(
            "/api/client/v1/license/validate",
            json={"softwareId": software_id, "licenseKey": active_auth_id, "installationId": "SEARCH-MACHINE", "clientVersion": software["version"]},
        ).json()
        assert verify["success"] is True

        page_calls = [
            ("/api/adm/user", {}),
            ("/api/adm/dataCount", {}),
            ("/api/adm/softwareList", {"page": {"pageNum": 1, "limit": 10}}),
            ("/api/adm/authList", {"page": {"pageNum": 1, "limit": 10}}),
            ("/api/adm/customerList", {"page": {"pageNum": 1, "limit": 10}}),
            ("/api/adm/cloudVariablesList", {}),
            ("/api/adm/blackWhiteList", {}),
            ("/api/adm/message/event", {"page": {"pageNum": 1, "limit": 10}}),
            ("/api/adm/message/list", {}),
            ("/api/adm/subUserList", {"page": {"pageNum": 1, "limit": 10}}),
        ]
        for path, body in page_calls:
            response = client.post(path, json=body, headers=headers)
            assert response.status_code == 200, path
            assert response.json()["success"] is True, path

        by_software = client.post(
            "/api/adm/authList",
            json={"softwareId": software_id, "page": {"pageNum": 1, "limit": 10}},
            headers=headers,
        ).json()
        assert by_software["success"] is True
        listed_ids = {row["authId"] for row in by_software["data"]["list"]}
        assert {active_auth_id, unused_auth_id}.issubset(listed_ids)

        by_status = client.post(
            "/api/adm/authList",
            json={"softwareId": software_id, "status": "active", "page": {"pageNum": 1, "limit": 10}},
            headers=headers,
        ).json()
        assert by_status["success"] is True
        assert active_auth_id in {row["authId"] for row in by_status["data"]["list"]}
        assert all(row["state"] == "active" for row in by_status["data"]["list"])

        by_keyword = client.post(
            "/api/adm/authList",
            json={"softwareId": software_id, "keyword": "SEARCH-MACHINE", "page": {"pageNum": 1, "limit": 10}},
            headers=headers,
        ).json()
        assert by_keyword["success"] is True
        assert [row["authId"] for row in by_keyword["data"]["list"]] == [active_auth_id]

        by_auth = client.post(
            "/api/adm/authList",
            json={"authId": unused_auth_id[-8:], "status": "unused", "page": {"pageNum": 1, "limit": 10}},
            headers=headers,
        ).json()
        assert by_auth["success"] is True
        assert [row["authId"] for row in by_auth["data"]["list"]] == [unused_auth_id]

        exported = client.post(
            "/api/adm/exportTable",
            json={"softwareId": software_id, "keyword": "SEARCH-MACHINE"},
            headers=headers,
        )
        assert exported.status_code == 200
        assert active_auth_id in exported.text
        assert unused_auth_id not in exported.text


def test_frontend_api_contract_mutation_routes():
    with TestClient(app) as client:
        registered = client.post(
            "/api/adm/register",
            json={"user": "contract_admin", "password": "contract123456", "email": "contract-admin@example.com"},
        ).json()
        assert registered["success"] is False
        assert "注册已关闭" in registered["message"]
        assert_ok(client.post("/api/adm/forgotPassword", json={"email": "admin@example.com"}), "/api/adm/forgotPassword")

        headers = login(client)
        software = assert_ok(client.post("/api/adm/softwareSelect", json={}, headers=headers), "/api/adm/softwareSelect")["data"][0]
        software_id = software["softwareId"]
        instance_key = software["instanceKey"]

        updated_user = assert_ok(
            client.post(
                "/api/adm/updateUserInfo",
                json={"nick": "Contract Admin", "email": "admin-contract@example.com", "qq": "10001"},
                headers=headers,
            ),
            "/api/adm/updateUserInfo",
        )
        assert updated_user["data"]["nick"] == "Contract Admin"
        assert_ok(client.post("/api/adm/clearFingerId", json={}, headers=headers), "/api/adm/clearFingerId")

        sent = assert_ok(client.post("/api/adm/message/send", json={"content": "contract message"}, headers=headers), "/api/adm/message/send")
        listed_messages = assert_ok(client.post("/api/adm/message/list", json={}, headers=headers), "/api/adm/message/list")
        assert sent["data"]["id"] in {row["id"] for row in listed_messages["data"]}

        created_software = assert_ok(
            client.post(
                "/api/adm/createSoftware",
                json={
                    "name": "contract-sw",
                    "version": "1.0.0",
                    "lowVersion": "0.9.0",
                    "force": True,
                    "notice": "initial notice",
                    "remark": "initial remark",
                    "url": "https://example.com/initial.zip",
                    "md5": "initial-md5",
                },
                headers=headers,
            ),
            "/api/adm/createSoftware",
        )
        created_software_id = created_software["data"]["softwareId"]
        assert created_software["data"]["lowVersion"] == "0.9.0"
        assert created_software["data"]["force"] is True
        assert created_software["data"]["notice"] == "initial notice"
        assert created_software["data"]["remark"] == "initial remark"
        assert created_software["data"]["url"] == "https://example.com/initial.zip"
        assert created_software["data"]["md5"] == "initial-md5"
        updated_software = assert_ok(
            client.post(
                "/api/adm/updateSoftware",
                json={
                    "softwareId": created_software_id,
                    "name": "contract-sw-renamed",
                    "version": "1.1.0",
                    "lowVersion": "1.0.0",
                    "force": True,
                    "notice": "contract notice",
                    "url": "https://example.com/app.zip",
                    "md5": "abcd",
                },
                headers=headers,
            ),
            "/api/adm/updateSoftware",
        )
        assert updated_software["data"]["version"] == "1.1.0"

        saved_vars = assert_ok(
            client.post(
                "/api/adm/saveCloudVariables",
                json={
                    "variables": [
                        {"key": "global_flag", "value": "on", "status": "y", "softwareId": ""},
                        {"key": "contract_flag", "value": "enabled", "status": "y", "softwareId": software_id},
                    ]
                },
                headers=headers,
            ),
            "/api/adm/saveCloudVariables",
        )
        assert saved_vars["success"] is True
        client_vars = assert_ok(client.post("/api/client/cloudVariables/list", json={"softwareId": software_id, "instanceKey": instance_key}), "/api/client/cloudVariables/list")
        assert {"global_flag", "contract_flag"}.issubset({row["key"] for row in client_vars["data"]})

        cards = assert_ok(
            client.post(
                "/api/adm/createAuth",
                json={"softwareId": software_id, "createNumber": 5, "day": 1, "bindCount": 2, "remark": "contract"},
                headers=headers,
            ),
            "/api/adm/createAuth",
        )["data"]
        editable_auth_id = cards[0]["authId"]
        delete_auth_id = cards[1]["authId"]
        batch_ids = [cards[2]["authId"], cards[3]["authId"]]
        activate_auth_id = cards[4]["authId"]

        edited = assert_ok(client.post("/api/adm/editAuth", json={"authId": editable_auth_id, "bindCount": 3}, headers=headers), "/api/adm/editAuth")
        assert edited["data"]["bindCount"] == 3
        remarked = assert_ok(
            client.post("/api/adm/updateAuthRemark", json={"authId": editable_auth_id, "remark": "contract remark"}, headers=headers),
            "/api/adm/updateAuthRemark",
        )
        assert remarked["data"]["remark"] == "contract remark"

        assert_ok(
            client.post("/api/client/v1/license/validate", json={"softwareId": software_id, "licenseKey": editable_auth_id, "installationId": "ADMIN-UNBIND", "clientVersion": software["version"]}),
            "/api/client/auth/verify",
        )
        unbound = assert_ok(
            client.post("/api/adm/commitUnBind", json={"authId": editable_auth_id, "macid": ""}, headers=headers),
            "/api/adm/commitUnBind",
        )
        assert unbound["data"]["macid"] is None

        activated = assert_ok(
            client.post("/api/client/auth/activate", json={"softwareId": software_id, "instanceKey": instance_key, "authId": activate_auth_id, "macid": "ACTIVATE-MACHINE"}),
            "/api/client/auth/activate",
        )
        assert activated["data"]["state"] == "active"

        assert_ok(client.post("/api/adm/delAuth", json={"authId": delete_auth_id}, headers=headers), "/api/adm/delAuth")
        assert_ok(client.post("/api/adm/batchDelAuth", json={"list": batch_ids}, headers=headers), "/api/adm/batchDelAuth")

        update = assert_ok(
            client.post("/api/client/software/checkUpdate", json={"softwareId": software_id, "instanceKey": instance_key, "version": "1.0.0", "macid": "CLIENT-MACHINE"}),
            "/api/client/software/checkUpdate",
        )
        assert update["data"]["softwareId"] == software_id

        email = "client-contract@example.com"
        customer = assert_ok(
            client.post(
                "/api/client/user/register",
                json={"softwareId": software_id, "instanceKey": instance_key, "email": email, "password": "client123456", "nickName": "Contract Client"},
            ),
            "/api/client/user/register",
        )
        customer_id = customer["data"]["customerId"]
        logged_in = assert_ok(
            client.post("/api/client/user/login", json={"softwareId": software_id, "instanceKey": instance_key, "email": email, "password": "client123456"}),
            "/api/client/user/login",
        )
        assert logged_in["data"]["customerId"] == customer_id
        customer_list = assert_ok(
            client.post("/api/adm/customerList", json={"email": email, "page": {"pageNum": 1, "limit": 10}}, headers=headers),
            "/api/adm/customerList",
        )
        assert customer_id in {row["customerId"] for row in customer_list["data"]["list"]}
        assert_ok(client.post("/api/adm/delCustomer", json={"customerId": customer_id}, headers=headers), "/api/adm/delCustomer")

        username = "contract_sub"
        sub_user = assert_ok(
            client.post(
                "/api/adm/createSubUser",
                json={
                    "user": username,
                    "password": "sub123456",
                    "email": "contract-sub@example.com",
                    "nick": "Contract Sub",
                    "role": "user",
                    "softwareIds": [software_id],
                },
                headers=headers,
            ),
            "/api/adm/createSubUser",
        )
        assert sub_user["data"]["user"] == username
        assert sub_user["data"]["role"] == "user"
        assert sub_user["data"]["permissionTypes"] == ["softView", "authCreate"]
        updated_sub = assert_ok(
            client.post(
                "/api/adm/updateSubUser",
                json={
                    "user": username,
                    "password": "sub654321",
                    "email": "contract-sub-updated@example.com",
                    "nick": "Contract Sub Updated",
                    "role": "user",
                    "softwareIds": [software_id],
                },
                headers=headers,
            ),
            "/api/adm/updateSubUser",
        )
        assert updated_sub["data"]["nick"] == "Contract Sub Updated"
        assert updated_sub["data"]["permissionTypes"] == ["softView", "authCreate"]
        assert_ok(client.post("/api/adm/deleteSubUser", json={"user": username}, headers=headers), "/api/adm/deleteSubUser")

        assert_ok(client.post("/api/adm/delSoftware", json={"softwareId": created_software_id}, headers=headers), "/api/adm/delSoftware")


def test_fixed_role_model_for_admin_and_user_login():
    with TestClient(app) as client:
        developer_headers = login(client)
        developer_software = assert_ok(client.post("/api/adm/softwareSelect", json={}, headers=developer_headers), "/api/adm/softwareSelect developer")["data"][0]
        developer_software_id = developer_software["softwareId"]

        manager = assert_ok(
            client.post(
                "/api/adm/createSubUser",
                json={
                    "user": "role_manager",
                    "password": "manager123456",
                    "email": "manager@example.com",
                    "nick": "Role Manager",
                    "role": "admin",
                },
                headers=developer_headers,
            ),
            "/api/adm/createSubUser admin",
        )
        assert manager["data"]["role"] == "admin"
        assert manager["data"]["roleLabel"] == "管理员"
        assert {"softView", "softCreate", "softEdit", "softDelete", "authCreate", "authUnbind", "eventView", "accountManage"}.issubset(manager["data"]["permissionTypes"])
        assert manager["data"]["softwareIds"] == ["*"]

        manager_login = login_payload(client, "role_manager", "manager123456")
        assert manager_login["data"]["user"] == "role_manager"
        assert manager_login["data"]["role"] == "admin"
        assert manager_login["data"]["roleLabel"] == "管理员"
        assert {"softView", "softCreate", "softEdit", "softDelete", "authCreate", "authUnbind", "eventView", "accountManage"}.issubset(manager_login["data"]["permissions"]["permissionTypes"])
        assert manager_login["data"]["permissions"]["softwareIds"] == ["*"]
        assert "accountToken" not in manager_login["data"]
        assert "openId" not in manager_login["data"]
        manager_headers = {"token": manager_login["data"]["token"]}

        manager_visible = assert_ok(
            client.post("/api/adm/softwareSelect", json={}, headers=manager_headers),
            "/api/adm/softwareSelect manager",
        )
        assert developer_software_id not in {row["softwareId"] for row in manager_visible["data"]}

        manager_software = assert_ok(
            client.post(
                "/api/adm/createSoftware",
                json={"name": "manager-sw", "version": "1.0.0"},
                headers=manager_headers,
            ),
            "/api/adm/createSoftware manager",
        )
        assert manager_software["data"]["softwareId"]
        manager_software_id = manager_software["data"]["softwareId"]

        manager_auth = assert_ok(
            client.post(
                "/api/adm/createAuth",
                json={"softwareId": manager_software_id, "createNumber": 1, "remark": "created-by-admin"},
                headers=manager_headers,
            ),
            "/api/adm/createAuth manager",
        )
        manager_auth_id = manager_auth["data"][0]["authId"]
        assert manager_auth["data"][0]["creatorUser"] == "role_manager"
        assert manager_auth["data"][0]["creatorRole"] == "admin"
        denied_admin_create = client.post(
            "/api/adm/createSubUser",
            json={"user": "blocked_admin", "password": "123456", "role": "admin"},
            headers=manager_headers,
        )
        assert denied_admin_create.status_code == 403
        denied_developer_create = client.post(
            "/api/adm/createSubUser",
            json={"user": "blocked_developer", "password": "123456", "role": "developer"},
            headers=manager_headers,
        )
        assert denied_developer_create.status_code == 403

        created_user = assert_ok(
            client.post(
                "/api/adm/createSubUser",
                json={
                    "user": "role_user",
                    "password": "user123456",
                    "email": "user@example.com",
                    "nick": "Role User",
                    "role": "user",
                    "softwareIds": [manager_software_id],
                },
                headers=manager_headers,
            ),
            "/api/adm/createSubUser user",
        )
        assert created_user["data"]["role"] == "user"
        assert created_user["data"]["roleLabel"] == "普通用户"
        assert created_user["data"]["permissionTypes"] == ["softView", "authCreate"]
        assert created_user["data"]["softwareIds"] == [manager_software_id]

        user_login = login_payload(client, "role_user", "user123456")
        assert user_login["data"]["user"] == "role_user"
        assert user_login["data"]["role"] == "user"
        assert user_login["data"]["roleLabel"] == "普通用户"
        assert user_login["data"]["isSubUser"] is True
        assert user_login["data"]["permissions"]["permissionTypes"] == ["softView", "authCreate"]
        assert "accountManage" not in user_login["data"]["permissions"]["permissionTypes"]
        assert "softCreate" not in user_login["data"]["permissions"]["permissionTypes"]
        assert "accountToken" not in user_login["data"]
        assert "openId" not in user_login["data"]
        user_headers = {"token": user_login["data"]["token"]}
        user_visible = assert_ok(
            client.post("/api/adm/softwareSelect", json={}, headers=user_headers),
            "/api/adm/softwareSelect role user",
        )
        assert [row["softwareId"] for row in user_visible["data"]] == [manager_software_id]

        user_auth = assert_ok(
            client.post(
                "/api/adm/createAuth",
                json={"softwareId": manager_software_id, "createNumber": 1, "remark": "created-by-role-user"},
                headers=user_headers,
            ),
            "/api/adm/createAuth role user",
        )
        assert user_auth["data"][0]["softwareId"] == manager_software_id
        assert user_auth["data"][0]["creatorUser"] == "role_user"
        assert user_auth["data"][0]["creatorRole"] == "user"
        manager_auth_list = assert_ok(
            client.post(
                "/api/adm/authList",
                json={"authId": user_auth["data"][0]["authId"], "page": {"pageNum": 1, "limit": 10}},
                headers=manager_headers,
            ),
            "/api/adm/authList manager sees user card",
        )
        assert [row["authId"] for row in manager_auth_list["data"]["list"]] == [user_auth["data"][0]["authId"]]
        assert manager_auth_list["data"]["list"][0]["creatorUser"] == "role_user"
        hidden_admin_auth = assert_ok(
            client.post(
                "/api/adm/authList",
                json={"authId": manager_auth_id, "page": {"pageNum": 1, "limit": 10}},
                headers=user_headers,
            ),
            "/api/adm/authList user cannot see admin card on same software",
        )
        assert hidden_admin_auth["data"]["list"] == []
        denied_user_software = client.post("/api/adm/createSoftware", json={"name": "blocked", "version": "1.0.0"}, headers=user_headers)
        assert denied_user_software.status_code == 403
        denied_user_account = client.post("/api/adm/createSubUser", json={"user": "blocked_user", "password": "123456"}, headers=user_headers)
        assert denied_user_account.status_code == 403


def test_sub_user_permissions_limit_access():
    with TestClient(app) as client:
        headers = login(client)
        software = client.post("/api/adm/softwareSelect", json={}, headers=headers).json()["data"][0]
        software_id = software["softwareId"]
        instance_key = software["instanceKey"]
        card = client.post(
            "/api/adm/createAuth",
            json={"softwareId": software_id, "createNumber": 1, "remark": "sub-permission"},
            headers=headers,
        ).json()["data"][0]
        username = "sub_pytest"

        client.post("/api/adm/deleteSubUser", json={"user": username}, headers=headers)
        created = client.post(
            "/api/adm/createSubUser",
            json={
                "user": username,
                "password": "sub123456",
                "email": "sub@example.com",
                "nick": "sub",
                "role": "user",
                "softwareIds": [software_id],
            },
            headers=headers,
        ).json()
        assert created["success"] is True
        assert created["data"]["role"] == "user"
        assert created["data"]["roleLabel"] == "普通用户"
        assert created["data"]["permissionTypes"] == ["softView", "authCreate"]
        assert created["data"]["softwareIds"] == [software_id]

        sub_login = login_payload(client, username, "sub123456")
        assert sub_login["success"] is True
        assert sub_login["data"]["user"] == username
        assert sub_login["data"]["role"] == "user"
        assert sub_login["data"]["roleLabel"] == "普通用户"
        assert sub_login["data"]["isSubUser"] is True
        assert sub_login["data"]["permissions"]["permissionTypes"] == ["softView", "authCreate"]
        assert sub_login["data"]["permissions"]["softwareIds"] == [software_id]
        assert "accountToken" not in sub_login["data"]
        assert "openId" not in sub_login["data"]
        sub_headers = {"token": sub_login["data"]["token"]}
        allowed = client.post("/api/adm/softwareList", json={"page": 1}, headers=sub_headers).json()
        assert allowed["success"] is True
        created_by_user = client.post(
            "/api/adm/createAuth",
            json={"softwareId": software_id, "createNumber": 1, "remark": "user-created"},
            headers=sub_headers,
        ).json()
        assert created_by_user["success"] is True

        profile = client.post("/api/adm/user", json={}, headers=sub_headers).json()
        assert profile["success"] is True
        assert profile["data"]["user"] == username
        assert profile["data"]["role"] == "user"
        assert profile["data"]["permissionTypes"] == ["softView", "authCreate"]
        assert "accountToken" not in profile["data"]
        assert "openId" not in profile["data"]

        updated_profile = client.post("/api/adm/updateUserInfo", json={"nick": "Sub Updated", "qq": "20001"}, headers=sub_headers).json()
        assert updated_profile["success"] is True
        assert updated_profile["data"]["nick"] == "Sub Updated"
        assert "accountToken" not in updated_profile["data"]

        denied = client.post("/api/adm/createSoftware", json={"name": "blocked", "version": "1.0.0"}, headers=sub_headers)
        assert denied.status_code == 403
        denied_delete = client.post("/api/adm/delAuth", json={"authId": card["authId"]}, headers=sub_headers)
        assert denied_delete.status_code == 403
        denied_export = client.post("/api/adm/exportTable", json={"softwareId": software_id}, headers=sub_headers)
        assert denied_export.status_code == 403
        denied_private_update = client.post("/api/adm/updateUserInfo", json={"openId": "open_blocked"}, headers=sub_headers)
        assert denied_private_update.status_code == 403
        denied_remark = client.post("/api/adm/updateAuthRemark", json={"authId": card["authId"], "remark": "blocked"}, headers=sub_headers)
        assert denied_remark.status_code == 403
        denied_assign = client.post("/api/adm/assignAuthToSubUser", json={"authIds": [card["authId"]], "subUserName": username}, headers=sub_headers)
        assert denied_assign.status_code == 403
        denied_events = client.post("/api/adm/message/event", json={"page": {"pageNum": 1, "limit": 10}}, headers=sub_headers)
        assert denied_events.status_code == 403
        denied_messages = client.post("/api/adm/message/list", json={}, headers=sub_headers)
        assert denied_messages.status_code == 403
        denied_send = client.post("/api/adm/message/send", json={"content": "blocked"}, headers=sub_headers)
        assert denied_send.status_code == 403
        denied_sub_users = client.post("/api/adm/subUserList", json={"page": {"pageNum": 1, "limit": 10}}, headers=sub_headers)
        assert denied_sub_users.status_code == 403
        denied_create_sub = client.post("/api/adm/createSubUser", json={"user": "blocked_sub", "password": "123456"}, headers=sub_headers)
        assert denied_create_sub.status_code == 403
        denied_gitcode = client.post("/api/adm/bindGitCode", json={"projectUrl": "https://gitcode.com/a/b", "token": "blocked"}, headers=sub_headers)
        assert denied_gitcode.status_code == 403


def test_blacklist_blocks_client_verify():
    with TestClient(app) as client:
        headers = login(client)
        software = client.post("/api/adm/softwareSelect", json={}, headers=headers).json()["data"][0]
        software_id = software["softwareId"]

        cards = client.post("/api/adm/createAuth", json={"softwareId": software_id, "createNumber": 1}, headers=headers).json()
        auth_id = cards["data"][0]["authId"]

        saved = client.post(
            "/api/adm/saveBlackWhiteList",
            json={"list": [{"type": "black", "value": "BAD-MACHINE", "remark": "test", "softwareId": software_id}]},
            headers=headers,
        ).json()
        assert saved["success"] is True

        blocked = client.post(
            "/api/client/v1/license/validate",
            json={"softwareId": software_id, "licenseKey": auth_id, "installationId": "BAD-MACHINE", "clientVersion": software["version"]},
        ).json()
        assert blocked["success"] is False
        assert "黑名单" in blocked["error"]["message"]


def test_python_sdk_config_file_and_state_helpers(tmp_path):
    from clients.python import KeyDeskApp, KeyDeskConfigError

    config_path = tmp_path / "keydesk-client.json"
    config_path.write_text(
        json.dumps(
            {
                "baseUrl": "http://127.0.0.1:8080",
                "softwareId": "SWSDK",
                "version": "2.0.0",
                "licenseFile": "state/license.json",
                "deviceFile": "state/device.txt",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self):
            self.calls = []

        def validate_license(self, software_id, auth_id, macid, version):
            self.calls.append(("validate_license", software_id, auth_id, macid, version))
            return {"data": {"status": "active", "expiresAt": None, "serverTime": "2026-06-07T00:00:00Z"}}

    app = KeyDeskApp.from_file(config_path)
    fake = FakeClient()
    app.client = fake

    assert app.config.project_name == "KeyDesk App"
    assert app.config.software_id == "SWSDK"
    assert app.config.instance_key == ""
    assert app.macid.startswith("INST-")

    card = app.verify("KMSDK")
    assert card["status"] == "active"
    assert app.saved_auth_id() == "KMSDK"
    assert json.loads((tmp_path / "state/license.json").read_text(encoding="utf-8"))["licenseKey"] == "KMSDK"
    assert ("validate_license", "SWSDK", "KMSDK", app.macid, "2.0.0") in fake.calls

    with pytest.raises(KeyDeskConfigError):
        KeyDeskApp.from_dict({"baseUrl": "http://127.0.0.1:8080", "softwareId": "SWBAD"})


def test_python_sdk_only_retries_retryable_errors(tmp_path, monkeypatch):
    from clients.python import KeyDeskApp, KeyDeskNetworkError, LicenseError

    app = KeyDeskApp.from_dict(
        {
            "baseUrl": "https://card.example.com",
            "softwareId": "SWSDK",
            "version": "1.0.0",
            "authId": "KM-SECRET-VALUE",
            "deviceFile": str(tmp_path / "device"),
            "licenseFile": str(tmp_path / "license.json"),
            "maxRetries": 2,
        }
    )

    class RetryClient:
        def __init__(self):
            self.calls = 0

        def validate_license(self, *args):
            self.calls += 1
            if self.calls < 3:
                raise KeyDeskNetworkError("timeout", error_code="NETWORK_ERROR", retryable=True)
            return {"data": {"status": "active", "serverTime": "2026-09-10T00:00:00Z"}}

    retry_client = RetryClient()
    app.client = retry_client
    monkeypatch.setattr("clients.python.keydesk_client.time.sleep", lambda _: None)
    assert app.require_license()["status"] == "active"
    assert retry_client.calls == 3

    class RevokedClient:
        def __init__(self):
            self.calls = 0

        def validate_license(self, *args):
            self.calls += 1
            raise LicenseError("revoked", error_code="LICENSE_REVOKED", http_status=403, retryable=False)

    revoked_client = RevokedClient()
    app.client = revoked_client
    with pytest.raises(LicenseError) as exc_info:
        app.require_license()
    assert exc_info.value.error_code == "LICENSE_REVOKED"
    assert exc_info.value.http_status == 403
    assert revoked_client.calls == 1


def test_python_sdk_preserves_transport_error_metadata(monkeypatch):
    from clients.python import KeyDeskClient, KeyDeskError, KeyDeskNetworkError

    client = KeyDeskClient("https://card.example.com")

    class InvalidResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"not-json"

    monkeypatch.setattr("clients.python.keydesk_client.urllib.request.urlopen", lambda *args, **kwargs: InvalidResponse())
    with pytest.raises(KeyDeskNetworkError) as invalid:
        client.validate_license("SW", "KM-SENSITIVE", "INST", "1.0.0")
    assert invalid.value.error_code == "INVALID_RESPONSE"
    assert invalid.value.http_status == 200
    assert "KM-SENSITIVE" not in str(invalid.value)

    http_error = urllib.error.HTTPError(
        "https://card.example.com",
        500,
        "server error",
        {},
        io.BytesIO(b'{"success":false,"error":{"code":"SERVER_ERROR","message":"temporary","retryable":true}}'),
    )
    monkeypatch.setattr("clients.python.keydesk_client.urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(http_error))
    with pytest.raises(KeyDeskError) as server_error:
        client.validate_license("SW", "KM-SENSITIVE", "INST", "1.0.0")
    assert server_error.value.error_code == "SERVER_ERROR"
    assert server_error.value.http_status == 500
    assert server_error.value.retryable is True

    network_error = urllib.error.URLError("TLS handshake failed")
    monkeypatch.setattr("clients.python.keydesk_client.urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(network_error))
    with pytest.raises(KeyDeskNetworkError) as transport:
        client.validate_license("SW", "KM-SENSITIVE", "INST", "1.0.0")
    assert transport.value.error_code == "NETWORK_ERROR"
    assert transport.value.retryable is True
    assert transport.value.__cause__ is network_error


def test_strict_legacy_auth_and_v1_license_state_machine():
    with TestClient(app) as client:
        headers = login(client)
        software = assert_ok(client.post("/api/adm/softwareSelect", json={}, headers=headers))["data"][0]
        software_id = software["softwareId"]
        instance_key = software["instanceKey"]
        cards = assert_ok(
            client.post(
                "/api/adm/createAuth",
                json={"softwareId": software_id, "createNumber": 3, "day": 1, "bindCount": 5},
                headers=headers,
            )
        )["data"]

        legacy_payload = {"softwareId": software_id, "authId": cards[0]["authId"], "macid": "INST-A"}
        for key in (None, "", "IK-WRONG"):
            payload = dict(legacy_payload)
            if key is not None:
                payload["instanceKey"] = key
            response = client.post("/api/client/auth/activate", json=payload)
            assert response.status_code == 200
            assert response.json()["error"]["code"] == "INSTANCE_KEY_INVALID"

        unused_verify = client.post(
            "/api/client/auth/verify",
            json={**legacy_payload, "instanceKey": instance_key},
        ).json()
        assert unused_verify["error"]["code"] == "LICENSE_UNUSED"

        activated = assert_ok(
            client.post(
                "/api/client/v1/license/validate",
                json={
                    "softwareId": software_id,
                    "licenseKey": cards[0]["authId"],
                    "installationId": "INST-A",
                    "clientVersion": software["version"],
                },
            )
        )
        assert activated["data"]["requiresOnline"] is True
        assert activated["data"]["offlineGraceSeconds"] == 0
        assert activated["data"]["leaseToken"] is None

        mismatch = client.post(
            "/api/client/v1/license/validate",
            json={
                "softwareId": software_id,
                "licenseKey": cards[0]["authId"],
                "installationId": "INST-B",
                "clientVersion": software["version"],
            },
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "LICENSE_DEVICE_MISMATCH"
        with SessionLocal() as db:
            row = db.query(AuthCard).filter(AuthCard.auth_id == cards[0]["authId"]).one()
            assert row.macid == "INST-A"
            assert row.bind_used == 0
            disabled = db.query(AuthCard).filter(AuthCard.auth_id == cards[1]["authId"]).one()
            disabled.status = "disabled"
            expired = db.query(AuthCard).filter(AuthCard.auth_id == cards[2]["authId"]).one()
            expired.end_time = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

        audit = assert_ok(
            client.post(
                "/api/adm/message/event",
                json={"keyword": cards[0]["authId"], "page": {"pageNum": 1, "limit": 100}},
                headers=headers,
            )
        )
        assert audit["data"]["list"] == []

        revoked = assert_ok(client.post("/api/adm/revokeAuth", json={"authId": cards[0]["authId"]}, headers=headers))
        assert revoked["data"]["state"] == "revoked"
        revoked_validate = client.post(
            "/api/client/v1/license/validate",
            json={"softwareId": software_id, "licenseKey": cards[0]["authId"], "installationId": "INST-A", "clientVersion": software["version"]},
        )
        assert revoked_validate.status_code == 403
        assert revoked_validate.json()["error"]["code"] == "LICENSE_REVOKED"

        rotated = assert_ok(client.post("/api/adm/rotateInstanceKey", json={"softwareId": software_id}, headers=headers))["data"]
        assert rotated["instanceKey"] != instance_key
        old_key = client.post(
            "/api/client/software/checkUpdate",
            json={"softwareId": software_id, "instanceKey": instance_key, "version": software["version"]},
        ).json()
        assert old_key["error"]["code"] == "INSTANCE_KEY_INVALID"
        assert_ok(
            client.post(
                "/api/client/software/checkUpdate",
                json={"softwareId": software_id, "instanceKey": rotated["instanceKey"], "version": software["version"]},
            )
        )

        for auth_id, code in ((cards[1]["authId"], "LICENSE_REVOKED"), (cards[2]["authId"], "LICENSE_EXPIRED")):
            response = client.post(
                "/api/client/v1/license/validate",
                json={"softwareId": software_id, "licenseKey": auth_id, "installationId": "INST-C", "clientVersion": software["version"]},
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == code

        missing_installation = client.post(
            "/api/client/v1/license/validate",
            json={"softwareId": software_id, "licenseKey": cards[0]["authId"], "installationId": "", "clientVersion": software["version"]},
        )
        assert missing_installation.status_code == 422
        assert missing_installation.json()["error"]["code"] == "INVALID_REQUEST"


def test_admin_tenants_are_isolated_for_instances_and_cards():
    with TestClient(app) as client:
        developer_headers = login(client)
        for name in ("tenant_a", "tenant_b"):
            assert_ok(
                client.post(
                    "/api/adm/createSubUser",
                    json={"user": name, "password": f"{name}-password", "email": f"{name}@example.com", "role": "admin"},
                    headers=developer_headers,
                )
            )
        a_headers = {"token": login_payload(client, "tenant_a", "tenant_a-password")["data"]["token"]}
        b_headers = {"token": login_payload(client, "tenant_b", "tenant_b-password")["data"]["token"]}
        a_soft = assert_ok(client.post("/api/adm/createSoftware", json={"name": "A", "version": "1.0.0"}, headers=a_headers))["data"]
        b_soft = assert_ok(client.post("/api/adm/createSoftware", json={"name": "B", "version": "1.0.0"}, headers=b_headers))["data"]
        b_card = assert_ok(
            client.post("/api/adm/createAuth", json={"softwareId": b_soft["softwareId"], "createNumber": 1}, headers=b_headers)
        )["data"][0]

        a_visible = assert_ok(client.post("/api/adm/softwareSelect", json={}, headers=a_headers))["data"]
        assert {row["softwareId"] for row in a_visible} == {a_soft["softwareId"]}
        denied_update = client.post(
            "/api/adm/updateSoftware",
            json={"softwareId": b_soft["softwareId"], "name": "stolen"},
            headers=a_headers,
        )
        assert denied_update.status_code == 404
        denied_delete = client.post("/api/adm/delSoftware", json={"softwareId": b_soft["softwareId"]}, headers=a_headers)
        assert denied_delete.status_code == 404
        denied_card_create = client.post(
            "/api/adm/createAuth",
            json={"softwareId": b_soft["softwareId"], "createNumber": 1},
            headers=a_headers,
        )
        assert denied_card_create.status_code == 404
        a_cards = assert_ok(client.post("/api/adm/authList", json={}, headers=a_headers))["data"]["list"]
        assert b_card["authId"] not in {row["authId"] for row in a_cards}


def test_password_reset_token_is_one_time_and_revokes_existing_sessions():
    with TestClient(app) as client:
        old_headers = login(client)
        existing = assert_ok(client.post("/api/adm/forgotPassword", json={"email": "admin@example.com"}))
        missing = assert_ok(client.post("/api/adm/forgotPassword", json={"email": "nobody@example.com"}))
        assert existing["message"] == missing["message"]
        token = existing["data"]["resetToken"]
        assert token

        valid = assert_ok(client.post("/api/adm/rePasswordInfo", json={"token": token}))
        assert valid["data"] == {"valid": True}
        forged = client.post("/api/adm/resetUserPassword", json={"token": "forged", "password": "new-password-123"}).json()
        assert forged["error"]["code"] == "RESET_TOKEN_INVALID"
        reset = assert_ok(client.post("/api/adm/resetUserPassword", json={"token": token, "password": "new-password-123"}))
        assert reset["success"] is True
        replay = client.post("/api/adm/resetUserPassword", json={"token": token, "password": "another-password-123"}).json()
        assert replay["error"]["code"] == "RESET_TOKEN_INVALID"
        assert client.post("/api/adm/user", json={}, headers=old_headers).status_code == 401
        login_payload(client, "admin", "new-password-123")

        expired_request = assert_ok(client.post("/api/adm/forgotPassword", json={"email": "admin@example.com"}))
        expired_token = expired_request["data"]["resetToken"]
        with SessionLocal() as db:
            row = db.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None)).one()
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        expired = client.post("/api/adm/resetUserPassword", json={"token": expired_token, "password": "expired-password-123"}).json()
        assert expired["error"]["code"] == "RESET_TOKEN_INVALID"


def test_concurrent_first_bind_has_one_winning_installation():
    with TestClient(app) as client:
        headers = login(client)
        software = assert_ok(client.post("/api/adm/softwareSelect", json={}, headers=headers))["data"][0]
        card = assert_ok(
            client.post("/api/adm/createAuth", json={"softwareId": software["softwareId"], "createNumber": 1}, headers=headers)
        )["data"][0]

        def validate(index: int):
            return client.post(
                "/api/client/v1/license/validate",
                json={
                    "softwareId": software["softwareId"],
                    "licenseKey": card["authId"],
                    "installationId": f"INST-CONCURRENT-{index}",
                    "clientVersion": software["version"],
                },
            )

        with ThreadPoolExecutor(max_workers=20) as pool:
            responses = list(pool.map(validate, range(100)))

        successes = [response for response in responses if response.status_code == 200 and response.json().get("success")]
        assert len(successes) == 1
        failures = [response for response in responses if response not in successes]
        assert all(response.status_code == 409 for response in failures)
        assert all(response.json()["error"]["code"] == "LICENSE_DEVICE_MISMATCH" for response in failures)


def test_health_metadata_and_downloadable_minimal_sdk_package():
    with TestClient(app) as client:
        health = assert_ok(client.get("/health"))
        assert health["data"]["schemaVersion"] == "20260910_01"
        assert health["data"]["protocolVersion"] == "v1"
        assert "secret" not in json.dumps(health).lower()

        headers = login(client)
        software = assert_ok(client.post("/api/adm/softwareSelect", json={}, headers=headers))["data"][0]
        package = client.post("/api/adm/clientPackage", json={"softwareId": software["softwareId"]}, headers=headers)
        assert package.status_code == 200
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            assert set(archive.namelist()) == {"keydesk.py", "keydesk.json", "example.py", "smoke_test.py", "README.txt"}
            config = json.loads(archive.read("keydesk.json"))
            assert config == {
                "baseUrl": "http://127.0.0.1:8080",
                "softwareId": software["softwareId"],
                "version": software["version"],
            }
            assert software["instanceKey"] not in archive.read("keydesk.json").decode()


def test_production_rejects_default_secrets():
    insecure = replace(
        get_settings(),
        environment="production",
        public_base_url="http://127.0.0.1:8080",
        secret_key="change-me-in-production",
        default_admin_password="admin123456",
        database_url="mysql+pymysql://card_user:card_password@mysql/card_system",
    )
    with pytest.raises(RuntimeError, match="生产配置不安全"):
        validate_production_settings(insecure)

    secure = replace(
        insecure,
        public_base_url="https://card.example.com",
        secret_key="a" * 64,
        default_admin_password="unique-admin-password",
        database_url="mysql+pymysql://card_user:unique-db-password@mysql/card_system",
        allow_dev_reset_link=False,
    )
    validate_production_settings(secure)
