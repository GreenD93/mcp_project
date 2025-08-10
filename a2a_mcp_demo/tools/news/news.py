# news.py
import uvicorn
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import JSONResponse

app = FastAPI()

# 예시 DataFrame (원하시는 대로 교체/확장 가능)
df = pd.DataFrame({
    "company": ["삼성전자", "카카오", "네이버", "삼성전자", "조용걸"],
    "info": [
        "삼성전자는 반도체/스마트폰을 주력으로 하는 대형주입니다.",
        "카카오는 플랫폼/콘텐츠 중심의 기업입니다.",
        "네이버는 검색/커머스/클라우드 사업을 영위합니다.",
        "삼성전자 추가 설명: 배당 및 글로벌 매출 비중이 큽니다.",
        "조용걸이라는 회사는 이목동 104동 802호에서 개인사업을하고 있는 회사입니다."
    ]
})

class NewsRequest(BaseModel):
    company: str  # 종목명

def build_payload(company: str):
    key = (company or "").strip()
    matches = df[df["company"] == key]["info"].tolist()
    if not matches:
        return {"company": key, "info": None, "message": "해당 종목을 찾지 못했습니다."}
    # 여러 건일 수 있으므로 리스트로 반환
    return {"company": key, "info": matches, "message": None}

@app.post("/tool/get_news")
def get_news(request: NewsRequest):
    """
    입력: {"company": "삼성전자"}
    출력 예:
    {
      "company": "삼성전자",
      "info": ["삼성전자는 ...", "삼성전자 추가 설명: ..."],
      "message": null
    }
    """
    print("저 호출됨요!")
    payload = build_payload(request.company)
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")

@app.get("/tools")
def list_tools():
    # parameters 스키마의 키를 company로 통일(기존 topic → company)
    return [
        {
            "name": "get_news",
            "description": "회사에 대한 뉴스 정보들과 보고서 내용을 요약해서 제공합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "회사 이름"
                    }
                },
                "required": ["company"]
            }
        }
    ]

if __name__ == "__main__":
    # 파일명이 news.py 라고 가정
    uvicorn.run("news:app", host="0.0.0.0", port=8001, reload=True)