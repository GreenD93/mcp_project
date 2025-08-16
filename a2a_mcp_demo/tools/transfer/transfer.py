# transfer_api.py
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

app = FastAPI(title="Transfers & Deposits API")

# (데모) 기본 계좌 (출금자는 고정)
ACCOUNT_NAME = "기본 입출금통장"


# -----------------------------
# 요청 스키마
# -----------------------------
class TransferRequest(BaseModel):
    recipient: str = Field(..., description="받는 사람 이름")
    amount: int = Field(..., description="이체 금액(원 단위, 정수)")
    transfer_desc: str = Field(..., description="이체 내용 (받는 사람 통장 표시 내용)")

    @validator("amount")
    def check_amount_positive(cls, v):
        if v <= 0:
            raise ValueError("amount는 0보다 커야 합니다.")
        return v


class ProductDepositRequest(BaseModel):
    product_name: str = Field(..., description="예/적금 상품명")
    amount: int = Field(..., description="입금 금액(원 단위, 정수)")

    @validator("amount")
    def check_amount_positive(cls, v):
        if v <= 0:
            raise ValueError("amount는 0보다 커야 합니다.")
        return v


# -----------------------------
# 1) 특정 지정인한테 이체
# -----------------------------
@app.post("/tool/transfer")
def transfer_to_recipient(req: TransferRequest):
    """
    입력 예:
    {
      "recipient": "홍길동",
      "amount": 50000,
      "transfer_desc": "점심값"
    }

    출력 예:
    {
      "accepted": true,
      "message": "기본 입출금통장에서 홍길동에게 50000원을 이체했습니다. (이체 내용: 점심값)"
    }
    """
    # 실제로는 송금 시스템/DB 처리 로직이 들어갈 자리
    print(f"[이체] {ACCOUNT_NAME}에서 {req.recipient}에게 {req.amount}원을 이체했습니다. "
          f"(이체 내용: {req.transfer_desc})")

    return JSONResponse(
        content={
            "accepted": True,
            "message": f"{ACCOUNT_NAME}에서 {req.recipient}에게 {req.amount}원을 이체했습니다. "
                       f"(이체 내용: {req.transfer_desc})"
        }
    )


# -----------------------------
# 2) 예/적금 상품으로 입금
# -----------------------------
@app.post("/tool/deposit_product")
def deposit_to_savings(req: ProductDepositRequest):
    """
    입력 예:
    {
      "product_name": "자유적금 12개월",
      "amount": 300000
    }

    출력 예:
    {
      "accepted": true,
      "message": "기본 입출금통장에서 자유적금 12개월 상품으로 300000원을 입금했습니다."
    }
    """
    print(f"[입금] {ACCOUNT_NAME}에서 {req.product_name} 상품으로 {req.amount}원을 입금했습니다.")

    return JSONResponse(
        content={
            "accepted": True,
            "message": f"{ACCOUNT_NAME}에서 {req.product_name} 상품으로 {req.amount}원을 입금했습니다."
        }
    )


# (선택) 도구 스펙 노출
@app.get("/tools")
def list_tools():
    return [
        {
            "name": "transfer",
            "description": "고정된 기본 입출금통장에서 받는사람/금액/이체내용을 입력받아 송금합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "받는 사람"},
                    "amount": {"type": "integer", "description": "이체 금액(원 단위)"},
                    "transfer_desc": {"type": "string", "description": "이체 내용"}
                },
                "required": ["recipient", "amount", "transfer_desc"]
            }
        },
        {
            "name": "deposit_product",
            "description": "고정된 기본 입출금통장에서 예/적금(코드K정기예금, 코드K정기적금, 플러스박스, 궁금한적금) 상품으로 입금 합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "예/적금 상품명"},
                    "amount": {"type": "integer", "description": "입금 금액(원 단위)"}
                },
                "required": ["product_name", "amount"]
            }
        }
    ]


if __name__ == "__main__":
    uvicorn.run("transfer:app", host="0.0.0.0", port=8004, reload=True)