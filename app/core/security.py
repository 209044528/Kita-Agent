from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header

from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError


@dataclass(frozen=True)
class RequestIdentity:
    user_id: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_identity(authorization: str | None = Header(default=None)) -> RequestIdentity:
    if not settings.AUTH_ENABLED:
        return RequestIdentity(user_id="anonymous", role="admin")

    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("缺少 Bearer API Key")

    supplied = authorization.removeprefix("Bearer ").strip()
    return resolve_api_key(supplied)


def resolve_api_key(supplied: str) -> RequestIdentity:
    for api_key, (user_id, role) in settings.auth_key_map.items():
        if hmac.compare_digest(supplied, api_key):
            return RequestIdentity(user_id=user_id, role=role)
    raise AuthenticationError("API Key 无效")


def require_admin(
    identity: RequestIdentity = Depends(get_identity),
) -> RequestIdentity:
    if not identity.is_admin:
        raise AuthorizationError("该接口仅管理员可访问")
    return identity
