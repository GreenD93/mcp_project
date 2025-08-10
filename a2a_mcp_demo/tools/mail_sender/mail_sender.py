import os
import re
import ssl
import smtplib
import json
from typing import Dict

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from email.utils import formataddr, make_msgid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# ----- config.json 로드 -----
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

# ----- 간단 정규화 -----
def _normalize_password(s: str) -> str:
    # 앱 비밀번호는 공백 보이는 형태라서, 모든 공백 제거
    return re.sub(r"\s+", "", s or "")

# ----- SMTP 설정 -----
SMTP_HOST = config.get("SMTP_HOST", "")
SMTP_PORT = int(config.get("SMTP_PORT", 587))
SMTP_USERNAME = config.get("SMTP_USERNAME", "")        # ← Gmail이면 보통 이메일 주소여야 함
SMTP_PASSWORD = _normalize_password(config.get("SMTP_PASSWORD", ""))
SMTP_FROM = config.get("SMTP_FROM", SMTP_USERNAME)
SMTP_FROM_NAME = config.get("SMTP_FROM_NAME", "Mail Sender")
SMTP_USE_TLS = bool(config.get("SMTP_USE_TLS", True))   # 587 + TLS
SMTP_USE_SSL = bool(config.get("SMTP_USE_SSL", False))  # 465 + SSL
SMTP_TIMEOUT = int(config.get("SMTP_TIMEOUT", 10))

# 수신인 매핑
RECIPIENT_MAP: Dict[str, str] = config.get("RECIPIENT_MAP", {})

app = FastAPI(title="Mapped Mail Sender API")


class MappedMailRequest(BaseModel):
    name: str = Field(..., description="수신인 이름 (매핑 딕셔너리에 있는 키)")
    subject: str = Field(..., description="메일 제목")
    body: str = Field(..., description="메일 본문")


# ----- 유효성 검사 (에러를 '명확한 메시지'로 반환) -----
def _validate_smtp_config():
    if not (SMTP_HOST and SMTP_PORT and SMTP_FROM):
        raise ValueError("SMTP_HOST/PORT/FROM 설정이 누락되었습니다.")
    # Gmail 사용하는데 사용자명이 이메일 형식이 아니거나 비ASCII면 바로 실패 사유 반환
    if "gmail.com" in SMTP_HOST:
        if "@" not in SMTP_USERNAME:
            raise ValueError("Gmail은 SMTP 사용자명으로 '전체 이메일 주소'를 사용해야 합니다.")
    try:
        SMTP_USERNAME.encode("ascii")
        SMTP_PASSWORD.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("SMTP_USERNAME/SMTP_PASSWORD에 비ASCII 문자가 있습니다. 사용자명은 이메일 주소(ASCII)로, 앱 비밀번호는 공백 제거 후 16자리로 입력하세요.")
    if not (len(SMTP_PASSWORD) == 16 and SMTP_PASSWORD.isalnum()):
        raise ValueError("Gmail 앱 비밀번호는 공백 제거 후 영문/숫자 16자리여야 합니다.")


def _build_message(to_email: str, req: MappedMailRequest) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["Message-ID"] = make_msgid()
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_FROM))
    msg["To"] = to_email
    msg["Subject"] = str(Header(req.subject, "utf-8"))
    msg.attach(MIMEText(req.body, _subtype="plain", _charset="utf-8"))
    return msg


def _send_message(msg: MIMEMultipart, to_email: str) -> None:
    _validate_smtp_config()
    if SMTP_USE_SSL:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=SMTP_TIMEOUT) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.ehlo()
            if SMTP_USE_TLS:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())


# ----- 에러 → (status, payload) 변환을 최대한 단순화 -----
def _to_error_response(e: Exception):
    # SMTP 인증 실패
    if isinstance(e, smtplib.SMTPAuthenticationError):
        msg = e.smtp_error.decode("utf-8", "ignore") if isinstance(e.smtp_error, (bytes, bytearray)) else str(e.smtp_error)
        return 401, {"accepted": False, "error": "SMTPAuthenticationError", "smtp_code": e.smtp_code, "smtp_error": msg}
    # 발신/수신 거부
    if isinstance(e, smtplib.SMTPSenderRefused):
        return 400, {"accepted": False, "error": "SMTPSenderRefused", "smtp_code": e.smtp_code, "smtp_error": str(e.smtp_error), "sender": e.sender}
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        details = {addr: {"code": code, "error": (resp.decode("utf-8","ignore") if isinstance(resp, (bytes, bytearray)) else str(resp))}
                   for addr, (code, resp) in e.recipients.items()}
        return 400, {"accepted": False, "error": "SMTPRecipientsRefused", "details": details}
    # 서버/네트워크/데이터 오류
    if isinstance(e, (smtplib.SMTPDataError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError)):
        return 502, {"accepted": False, "error": e.__class__.__name__, "detail": str(e)}
    # 설정/검증 실패(우리가 의도적으로 raise한 것 포함)
    if isinstance(e, ValueError):
        return 400, {"accepted": False, "error": "ValueError", "detail": str(e)}
    # 알 수 없는 오류
    return 500, {"accepted": False, "error": e.__class__.__name__, "detail": str(e)}


# ----- API -----
@app.post("/tool/send_mail_mapped")
def send_mail_mapped(req: MappedMailRequest):
    to_email = RECIPIENT_MAP.get(req.name)
    if not to_email:
        return JSONResponse(content={"accepted": False, "error": f"'{req.name}' 수신인을 찾을 수 없습니다."}, status_code=404)
    try:
        msg = _build_message(to_email, req)
        _send_message(msg, to_email)  # 동기 전송
        return JSONResponse(content={"accepted": True, "to": to_email, "subject": req.subject, "message_id": msg["Message-ID"]})
    except Exception as e:
        status, payload = _to_error_response(e)
        return JSONResponse(content=payload, status_code=status)


# (필요하면 유지, 아니면 삭제해도 됨)
@app.get("/tools")
def list_tools():
    return [{
        "name": "send_mail_mapped",
        "description": "수신인 이름과 제목/본문을 받아서 매핑된 이메일 주소로 메일을 전송합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "수신인 이름 (config.json의 RECIPIENT_MAP 키)"},
                "subject": {"type": "string", "description": "메일 제목"},
                "body": {"type": "string", "description": "메일 본문"}
            },
            "required": ["name", "subject", "body"]
        }
    }]

if __name__ == "__main__":
    uvicorn.run("mail_sender:app", host="0.0.0.0", port=8003, reload=True)