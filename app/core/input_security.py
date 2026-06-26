from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import filetype

from app.core.config import settings
from app.core.exceptions import ValidationError


def validate_upload_name(filename: str | None) -> str:
    safe_name = Path(filename or "upload.bin").name
    extension = Path(safe_name).suffix.lower()
    if extension not in settings.allowed_upload_extensions:
        raise ValidationError(f"不支持的文件类型: {extension or '无扩展名'}")
    return safe_name


def validate_upload_content(filename: str, content: bytes) -> None:
    if not content:
        raise ValidationError("上传文件不能为空")
    extension = Path(filename).suffix.lower()
    detected = filetype.guess(content)
    if detected is None:
        if extension in {".txt", ".md", ".json", ".yaml", ".yml"}:
            return
        # DOCX and other ZIP-based Office files are reported as zip.
        if extension in {".docx"} and content.startswith(b"PK"):
            return
        raise ValidationError("无法识别上传文件类型")
    allowed_mimes = {
        ".pdf": {"application/pdf"},
        ".doc": {"application/msword", "application/x-ole-storage"},
        ".docx": {
            "application/zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    }
    expected = allowed_mimes.get(extension)
    if expected and detected.mime not in expected:
        raise ValidationError(
            f"文件内容类型 {detected.mime} 与扩展名 {extension} 不匹配"
        )


def validate_git_url(repo_url: str) -> str:
    parsed = urlparse(repo_url.strip())
    if parsed.scheme != "https":
        raise ValidationError("Git 仓库只允许使用 HTTPS 地址")
    hostname = (parsed.hostname or "").lower()
    if hostname not in settings.git_allowed_hosts:
        raise ValidationError(f"不允许访问 Git 主机: {hostname or '未知'}")
    if parsed.username or parsed.password:
        raise ValidationError("Git URL 不允许携带账号或密码")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValidationError(f"无法解析 Git 主机: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValidationError("Git 主机解析到非公网地址")
    return repo_url.strip()
