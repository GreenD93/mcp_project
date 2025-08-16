# susin_modal.py
import requests
import streamlit as st
from signals import emit_signal

API_BASE = "http://localhost:8004"
TIMEOUT = 8

def call_backend_api(tool_name: str, args: dict) -> dict:
    try:
        if tool_name == "transfer":
            url = f"{API_BASE}/tool/transfer"
            payload = {
                "recipient": args.get("recipient"),
                "amount": int(args.get("amount", 0)),
                "transfer_desc": args.get("transfer_desc", ""),
            }
        elif tool_name == "deposit_product":
            url = f"{API_BASE}/tool/deposit_product"
            payload = {
                "product_name": args.get("product_name"),
                "amount": int(args.get("amount", 0)),
            }
        else:
            return {"ok": False, "error": "지원되지 않는 tool_name 입니다."}

        if any(v in (None, "", 0) for v in payload.values()):
            return {"ok": False, "error": "필수 파라미터가 비어 있습니다."}

        resp = requests.post(url, json=payload, timeout=TIMEOUT)
        if resp.ok:
            return {"ok": True, "data": resp.json()}
        else:
            try:
                err = resp.json()
            except Exception:
                err = {"detail": resp.text}
            return {"ok": False, "error": f"HTTP {resp.status_code}: {err}"}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "요청 시간이 초과되었습니다."}
    except Exception as e:
        return {"ok": False, "error": f"예상치 못한 오류: {e}"}

def _make_chat(tool: str, args: dict, msg: str, ok=True):
    # 간단한 채팅용 문구 생성(원하면 포맷 강화 가능)
    if tool == "transfer":
        return f"이체 {'성공' if ok else '실패'}: {args.get('recipient')}에게 {int(args.get('amount',0)):,}원 – {msg}"
    if tool == "deposit_product":
        return f"상품 입금 {'성공' if ok else '실패'}: {args.get('product_name')} {int(args.get('amount',0)):,}원 – {msg}"
    return msg

def open_susin_modal(payload: dict):
    tool = payload.get("tool_name")
    args = payload.get("arguments", {})
    title = "📌 이체 확인" if tool == "transfer" else "📌 상품 입금 확인" if tool == "deposit_product" else "📌 알 수 없는 작업"

    @st.dialog(title)
    def _modal():
        if tool == "transfer":
            st.text_input("받는 사람", value=str(args.get("recipient", "")), disabled=True)
            st.number_input("금액", value=float(args.get("amount", 0)), step=1.0, disabled=True)
            st.text_area("이체 내용", value=str(args.get("transfer_desc", "")), disabled=True, height=80)
        elif tool == "deposit_product":
            st.text_input("상품 이름", value=str(args.get("product_name", "")), disabled=True)
            st.number_input("금액", value=float(args.get("amount", 0)), step=1.0, disabled=True)
        else:
            st.error("지원되지 않는 tool_name 입니다.")
            if st.button("닫기", use_container_width=True):
                st.stop()
            return

        c1, c2 = st.columns(2)
        with c1:
            if st.button("실행", type="primary", use_container_width=True, key="susin_run"):
                with st.spinner("처리 중..."):
                    result = call_backend_api(tool, args)

                if result.get("ok"):
                    data = result.get("data", {})
                    msg = data.get("message", "요청이 성공했습니다.")
                    emit_signal("success", {
                        "message": msg,
                        "chat": _make_chat(tool, args, msg, ok=True),   # ← 선택: 채팅용 텍스트
                        "tool": tool, "args": args
                    })
                    st.rerun()
                else:
                    msg = result.get("error", "요청에 실패했습니다.")
                    emit_signal("error", {
                        "message": msg,
                        "chat": _make_chat(tool, args, msg, ok=False),
                        "tool": tool, "args": args
                    })
                    st.rerun()
        with c2:
            if st.button("취소", type="secondary", use_container_width=True, key="susin_cancel"):
                emit_signal("cancel", {
                    "message": "요청을 취소했습니다.",
                    "chat": "요청이 취소되었습니다.",
                    "tool": tool, "args": args
                })
                st.rerun()

    _modal()
