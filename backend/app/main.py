from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, inspect, or_, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db
from .models import AdminUser, AuthCard, BlackWhiteItem, CloudVariable, Customer, EventLog, Message, SoftwareInstance
from .security import (
    create_token,
    current_user,
    hash_password,
    has_permission,
    new_token_value,
    normalize_role,
    owner_id_for,
    permission_list,
    require_permission,
    role_permissions,
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_USER,
    software_scope,
    verify_password,
)
from .seed import seed_database
from .serializers import (
    auth_dict,
    black_white_dict,
    cloud_var_dict,
    customer_dict,
    event_dict,
    message_dict,
    software_dict,
    user_dict,
)
from .utils import fail, ok, paged, parse_time_range, random_code


app = FastAPI(title="Card System API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    with SessionLocal() as db:
        seed_database(db)


class Body(dict):
    pass


class AnyBody(BaseModel):
    model_config = {"extra": "allow"}


def body_dict(body: AnyBody | None) -> dict[str, Any]:
    return body.model_dump() if body else {}


def migrate_schema() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("admin_users")}
    if "role" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE admin_users ADD COLUMN role VARCHAR(30)"))
            conn.execute(text("UPDATE admin_users SET role = 'admin' WHERE parent_id IS NULL"))
            conn.execute(text("UPDATE admin_users SET role = 'user' WHERE parent_id IS NOT NULL"))
    else:
        with engine.begin() as conn:
            conn.execute(text("UPDATE admin_users SET role = 'admin' WHERE (role IS NULL OR role = '') AND parent_id IS NULL"))
            conn.execute(text("UPDATE admin_users SET role = 'user' WHERE (role IS NULL OR role = '') AND parent_id IS NOT NULL"))
    auth_columns = {column["name"] for column in inspect(engine).get_columns("auth_cards")}
    with engine.begin() as conn:
        if "creator_id" not in auth_columns:
            conn.execute(text("ALTER TABLE auth_cards ADD COLUMN creator_id INTEGER"))
        if "creator_user" not in auth_columns:
            conn.execute(text("ALTER TABLE auth_cards ADD COLUMN creator_user VARCHAR(80) DEFAULT ''"))
        if "creator_role" not in auth_columns:
            conn.execute(text("ALTER TABLE auth_cards ADD COLUMN creator_role VARCHAR(30) DEFAULT ''"))
        conn.execute(text("UPDATE auth_cards SET creator_id = owner_id WHERE creator_id IS NULL"))
        conn.execute(
            text(
                """
                UPDATE auth_cards
                SET creator_user = COALESCE((SELECT admin_users.user FROM admin_users WHERE admin_users.id = auth_cards.creator_id), '')
                WHERE creator_user IS NULL OR creator_user = ''
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE auth_cards
                SET creator_role = COALESCE((SELECT admin_users.role FROM admin_users WHERE admin_users.id = auth_cards.creator_id), 'user')
                WHERE creator_role IS NULL OR creator_role = ''
                """
            )
        )


def is_developer(user: AdminUser) -> bool:
    return normalize_role(getattr(user, "role", ROLE_USER)) == ROLE_DEVELOPER


def ensure_developer(user: AdminUser) -> None:
    if not is_developer(user):
        raise HTTPException(status_code=403, detail="您没有访问权限")


def manageable_user_query(db: Session, user: AdminUser):
    role = normalize_role(user.role)
    if role == ROLE_DEVELOPER:
        return db.query(AdminUser).filter(AdminUser.id != user.id)
    if role == ROLE_ADMIN:
        return db.query(AdminUser).filter(AdminUser.parent_id == user.id)
    raise HTTPException(status_code=403, detail="您没有访问权限")


def assert_assignable_role(actor: AdminUser, role: str) -> None:
    actor_role = normalize_role(actor.role)
    if actor_role == ROLE_DEVELOPER:
        return
    if actor_role == ROLE_ADMIN and role == ROLE_USER:
        return
    raise HTTPException(status_code=403, detail="您没有访问权限")


def parent_id_for_role(actor: AdminUser, role: str, current_parent_id: int | None = None) -> int | None:
    if role in (ROLE_DEVELOPER, ROLE_ADMIN):
        return None
    return current_parent_id or actor.id


def normalize_software_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def add_event(
    db: Session,
    owner_id: int | None,
    type_: str,
    keyword: str,
    message: str,
    request: Request | None = None,
    **kwargs,
) -> None:
    db.add(
        EventLog(
            owner_id=owner_id,
            type=type_,
            keyword=keyword,
            message=message,
            ip=request.client.host if request and request.client else None,
            result=kwargs.pop("result", "success"),
            software_id=kwargs.pop("software_id", None),
            auth_id=kwargs.pop("auth_id", None),
            customer_id=kwargs.pop("customer_id", None),
            macid=kwargs.pop("macid", None),
        )
    )


def visible_software_query(db: Session, user: AdminUser):
    q = db.query(SoftwareInstance)
    role = normalize_role(user.role)
    if role in (ROLE_DEVELOPER, ROLE_ADMIN):
        return q
    scope = software_scope(user)
    if "*" in scope:
        return q.filter(SoftwareInstance.owner_id == owner_id_for(user))
    return q.filter(SoftwareInstance.software_id.in_(scope or [""]))


def visible_software_ids(db: Session, user: AdminUser) -> list[str]:
    return [row.software_id for row in visible_software_query(db, user).all()]


def visible_auth_query(db: Session, user: AdminUser):
    ids = visible_software_ids(db, user)
    q = db.query(AuthCard).filter(AuthCard.software_id.in_(ids or [""]))
    if normalize_role(user.role) == ROLE_USER:
        q = q.filter(AuthCard.creator_id == user.id)
    return q


def get_software_or_404(db: Session, user: AdminUser, software_id: str) -> SoftwareInstance:
    row = visible_software_query(db, user).filter(SoftwareInstance.software_id == software_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="实例不存在")
    return row


def software_owner_by_id(db: Session, software_id: str) -> int | None:
    row = db.query(SoftwareInstance).filter(SoftwareInstance.software_id == software_id).first()
    return row.owner_id if row else None


AUTH_STATUS_ALIASES = {
    True: "active",
    False: "unused",
    1: "active",
    2: "unused",
    "1": "active",
    "2": "unused",
    "true": "active",
    "false": "unused",
    "active": "active",
    "unused": "unused",
    "expired": "expired",
    "disabled": "disabled",
}


def text_value(value: Any) -> str:
    return str(value or "").strip()


def normalize_auth_status(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return AUTH_STATUS_ALIASES.get(value.strip().lower())
    return AUTH_STATUS_ALIASES.get(value)


def apply_auth_filters(query, data: dict[str, Any]):
    software_id = text_value(data.get("softwareId"))
    auth_id = text_value(data.get("authId"))
    macid = text_value(data.get("macid"))
    keyword = text_value(data.get("keyword"))
    status = normalize_auth_status(data.get("status"))

    if software_id:
        query = query.filter(AuthCard.software_id == software_id)
    if auth_id:
        query = query.filter(AuthCard.auth_id.contains(auth_id))
    if macid:
        query = query.filter(AuthCard.macid.contains(macid))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                AuthCard.auth_id.like(like),
                AuthCard.software_id.like(like),
                AuthCard.macid.like(like),
                AuthCard.remark.like(like),
                AuthCard.assigned_sub_user.like(like),
            )
        )
    if status:
        query = query.filter(AuthCard.status == status)
    return query


@app.get("/health")
def health():
    return ok({"status": "ok"})


@app.post("/api/adm/login")
def login(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    user = db.query(AdminUser).filter(AdminUser.user == data.get("user", "")).first()
    if not user or not verify_password(str(data.get("password", "")), user.password_hash):
        return fail("账号或密码错误")
    if data.get("fingerId"):
        user.finger_id = str(data["fingerId"])
    user.last_login = datetime.utcnow()
    token = create_token(user.user)
    add_event(db, owner_id_for(user), "login", user.user, "后台登录成功", request, result="success")
    db.commit()
    res = user_dict(user, include_private=is_developer(user))
    res.update({"token": token, "isSubUser": bool(user.parent_id), "permissions": {"permissionTypes": permission_list(user), "softwareIds": software_scope(user)}})
    return ok(res)


@app.post("/api/adm/fingerLogin")
def finger_login(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    user = db.query(AdminUser).filter(AdminUser.user == data.get("user", ""), AdminUser.finger_id == data.get("fingerId", "")).first()
    if not user:
        return fail("免密码登录失败")
    token = create_token(user.user)
    add_event(db, owner_id_for(user), "login", user.user, "免密码登录成功", request)
    db.commit()
    res = user_dict(user, include_private=is_developer(user))
    res.update({"token": token, "isSubUser": bool(user.parent_id), "permissions": {"permissionTypes": permission_list(user), "softwareIds": software_scope(user)}})
    return ok(res)


@app.post("/api/adm/register")
def register(body: AnyBody, db: Session = Depends(get_db)):
    return fail("后台注册已关闭，请联系超级管理员创建账号")


@app.post("/api/adm/forgotPassword")
def forgot_password(body: AnyBody, db: Session = Depends(get_db)):
    data = body_dict(body)
    user = db.query(AdminUser).filter(AdminUser.email == data.get("email", "")).first()
    if not user:
        return fail("邮箱不存在")
    reset_token = create_token(f"reset:{user.user}", expires_minutes=30)
    return ok({"resetToken": reset_token}, "发送成功,请查收邮件")


@app.post("/api/adm/resetUserPassword")
def reset_user_password(body: AnyBody, db: Session = Depends(get_db)):
    data = body_dict(body)
    user = db.query(AdminUser).filter(or_(AdminUser.email == data.get("email", ""), AdminUser.user == data.get("user", ""))).first()
    if not user:
        return fail("用户不存在")
    if not data.get("password"):
        return fail("新密码不能为空")
    user.password_hash = hash_password(data["password"])
    db.commit()
    return ok()


@app.post("/api/adm/rePasswordInfo")
def re_password_info(body: AnyBody):
    return ok({"valid": True, "token": body_dict(body).get("token")})


@app.post("/api/adm/user")
def adm_user(user: AdminUser = Depends(current_user)):
    return ok(user_dict(user, include_private=is_developer(user)))


@app.post("/api/adm/updateUserInfo")
def update_user_info(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    data = body_dict(body)
    if any(field in data for field in ("accountToken", "openId")) and not is_developer(user):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    for field, attr in [("email", "email"), ("nick", "nick"), ("qq", "qq"), ("accountToken", "account_token"), ("openId", "open_id")]:
        if field in data and data[field] is not None:
            setattr(user, attr, str(data[field]))
    if data.get("password"):
        user.password_hash = hash_password(data["password"])
    db.commit()
    return ok(user_dict(user, include_private=is_developer(user)))


@app.post("/api/adm/clearFingerId")
def clear_finger(db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    user.finger_id = None
    db.commit()
    return ok()


@app.post("/api/adm/user-config")
def user_config(user: AdminUser = Depends(current_user)):
    return ok(
        {
            "gitcodeProjectUrl": getattr(user, "gitcode_project_url", None),
            "gitcodeToken": None,
            "gitcodeName": None,
            "gitcodeRepo": None,
        }
    )


@app.post("/api/adm/bindGitCode")
def bind_gitcode(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softEdit"))):
    data = body_dict(body)
    project_url = str(data.get("projectUrl") or "")
    token = str(data.get("token") or "")
    if "gitcode.com" not in project_url or "/" not in project_url:
        return fail("请输入正确的项目地址")
    rows = db.query(SoftwareInstance).filter(SoftwareInstance.owner_id == owner_id_for(user)).all()
    parts = project_url.rstrip("/").split("/")
    for row in rows:
        row.gitcode_project_url = project_url
        row.gitcode_token = token
        row.gitcode_name = parts[-2] if len(parts) >= 2 else None
        row.gitcode_repo = parts[-1] if parts else None
    db.commit()
    return ok()


@app.post("/api/adm/softwareList")
def software_list(body: AnyBody, user: AdminUser = Depends(require_permission("softView")), db: Session = Depends(get_db)):
    data = body_dict(body)
    q = visible_software_query(db, user).order_by(SoftwareInstance.created_at.desc())
    if data.get("softwareName"):
        q = q.filter(SoftwareInstance.name.contains(data["softwareName"]))
    if data.get("softwareId"):
        q = q.filter(SoftwareInstance.software_id.contains(data["softwareId"]))
    return ok(paged(q, data.get("page"), software_dict))


@app.post("/api/adm/softwareSelect")
def software_select(user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = visible_software_query(db, user).order_by(SoftwareInstance.created_at.desc()).all()
    return ok([software_dict(row) for row in rows])


@app.post("/api/adm/createSoftware")
def create_software(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softCreate"))):
    data = body_dict(body)
    if not data.get("name") or not data.get("version"):
        return fail("请输入信息")
    if "|" in data["name"]:
        return fail("请不要使用关键字符 |")
    row = SoftwareInstance(
        owner_id=owner_id_for(user),
        name=data["name"],
        version=data["version"],
        software_id=random_code("SW", 12),
        low_version=data.get("lowVersion") or None,
        force=bool(data.get("force")),
        remark=str(data.get("remark") or ""),
        url=data.get("url") or None,
        notice=str(data.get("notice") or ""),
        md5=data.get("md5") or None,
    )
    db.add(row)
    db.commit()
    return ok(software_dict(row), "创建成功")


@app.post("/api/adm/updateSoftware")
def update_software(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softEdit"))):
    data = body_dict(body)
    row = get_software_or_404(db, user, data.get("softwareId", ""))
    mapping = {
        "name": "name",
        "version": "version",
        "lowVersion": "low_version",
        "force": "force",
        "remark": "remark",
        "url": "url",
        "notice": "notice",
        "md5": "md5",
    }
    for key, attr in mapping.items():
        if key in data:
            setattr(row, attr, data[key])
    row.updated_at = datetime.utcnow()
    db.commit()
    return ok(software_dict(row))


@app.post("/api/adm/delSoftware")
def del_software(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softDelete"))):
    data = body_dict(body)
    row = get_software_or_404(db, user, data.get("softwareId", ""))
    db.query(AuthCard).filter(AuthCard.software_id == row.software_id).delete()
    db.query(CloudVariable).filter(CloudVariable.owner_id == row.owner_id, CloudVariable.software_id == row.software_id).delete()
    db.query(BlackWhiteItem).filter(BlackWhiteItem.owner_id == row.owner_id, BlackWhiteItem.software_id == row.software_id).delete()
    db.delete(row)
    db.commit()
    return ok()


@app.post("/api/adm/authList")
def auth_list(body: AnyBody, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    if not any(has_permission(user, code) for code in ("authCreate", "authDelete", "authExport", "authUnbind")):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    data = body_dict(body)
    q = visible_auth_query(db, user).order_by(AuthCard.created_at.desc())
    q = apply_auth_filters(q, data)
    return ok(paged(q, data.get("page"), auth_dict))


@app.post("/api/adm/createAuth")
def create_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authCreate"))):
    data = body_dict(body)
    software = get_software_or_404(db, user, data.get("softwareId", ""))
    try:
        count = int(data.get("createNumber") or 1)
        day = int(data.get("day") or 0)
        hour = int(data.get("hour") or 0)
        minute = int(data.get("minute") or 0)
    except (TypeError, ValueError):
        return fail("数量和有效期必须是数字")
    if count < 1 or count > 100:
        return fail("创建数量必须在 1 到 100 之间")
    if min(day, hour, minute) < 0:
        return fail("有效期不能小于 0")
    bind_count = data.get("bindCount")
    if bind_count in ("", None):
        bind_count = None
    else:
        try:
            bind_count = int(bind_count)
        except (TypeError, ValueError):
            return fail("绑定次数必须是数字")
        if bind_count < 0:
            return fail("绑定次数不能小于 0")
    rows = []
    for _ in range(count):
        row = AuthCard(
            owner_id=software.owner_id,
            software_id=software.software_id,
            private_key=software.software_id,
            auth_id=random_code("KM", 20),
            creator_id=user.id,
            creator_user=user.user,
            creator_role=normalize_role(user.role),
            day=day,
            hour=hour,
            minute=minute,
            bind_count=bind_count,
            remark=data.get("remark") or "",
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return ok([auth_dict(row) for row in rows], "创建成功")


@app.post("/api/adm/editAuth")
def edit_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_query(db, user).filter(AuthCard.auth_id == data.get("authId")).first()
    if not row:
        return fail("卡密不存在")
    row.bind_count = data.get("bindCount")
    db.commit()
    return ok(auth_dict(row))


@app.post("/api/adm/commitUnBind")
def commit_unbind(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_query(db, user).filter(AuthCard.auth_id == data.get("authId")).first()
    if not row:
        return fail("卡密不存在")
    row.macid = data.get("macid") or None
    if row.macid is None:
        row.bind_used = 0
    db.commit()
    return ok(auth_dict(row))


@app.post("/api/adm/updateAuthRemark")
def update_auth_remark(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_query(db, user).filter(AuthCard.auth_id == data.get("authId")).first()
    if not row:
        return fail("卡密不存在")
    row.remark = data.get("remark") or ""
    db.commit()
    return ok(auth_dict(row))


@app.post("/api/adm/delAuth")
def del_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authDelete"))):
    data = body_dict(body)
    row = visible_auth_query(db, user).filter(AuthCard.auth_id == data.get("authId")).first()
    if row:
        db.delete(row)
        db.commit()
    return ok()


@app.post("/api/adm/batchDelAuth")
def batch_del_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authDelete"))):
    data = body_dict(body)
    ids = data.get("list") or []
    visible_ids = visible_software_ids(db, user)
    db.query(AuthCard).filter(AuthCard.software_id.in_(visible_ids or [""]), AuthCard.auth_id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return ok()


@app.post("/api/adm/exportTable")
def export_table(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authExport"))):
    data = body_dict(body)
    q = visible_auth_query(db, user)
    q = apply_auth_filters(q, data)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["authId", "softwareId", "status", "macid", "endTime", "remark", "creatorUser", "creatorRole"])
    for row in q.order_by(AuthCard.created_at.desc()).all():
        writer.writerow([row.auth_id, row.software_id, row.status, row.macid or "", row.end_time or "", row.remark, row.creator_user or "", row.creator_role or ""])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=auth_cards.csv"})


@app.post("/api/adm/assignAuthToSubUser")
def assign_auth_to_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    sub = data.get("subUserName")
    ids = data.get("authIds") or []
    visible_ids = visible_software_ids(db, user)
    db.query(AuthCard).filter(AuthCard.software_id.in_(visible_ids or [""]), AuthCard.auth_id.in_(ids)).update({"assigned_sub_user": sub}, synchronize_session=False)
    db.commit()
    return ok({"assigned": len(ids)}, "分配成功")


@app.post("/api/adm/customerList")
def customer_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("userView"))):
    data = body_dict(body)
    q = db.query(Customer).filter(Customer.owner_id == owner_id_for(user)).order_by(Customer.created_at.desc())
    if data.get("email"):
        q = q.filter(Customer.email.contains(data["email"]))
    if data.get("customerId"):
        q = q.filter(Customer.customer_id.contains(data["customerId"]))
    return ok(paged(q, data.get("page"), customer_dict))


@app.post("/api/adm/delCustomer")
def del_customer(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("userView"))):
    data = body_dict(body)
    row = db.query(Customer).filter(Customer.owner_id == owner_id_for(user), Customer.customer_id == data.get("customerId")).first()
    if row:
        db.delete(row)
        db.commit()
    return ok()


@app.post("/api/adm/cloudVariablesList")
def cloud_variables_list(user: AdminUser = Depends(require_permission("cloudVarView")), db: Session = Depends(get_db)):
    rows = db.query(CloudVariable).filter(CloudVariable.owner_id == owner_id_for(user)).all()
    return ok({"variables": json.dumps([cloud_var_dict(row) for row in rows], ensure_ascii=False)})


@app.post("/api/adm/saveCloudVariables")
def save_cloud_variables(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    if not any(has_permission(user, code) for code in ("cloudVarAdd", "cloudVarDelete")):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    data = body_dict(body)
    owner_id = owner_id_for(user)
    variables = data.get("variables") or []
    seen = set()
    for item in variables:
        key = (item.get("softwareId") or "", item.get("key", "").strip().lower())
        if not key[1]:
            continue
        if key in seen:
            return fail(f"变量名重复: {item.get('key')}")
        seen.add(key)
    db.query(CloudVariable).filter(CloudVariable.owner_id == owner_id).delete()
    for item in variables:
        if item.get("key"):
            db.add(CloudVariable(owner_id=owner_id, key=item["key"], value=item.get("value") or "", status=item.get("status") or "y", software_id=item.get("softwareId") or ""))
    db.commit()
    return ok()


@app.post("/api/adm/blackWhiteList")
def black_white_list(user: AdminUser = Depends(require_permission("blackWhiteView")), db: Session = Depends(get_db)):
    rows = db.query(BlackWhiteItem).filter(BlackWhiteItem.owner_id == owner_id_for(user)).all()
    return ok({"list": [black_white_dict(row) for row in rows]})


@app.post("/api/adm/saveBlackWhiteList")
def save_black_white_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    if not any(has_permission(user, code) for code in ("blackWhiteAdd", "blackWhiteDelete")):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    data = body_dict(body)
    owner_id = owner_id_for(user)
    items = data.get("list") or []
    seen = set()
    for item in items:
        key = (item.get("softwareId") or "", item.get("type") or "white", str(item.get("value") or "").strip().lower())
        if not key[2]:
            continue
        if key in seen:
            return fail(f"{item.get('type')} 值重复: {item.get('value')}")
        seen.add(key)
    db.query(BlackWhiteItem).filter(BlackWhiteItem.owner_id == owner_id).delete()
    for item in items:
        if item.get("value"):
            db.add(BlackWhiteItem(owner_id=owner_id, type=item.get("type") or "white", value=item["value"], remark=item.get("remark") or "", software_id=item.get("softwareId") or ""))
    db.commit()
    return ok()


@app.post("/api/adm/message/event")
def message_event(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("eventView"))):
    data = body_dict(body)
    q = db.query(EventLog).filter(EventLog.owner_id == owner_id_for(user)).order_by(EventLog.created_at.desc())
    if data.get("type"):
        q = q.filter(EventLog.type == data["type"])
    if data.get("keyword"):
        keyword = f"%{data['keyword']}%"
        q = q.filter(or_(EventLog.keyword.like(keyword), EventLog.message.like(keyword), EventLog.auth_id.like(keyword), EventLog.macid.like(keyword)))
    start, end = parse_time_range(data.get("time"))
    if start:
        q = q.filter(EventLog.created_at >= start)
    if end:
        q = q.filter(EventLog.created_at <= end)
    return ok(paged(q, data.get("page"), event_dict))


@app.post("/api/adm/message/list")
def message_list(db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("messageManage"))):
    rows = db.query(Message).filter(Message.owner_id == owner_id_for(user)).order_by(Message.created_at.desc()).limit(50).all()
    return ok([message_dict(row) for row in rows])


@app.post("/api/adm/message/send")
def message_send(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("messageManage"))):
    data = body_dict(body)
    content = str(data.get("content") or "").strip()
    if not content:
        return fail("消息不能为空")
    row = Message(owner_id=owner_id_for(user), content=content)
    db.add(row)
    db.commit()
    return ok(message_dict(row))


@app.post("/api/adm/subUserList")
def sub_user_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    q = manageable_user_query(db, user).order_by(AdminUser.created_at.desc())
    payload = paged(q, data.get("page"), lambda row: user_dict(row, include_private=False))
    payload["onlineCount"] = q.filter(AdminUser.last_login.isnot(None)).count()
    return ok(payload)


@app.post("/api/adm/createSubUser")
def create_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    role = normalize_role(data.get("role"))
    assert_assignable_role(user, role)
    username = str(data.get("user") or "").strip()
    if not username or not data.get("password"):
        return fail("账号和密码不能为空")
    if db.query(AdminUser).filter(AdminUser.user == username).first():
        return fail("账号已存在")
    software_ids = normalize_software_ids(data.get("softwareIds"))
    if role == ROLE_USER and not software_ids:
        return fail("普通用户必须选择可访问实例")
    row = AdminUser(
        user=username,
        password_hash=hash_password(data.get("password")),
        email=data.get("email") or "",
        nick=data.get("nick") or username,
        role=role,
        parent_id=parent_id_for_role(user, role),
        account_token=new_token_value("acct_"),
        open_id=new_token_value("open_"),
        permission_types=json.dumps(role_permissions(role), ensure_ascii=False),
        software_ids=json.dumps(software_ids if role == ROLE_USER else ["*"], ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return ok(user_dict(row, include_private=False))


@app.post("/api/adm/updateSubUser")
def update_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    row = manageable_user_query(db, user).filter(AdminUser.user == data.get("user")).first()
    if not row:
        return fail("账号不存在")
    role = normalize_role(data.get("role") or row.role)
    assert_assignable_role(user, role)
    row.email = data.get("email") or row.email
    row.nick = data.get("nick") or row.nick
    if data.get("password"):
        row.password_hash = hash_password(data["password"])
    row.role = role
    row.parent_id = parent_id_for_role(user, role, row.parent_id)
    software_ids = normalize_software_ids(data.get("softwareIds"))
    if role == ROLE_USER and not software_ids:
        return fail("普通用户必须选择可访问实例")
    row.permission_types = json.dumps(role_permissions(role), ensure_ascii=False)
    row.software_ids = json.dumps(software_ids if role == ROLE_USER else ["*"], ensure_ascii=False)
    db.commit()
    return ok(user_dict(row, include_private=False))


@app.post("/api/adm/deleteSubUser")
def delete_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    row = manageable_user_query(db, user).filter(AdminUser.user == body_dict(body).get("user")).first()
    if row:
        db.delete(row)
        db.commit()
    return ok()


@app.post("/api/adm/dataCount")
def data_count(db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    softwares = visible_software_query(db, user).all()
    visible_ids = [soft.software_id for soft in softwares]
    visit_list = []
    activation_query = db.query(AuthCard).filter(AuthCard.status == "active", AuthCard.software_id.in_(visible_ids or [""]))
    month_start = datetime.utcnow() - timedelta(days=30)
    month_query = db.query(EventLog).filter(EventLog.created_at >= month_start, EventLog.software_id.in_(visible_ids or [""]))
    activation_count = activation_query.count()
    month_count = month_query.count()
    for soft in softwares:
        logs = db.query(EventLog).filter(EventLog.software_id == soft.software_id, EventLog.created_at >= datetime.utcnow() - timedelta(days=1)).all()
        buckets: dict[int, int] = {}
        for log in logs:
            buckets[log.created_at.hour] = buckets.get(log.created_at.hour, 0) + 1
        visit_list.append({"name": soft.name, "softwareId": soft.software_id, "visitCount": len(logs), "visitList": [{"hours": k, "value": v} for k, v in sorted(buckets.items())]})
    return ok({"countDaily": [], "visitList": visit_list, "activationCount": activation_count, "monthCount": month_count})


@app.post("/api/adm/softwareVisit")
def software_visit(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    software_id = body_dict(body).get("softwareId")
    visible_ids = visible_software_ids(db, user)
    q = db.query(EventLog).filter(EventLog.software_id.in_(visible_ids or [""]))
    if software_id:
        q = q.filter(EventLog.software_id == software_id)
    rows = q.order_by(EventLog.created_at.desc()).limit(300).all()
    return ok([event_dict(row) for row in rows])


def auth_duration(card: AuthCard) -> timedelta | None:
    if card.day == 0 and card.hour == 0 and card.minute == 0:
        return None
    return timedelta(days=card.day, hours=card.hour, minutes=card.minute)


def check_black_white(db: Session, owner_id: int, software_id: str, macid: str | None) -> tuple[bool, str]:
    if not macid:
        return True, ""
    rows = db.query(BlackWhiteItem).filter(BlackWhiteItem.owner_id == owner_id, BlackWhiteItem.software_id.in_([software_id, ""])).all()
    blacks = {row.value.lower() for row in rows if row.type == "black"}
    whites = {row.value.lower() for row in rows if row.type == "white"}
    value = macid.lower()
    if value in blacks:
        return False, "命中黑名单"
    if whites and value not in whites:
        return False, "不在白名单"
    return True, ""


@app.post("/api/client/software/checkUpdate")
def client_check_update(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    soft = db.query(SoftwareInstance).filter(SoftwareInstance.software_id == data.get("softwareId")).first()
    if not soft:
        return fail("实例不存在")
    soft.visit += 1
    soft.lasttime = datetime.utcnow()
    add_event(db, soft.owner_id, "api", "checkUpdate", "检查更新", request, software_id=soft.software_id, macid=data.get("macid"))
    db.commit()
    return ok(software_dict(soft))


@app.post("/api/client/auth/activate")
def client_auth_activate(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    card = db.query(AuthCard).filter(AuthCard.auth_id == data.get("authId"), AuthCard.software_id == data.get("softwareId")).first()
    if not card:
        return fail("卡密不存在")
    allowed, reason = check_black_white(db, card.owner_id, card.software_id, data.get("macid"))
    if not allowed:
        add_event(db, card.owner_id, "api", "activate", reason, request, result="failed", software_id=card.software_id, auth_id=card.auth_id, macid=data.get("macid"))
        db.commit()
        return fail(reason)
    if card.status == "disabled":
        return fail("卡密已禁用")
    if card.macid and card.macid != data.get("macid"):
        return fail("卡密已绑定其他设备")
    card.macid = data.get("macid")
    card.status = "active"
    card.activated_at = card.activated_at or datetime.utcnow()
    duration = auth_duration(card)
    if duration and not card.end_time:
        card.end_time = datetime.utcnow() + duration
    add_event(db, card.owner_id, "api", "activate", "激活成功", request, software_id=card.software_id, auth_id=card.auth_id, macid=card.macid)
    db.commit()
    return ok(auth_dict(card))


@app.post("/api/client/auth/verify")
def client_auth_verify(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    card = db.query(AuthCard).filter(AuthCard.auth_id == data.get("authId"), AuthCard.software_id == data.get("softwareId")).first()
    if not card:
        return fail("卡密不存在")
    allowed, reason = check_black_white(db, card.owner_id, card.software_id, data.get("macid"))
    if not allowed:
        add_event(db, card.owner_id, "api", "verify", reason, request, result="failed", software_id=card.software_id, auth_id=card.auth_id, macid=data.get("macid"))
        db.commit()
        return fail(reason)
    if card.end_time and card.end_time < datetime.utcnow():
        card.status = "expired"
        db.commit()
        return fail("卡密已过期")
    if not card.macid:
        card.macid = data.get("macid")
        card.status = "active"
        card.activated_at = datetime.utcnow()
        duration = auth_duration(card)
        card.end_time = datetime.utcnow() + duration if duration else None
    elif card.macid != data.get("macid"):
        if card.bind_count is not None and card.bind_used >= card.bind_count:
            return fail("换绑次数不足")
        card.macid = data.get("macid")
        card.bind_used += 1
    add_event(db, card.owner_id, "api", "verify", "验证成功", request, software_id=card.software_id, auth_id=card.auth_id, macid=card.macid)
    db.commit()
    return ok(auth_dict(card))


@app.post("/api/client/auth/unbind")
def client_auth_unbind(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    card = db.query(AuthCard).filter(AuthCard.auth_id == data.get("authId"), AuthCard.software_id == data.get("softwareId")).first()
    if not card:
        return fail("卡密不存在")
    if card.macid != data.get("macid"):
        return fail("设备码不匹配")
    card.macid = None
    add_event(db, card.owner_id, "api", "unbind", "解绑成功", request, software_id=card.software_id, auth_id=card.auth_id, macid=data.get("macid"))
    db.commit()
    return ok(auth_dict(card))


@app.post("/api/client/cloudVariables/list")
def client_cloud_vars(body: AnyBody, db: Session = Depends(get_db)):
    data = body_dict(body)
    owner_id = software_owner_by_id(db, data.get("softwareId", ""))
    if owner_id is None:
        return fail("实例不存在")
    rows = db.query(CloudVariable).filter(CloudVariable.owner_id == owner_id, CloudVariable.status == "y", CloudVariable.software_id.in_(["", data.get("softwareId")])).all()
    return ok([cloud_var_dict(row) for row in rows])


@app.post("/api/client/user/register")
def client_user_register(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    owner_id = software_owner_by_id(db, data.get("softwareId", ""))
    if owner_id is None:
        return fail("实例不存在")
    if db.query(Customer).filter(Customer.owner_id == owner_id, Customer.email == data.get("email")).first():
        return fail("邮箱已注册")
    customer = Customer(
        owner_id=owner_id,
        customer_id=random_code("CU", 14),
        email=data.get("email"),
        password_hash=hash_password(data.get("password") or ""),
        nick_name=data.get("nickName") or data.get("email"),
        keys=json.dumps({data.get("softwareId"): "registered"}, ensure_ascii=False),
    )
    db.add(customer)
    add_event(db, owner_id, "api", "userRegister", "用户注册", request, software_id=data.get("softwareId"), customer_id=customer.customer_id)
    db.commit()
    return ok(customer_dict(customer))


@app.post("/api/client/user/login")
def client_user_login(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    owner_id = software_owner_by_id(db, data.get("softwareId", ""))
    customer = db.query(Customer).filter(Customer.owner_id == owner_id, Customer.email == data.get("email")).first() if owner_id else None
    if not customer or not verify_password(data.get("password") or "", customer.password_hash):
        return fail("邮箱或密码错误")
    customer.last_login = datetime.utcnow()
    add_event(db, owner_id, "api", "userLogin", "用户登录", request, software_id=data.get("softwareId"), customer_id=customer.customer_id)
    db.commit()
    return ok(customer_dict(customer))


@app.post("/api/client/user/heartbeat")
def client_user_heartbeat(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    owner_id = software_owner_by_id(db, data.get("softwareId", ""))
    add_event(db, owner_id, "api", "heartbeat", "用户心跳", request, software_id=data.get("softwareId"), customer_id=data.get("customerId"), macid=data.get("macid"))
    db.commit()
    return ok({"serverTime": datetime.utcnow().isoformat()})


@app.post("/api/client/user/logout")
def client_user_logout(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    owner_id = software_owner_by_id(db, data.get("softwareId", ""))
    add_event(db, owner_id, "api", "userLogout", "用户退出", request, software_id=data.get("softwareId"), customer_id=data.get("customerId"))
    db.commit()
    return ok()
