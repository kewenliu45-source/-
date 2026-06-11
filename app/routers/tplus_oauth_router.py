import base64
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, CHANJET_MESSAGE_SECRET
from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient, _extract_app_ticket

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    AES = None
    unpad = None

try:
    from dotenv import set_key
except ImportError:
    set_key = None


router = APIRouter()
ENV_FILE = os.path.join(BASE_DIR, ".env")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


def decrypt_chanjet_message(encrypted_message: str, message_secret: str) -> dict:
    if AES is None or unpad is None:
        raise RuntimeError("缺少 pycryptodome，请运行 pip install -r requirements.txt")

    key = message_secret.encode("utf-8")
    if len(key) not in {16, 24, 32}:
        raise ValueError("CHANJET_MESSAGE_SECRET 必须是 16、24 或 32 字节")

    encrypted_bytes = base64.b64decode(encrypted_message, validate=True)
    decrypted_bytes = unpad(AES.new(key, AES.MODE_ECB).decrypt(encrypted_bytes), AES.block_size)
    payload = json.loads(decrypted_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("畅捷通解密消息不是 JSON 对象")

    return payload


def save_chanjet_certificate(certificate: str) -> None:
    if not os.path.exists(ENV_FILE):
        with open(ENV_FILE, "a", encoding="utf-8"):
            pass

    if set_key:
        set_key(ENV_FILE, "CHANJET_CERTIFICATE", certificate)
        return

    lines = []
    found = False
    with open(ENV_FILE, "r", encoding="utf-8") as file:
        for line in file:
            if line.startswith("CHANJET_CERTIFICATE="):
                lines.append(f"CHANJET_CERTIFICATE={certificate}\n")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"CHANJET_CERTIFICATE={certificate}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as file:
        file.writelines(lines)


@router.api_route("/tplus/message/callback", methods=["GET", "POST"])
async def tplus_message_callback(request: Request):
    payload = dict(request.query_params)
    body = {}

    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}

        if isinstance(body, dict):
            payload.update(body)

    encrypted_message = payload.get("encryptMsg")
    if encrypted_message:
        if not CHANJET_MESSAGE_SECRET:
            print("收到畅捷通加密消息，但未配置 CHANJET_MESSAGE_SECRET")
        else:
            try:
                decrypted_payload = decrypt_chanjet_message(str(encrypted_message), CHANJET_MESSAGE_SECRET)
                payload.update(decrypted_payload)
                print(
                    "收到畅捷通消息回调：",
                    {
                        "msgType": decrypted_payload.get("msgType"),
                        "id": decrypted_payload.get("id"),
                        "appKey": decrypted_payload.get("appKey"),
                    },
                )
            except Exception as exc:
                print(f"解密畅捷通消息失败：{exc}")
    else:
        print("收到畅捷通消息回调：", {"method": request.method, "keys": sorted(payload.keys())})

    certificate = payload.get("certificate")
    if certificate:
        save_chanjet_certificate(str(certificate))

    app_ticket = _extract_app_ticket(payload)
    if app_ticket:
        try:
            TPlusOpenAPIClient().save_app_ticket(payload)
        except Exception as exc:
            print(f"保存 appTicket 失败：{exc}")

    return {
        "result": "success",
        "code": 0,
        "msg": "success",
    }


@router.get("/tplus/oauth/callback", response_class=HTMLResponse)
def tplus_oauth_callback(request: Request, code: str | None = None, state: str | None = None):
    if not code:
        raise HTTPException(status_code=400, detail="缺少 T+ OAuth 授权码 code")

    try:
        token_payload = TPlusOpenAPIClient().exchange_code_for_token(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"T+ OAuth 授权失败：{exc}") from exc

    return templates.TemplateResponse(
        request=request,
        name="oauth_success.html",
        context={
            "app_name": token_payload.get("app_name") or "",
            "org_id": token_payload.get("org_id") or "",
            "user_id": token_payload.get("user_id") or "",
            "state": state or "",
        },
    )
