# signals.py
import streamlit as st

_SIGNAL_KEY = "__one_shot_signal__"

def emit_signal(status: str, payload: dict | None = None):
    """모달 등 하위 컴포넌트에서 메인 영역으로 보낼 일회성 신호 저장"""
    st.session_state[_SIGNAL_KEY] = {
        "status": status,           # "success" | "error" | "cancel" 등
        "payload": payload or {},   # {"message": "...", ...}
    }

def consume_signal():
    """메인 영역에서 신호를 1회성으로 소비 (읽으면 즉시 제거)"""
    return st.session_state.pop(_SIGNAL_KEY, None)