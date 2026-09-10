from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .config import get_settings
from .models import AdminUser, AuthCard, BlackWhiteItem, CloudVariable, Customer, EventLog, Message, SoftwareInstance
from .security import hash_password, new_token_value
from .utils import random_code


def seed_database(db: Session) -> None:
    settings = get_settings()
    admin = db.query(AdminUser).filter(AdminUser.user == settings.default_admin_user).first()
    if not admin:
        admin = AdminUser(
            user=settings.default_admin_user,
            password_hash=hash_password(settings.default_admin_password),
            email=settings.default_admin_email,
            nick="系统管理员",
            role="developer",
            account_token=new_token_value("acct_"),
            open_id=new_token_value("open_"),
            permission_types="[]",
            software_ids='["*"]',
        )
        db.add(admin)
        db.flush()
    else:
        admin.role = "developer"
        admin.software_ids = '["*"]'

    if db.query(SoftwareInstance).filter(SoftwareInstance.owner_id == admin.id).count() == 0:
        soft = SoftwareInstance(
            owner_id=admin.id,
            name="演示软件",
            version="1.0.0",
            low_version="0.9.0",
            software_id=random_code("SW", 10),
            instance_key=random_code("IK", 32),
            force=False,
            remark="默认演示实例",
            url="https://example.com/download/demo.zip",
            notice="欢迎使用卡密系统。",
            md5="",
            visit=12,
            lasttime=datetime.utcnow(),
        )
        db.add(soft)
        db.flush()

        cards = [
            AuthCard(
                owner_id=admin.id,
                software_id=soft.software_id,
                auth_id=random_code("KM", 18),
                creator_id=admin.id,
                creator_user=admin.user,
                creator_role=admin.role,
                day=30,
                remark="30 天测试卡",
            ),
            AuthCard(
                owner_id=admin.id,
                software_id=soft.software_id,
                auth_id=random_code("KM", 18),
                status="active",
                macid="DEMO-MACHINE",
                creator_id=admin.id,
                creator_user=admin.user,
                creator_role=admin.role,
                day=0,
                end_time=None,
                activated_at=datetime.utcnow(),
                remark="永久演示卡",
            ),
        ]
        db.add_all(cards)
        db.add(
            Customer(
                owner_id=admin.id,
                customer_id=random_code("CU", 12),
                email="demo@example.com",
                password_hash=hash_password("demo123456"),
                nick_name="演示用户",
                keys=json.dumps({soft.name: "永久有效"}, ensure_ascii=False),
            )
        )
        db.add(CloudVariable(owner_id=admin.id, key="api_host", value="https://api.example.com", status="y", software_id=""))
        db.add(CloudVariable(owner_id=admin.id, key="feature_x", value="enabled", status="y", software_id=soft.software_id))
        db.add(BlackWhiteItem(owner_id=admin.id, type="black", value="BLOCKED-MACHINE", remark="演示黑名单", software_id=soft.software_id))
        for idx in range(6):
            db.add(
                EventLog(
                    owner_id=admin.id,
                    type="api",
                    keyword="verify",
                    software_id=soft.software_id,
                    auth_id=f"last4:{cards[0].auth_id[-4:]}",
                    macid=f"DEMO-{idx}",
                    result="success",
                    message="演示验证日志",
                    created_at=datetime.utcnow() - timedelta(hours=idx),
                )
            )
        db.add(Message(owner_id=admin.id, content="系统初始化完成。"))
    db.commit()
