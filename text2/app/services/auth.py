from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

# 直接调用 bcrypt，不再经过 passlib：passlib 1.7.4 与 bcrypt >= 4.1 不兼容
# （内部用 72 字节以上的测试密码探测后端时会抛 ValueError）。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    # bcrypt 只使用前 72 个字节；这里直接拒绝超长 UTF-8 密码，避免静默截断。
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise HTTPException(422, "密码 UTF-8 长度不能超过 72 字节")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), encoded.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm="HS256")


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "登录状态无效或已过期", headers={"WWW-Authenticate": "Bearer"})
    if not token:
        raise unauthorized
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload.get("sub", ""))
    except (JWTError, ValueError):
        raise unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user
