from __future__ import annotations

import json
from datetime import datetime

from .models import AdminUser, AuthCard, BlackWhiteItem, CloudVariable, Customer, EventLog, Message, SoftwareInstance
from .security import normalize_role, role_label, role_permissions, ROLE_USER
from .utils import now_text


def parse_json(value: str, default):
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def user_dict(user: AdminUser, include_private: bool = True) -> dict:
    data = {
        "_id": str(user.id),
        "id": user.id,
        "user": user.user,
        "email": user.email,
        "time": now_text(user.created_at),
        "nick": user.nick or user.user,
        "qq": user.qq,
        "parentId": user.parent_id,
        "role": normalize_role(user.role),
        "roleLabel": role_label(user.role),
        "isAgent": user.is_agent,
        "lastLogin": now_text(user.last_login),
        "permissionTypes": role_permissions(user.role),
        "softwareIds": parse_json(user.software_ids, []),
    }
    if include_private:
        data["openId"] = user.open_id
        data["accountToken"] = user.account_token
        data["fingerId"] = user.finger_id
    return data


def software_dict(row: SoftwareInstance, include_secret: bool = False) -> dict:
    data = {
        "_id": str(row.id),
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "user": str(row.owner_id),
        "lowVersion": row.low_version,
        "softwareId": row.software_id,
        "force": row.force,
        "remark": row.remark,
        "url": row.url,
        "notice": row.notice,
        "visit": row.visit,
        "md5": row.md5,
        "sha256": row.sha256,
        "protocolVersion": row.protocol_version,
        "strictClientAuth": row.strict_client_auth,
        "createTime": now_text(row.created_at),
        "lasttime": now_text(row.lasttime or row.updated_at),
    }
    if include_secret:
        data["instanceKey"] = row.instance_key or ""
    return data


def auth_dict(row: AuthCard) -> dict:
    creator_name = ""
    if row.creator:
        creator_name = row.creator.nick or row.creator.user
    creator_user = row.creator_user or (row.creator.user if row.creator else "")
    return {
        "_id": str(row.id),
        "id": row.id,
        "authId": row.auth_id,
        "softwareId": row.software_id,
        "status": row.status == "active",
        "state": row.status,
        "macid": row.macid,
        "bindCount": row.bind_count,
        "bindUsed": row.bind_used,
        "day": row.day,
        "hour": row.hour,
        "minute": row.minute,
        "endTime": now_text(row.end_time),
        "remark": row.remark,
        "assignedSubUser": row.assigned_sub_user,
        "creatorId": row.creator_id,
        "creatorUser": creator_user,
        "creatorName": creator_name or creator_user,
        "creatorRole": normalize_role(row.creator_role or ROLE_USER),
        "creatorRoleLabel": role_label(row.creator_role or ROLE_USER),
        "createTime": now_text(row.created_at),
        "activatedAt": now_text(row.activated_at),
    }


def customer_dict(row: Customer) -> dict:
    return {
        "_id": str(row.id),
        "id": row.id,
        "customerId": row.customer_id,
        "email": row.email,
        "nickName": row.nick_name,
        "keys": parse_json(row.keys, {}),
        "createTime": now_text(row.created_at),
        "lastLogin": now_text(row.last_login),
    }


def cloud_var_dict(row: CloudVariable) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "value": row.value,
        "status": row.status,
        "softwareId": row.software_id,
    }


def black_white_dict(row: BlackWhiteItem) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "value": row.value,
        "remark": row.remark,
        "softwareId": row.software_id,
    }


def event_dict(row: EventLog) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "keyword": row.keyword,
        "softwareId": row.software_id,
        "authId": row.auth_id,
        "customerId": row.customer_id,
        "macid": row.macid,
        "ip": row.ip,
        "result": row.result,
        "message": row.message,
        "createTime": now_text(row.created_at),
    }


def message_dict(row: Message) -> dict:
    return {"id": row.id, "content": row.content, "createTime": now_text(row.created_at)}


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
