# app.py — Streamlit A2A Chatbot (사이드바: Agent 카드 뷰어, 메인: 챗)
# 실행: streamlit run app.py

import os
import json
import types
from pathlib import Path
from typing import Iterator, Union, Dict, Any

import streamlit as st
from openai import OpenAI

from a2a_client import A2AClient

st.set_page_config(page_title="A2A Chatbot", layout="wide")

# OpenAI
OPENAI_API_KEY = ""

if not OPENAI_API_KEY:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. 환경변수 또는 .streamlit/secrets.toml에 설정하세요.")
if "llm_client" not in st.session_state:
    st.session_state.llm_client = OpenAI(api_key=OPENAI_API_KEY)

# A2A
def init_a2a():
    st.session_state.a2a = A2AClient(agents_root="agents", llm_client=st.session_state.llm_client)
    st.session_state.agents = st.session_state.a2a.discover()
    if st.session_state.agents:
        st.session_state.selected_agent_name = st.session_state.agents[0]["name"]
    else:
        st.session_state.selected_agent_name = None

if "a2a" not in st.session_state:
    init_a2a()

if "messages" not in st.session_state:
    st.session_state.messages = []  # [{role, content}]

# ───────────────────────────────────────────────
# 사이드바: Agent 카드 뷰어
# ───────────────────────────────────────────────
with st.sidebar:
    st.header("🗂️ Agent 카드 뷰어")

    agents = st.session_state.get("agents", [])
    names = [a["name"] for a in agents] if agents else []
    if not names:
        st.info("등록된 에이전트가 없습니다.\n`agents/<name>/{card.json, agent.py}`를 추가하세요.")
    else:
        default_idx = 0
        if st.session_state.get("selected_agent_name") in names:
            default_idx = names.index(st.session_state["selected_agent_name"])
        selected_name = st.selectbox("Agent 리스트", names, index=default_idx, key="agent_select_sidebar")

        selected = next((a for a in agents if a["name"] == selected_name), None)
        if selected:
            st.session_state.selected_agent_name = selected_name
            card_path = Path(selected["path"]) / "card.json"
            try:
                card_json = json.loads(Path(card_path).read_text(encoding="utf-8"))
                st.caption(f"카드 경로: `{card_path}`")
                st.code(json.dumps(card_json, ensure_ascii=False, indent=2), language="json")
            except Exception as e:
                st.error(f"카드 로딩 실패: {e}")

    if st.button("🔄 에이전트 새로고침"):
        init_a2a()
        st.rerun()

    if st.button("🗑️ 대화 초기화"):
        st.session_state.messages = []
        st.rerun()

# ───────────────────────────────────────────────
# 메인 화면: 챗 인터페이스
# ───────────────────────────────────────────────
st.title("🤝 A2A → Agent Chatbot")

# 히스토리 렌더
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# 입력
user_input = st.chat_input("메시지를 입력하세요")
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""

        try:
            # 1) 실행 전: 라우팅 + 디버그 정보 미리 받기
            out = st.session_state.a2a.run(list(st.session_state.messages))
            agent_name = out.get("agent_name")
            result = out.get("result")
            debug = out.get("debug", {})

            # 2) 디버그 먼저 표시 (접힘)
            if agent_name:
                st.caption(f"🛠️ 선택된 Agent: **{agent_name}**")

                with st.expander("라우팅 디버그 보기", expanded=False):
                    st.markdown("**선택 프롬프트 (A2A → LLM)**")
                    st.code(debug.get("prompt", ""), language="markdown")

                    st.markdown("**LLM 결정(JSON)**")
                    st.code(json.dumps(debug.get("decision", {}), ensure_ascii=False, indent=2), language="json")

                    st.markdown("**Agent 실행 요청 입력 (A2A → Agent)**")
                    st.code(debug.get("execution", {}).get("requested_agent_input", ""), language="text")

                    # 시작점(초기 system/user 템플릿)만 명시
                    init_info = debug.get("execution", {}).get("init", {})
                    if init_info:
                        st.markdown("**Agent 시작점(초기 프롬프트)**")
                        st.code(json.dumps(init_info, ensure_ascii=False, indent=2), language="json")

                    # ✅ 초기 메시지 미리보기(있을 때만)
                    init_msgs = debug.get("execution", {}).get("initial_messages")
                    if init_msgs:
                        st.markdown("**초기 메시지 미리보기**")
                        st.code(json.dumps(init_msgs, ensure_ascii=False, indent=2), language="json")

            # 3) 이제 스트리밍 시작
            is_stream = hasattr(result, "__iter__") and not isinstance(result, (dict, list, str))
            if is_stream:
                for token in result:
                    full_text += token
                    placeholder.markdown(full_text)
            else:
                full_text = json.dumps(result, ensure_ascii=False, indent=2)
                placeholder.markdown(f"```json\n{full_text}\n```")
        except Exception as e:
            full_text = f"[에러] 응답 생성 중 문제: {e}"
            placeholder.error(full_text)

    # 어시스턴트 메시지 저장
    st.session_state.messages.append({"role": "assistant", "content": full_text})
