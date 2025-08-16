# ad_minder.py
import uvicorn
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime

app = FastAPI()

# ---------------------------------------------
# 예시 데이터셋 (여러 배너/여러 날짜)
# ---------------------------------------------
# 컬럼: bnnr_id, base_dt, impression_cnt, click_cnt
# 날짜는 문자열이 아닌 pandas datetime으로 보관
raw_data = [
    # bnnr_id 1232
    {"bnnr_id": 1232, "base_dt": "2025-08-08", "impression_cnt": 100, "click_cnt": 9},
    {"bnnr_id": 1232, "base_dt": "2025-08-09", "impression_cnt": 120, "click_cnt": 11},
    {"bnnr_id": 1232, "base_dt": "2025-08-10", "impression_cnt": 123, "click_cnt": 12},
    {"bnnr_id": 1232, "base_dt": "2025-08-11", "impression_cnt": 150, "click_cnt": 15},

    # bnnr_id 5555
    {"bnnr_id": 5555, "base_dt": "2025-08-09", "impression_cnt": 200, "click_cnt": 25},
    {"bnnr_id": 5555, "base_dt": "2025-08-10", "impression_cnt": 180, "click_cnt": 18},
    {"bnnr_id": 5555, "base_dt": "2025-08-11", "impression_cnt": 220, "click_cnt": 24},

    # bnnr_id 7777
    {"bnnr_id": 7777, "base_dt": "2025-08-10", "impression_cnt": 90,  "click_cnt": 6},
    {"bnnr_id": 7777, "base_dt": "2025-08-11", "impression_cnt": 110, "click_cnt": 9},
]

df = pd.DataFrame(raw_data)
df["base_dt"] = pd.to_datetime(df["base_dt"])  # 문자열 → datetime

# ---------------------------------------------
# 요청 스키마
# ---------------------------------------------
class PerformanceRequest(BaseModel):
    bnnr_id: int = Field(..., description="배너 번호 (정수)")
    start_date: str = Field(..., description="조회 시작일 (YYYY-MM-DD)")
    end_date: str = Field(..., description="조회 종료일 (YYYY-MM-DD)")

# ---------------------------------------------
# 유틸 함수
# ---------------------------------------------

def parse_date(date_str: str) -> Optional[pd.Timestamp]:
    try:
        return pd.to_datetime(date_str, format="%Y-%m-%d", errors="raise")
    except Exception:
        return None


def build_payload(bnnr_id: int, start_date: str, end_date: str):
    # 날짜 파싱 & 검증
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start is None or end is None:
        return {
            "bnnr_id": bnnr_id,
            "start_date": start_date,
            "end_date": end_date,
            "records": [],
            "grouped": [],
            "summary": None,
            "message": "날짜 형식은 YYYY-MM-DD 이어야 합니다.",
        }
    if end < start:
        return {
            "bnnr_id": bnnr_id,
            "start_date": start_date,
            "end_date": end_date,
            "records": [],
            "grouped": [],
            "summary": None,
            "message": "종료일이 시작일보다 빠를 수 없습니다.",
        }

    # 데이터 필터링
    subset = df[(df["bnnr_id"] == bnnr_id) & (df["base_dt"].between(start, end))].copy()
    subset.sort_values("base_dt", inplace=True)

    if subset.empty:
        return {
            "bnnr_id": bnnr_id,
            "start_date": start_date,
            "end_date": end_date,
            "records": [],
            "grouped": [],
            "summary": None,
            "message": "해당 조건에 맞는 실적 데이터가 없습니다.",
        }

    # 상세 레코드 리스트 (문자열 날짜로 변환하여 반환)
    records = [
        {
            "bnnr_id": int(row.bnnr_id),
            "base_dt": row.base_dt.strftime("%Y-%m-%d"),
            "impression_cnt": int(row.impression_cnt),
            "click_cnt": int(row.click_cnt),
            "ctr": round((row.click_cnt / row.impression_cnt) if row.impression_cnt else 0.0, 6),
        }
        for _, row in subset.iterrows()
    ]

    # --- 배너ID 기준 groupby 합계/CTR 계산 ---
    grouped_df = subset.groupby("bnnr_id", as_index=False).agg(
        impression_sum=("impression_cnt", "sum"),
        click_sum=("click_cnt", "sum")
    )
    grouped_df["ctr"] = grouped_df.apply(
        lambda r: (r["click_sum"] / r["impression_sum"]) if r["impression_sum"] else 0.0,
        axis=1
    )
    grouped = [
        {
            "bnnr_id": int(row.bnnr_id),
            "impression_sum": int(row.impression_sum),
            "click_sum": int(row.click_sum),
            "ctr": round(float(row.ctr), 6)
        }
        for _, row in grouped_df.iterrows()
    ]

    # 전체 요약(단일 배너 요청이므로 grouped[0]과 동일)
    total_impr = int(subset["impression_cnt"].sum())
    total_click = int(subset["click_cnt"].sum())
    ctr = (total_click / total_impr) if total_impr else 0.0

    summary = {
        "total_impression": total_impr,
        "total_click": total_click,
        "ctr": round(ctr, 6),
        "days": len(subset),
        "date_range": {
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
        },
    }

    return {
        "bnnr_id": bnnr_id,
        "start_date": start_date,
        "end_date": end_date,
        "records": records,
        "grouped": grouped,
        "summary": summary,
        "message": None,
    }


# ---------------------------------------------
# 엔드포인트
# ---------------------------------------------
@app.post("/tool/performance")
def get_performance(request: PerformanceRequest):
    """
    입력 예:
    {
      "bnnr_id": 1232,
      "start_date": "2025-08-09",
      "end_date": "2025-08-11"
    }

    출력 예(집계 결과 중심):
    {
      "bnnr_id": 1232,
      "start_date": "2025-08-09",
      "end_date": "2025-08-11",
      "grouped": [
        {"bnnr_id": 1232, "impression_sum": 393, "click_sum": 38, "ctr": 0.096698}
      ],
      "records": [...일자별 원본...],
      "summary": {"total_impression": 393, "total_click": 38, "ctr": 0.096698, "days": 3, "date_range": {"start": "2025-08-09", "end": "2025-08-11"}},
      "message": null
    }
    """
    payload = build_payload(request.bnnr_id, request.start_date, request.end_date)
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")


@app.get("/tools")
def list_tools():
    # 오픈API 식 파라미터 스키마 제공
    return [
        {
            "name": "performance",
            "description": "배너 번호와 기간(시작/종료)을 입력받아 해당 배너의 실적(노출/클릭/CTR)을 반환합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bnnr_id": {"type": "integer", "description": "배너 번호"},
                    "start_date": {"type": "string", "description": "조회 시작일 (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "조회 종료일 (YYYY-MM-DD)"}
                },
                "required": ["bnnr_id", "start_date", "end_date"]
            }
        }
    ]


if __name__ == "__main__":
    # 파일명이 ad_minder.py 라고 가정
    uvicorn.run("ad_minder:app", host="0.0.0.0", port=8002, reload=True)
