# app.py
import json
from pathlib import Path
import streamlit as st
from openai import OpenAI
from types import GeneratorType

from a2a_client import A2AClient

st.set_page_config(page_title="A2A → Agent → MCP Demo", layout="wide")
st.title("🤖 A2A → Agent → MCP 데모")

# -----------------------------
# 초기화
# -----------------------------
# OpenAI
OPENAI_API_KEY = ""

if not OPENAI_API_KEY:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. 환경변수 또는 .streamlit/secrets.toml에 설정하세요.")

if "llm" not in st.session_state:
    # 환경변수 OPENAI_API_KEY 필요
    st.session_state.llm = OpenAI(api_key=OPENAI_API_KEY)

if "client" not in st.session_state:
    st.session_state.client = A2AClient(agents_root="agents", llm_client=st.session_state.llm)

client: A2AClient = st.session_state.client

if "messages" not in st.session_state:
    st.session_state.messages = []  # [{"role":"user"/"assistant","content": "..."}]

# -----------------------------
# 사이드바: 에이전트 카드 탐색
# -----------------------------
with st.sidebar:
    st.header("🗂 등록된 Agents")

    discovered = client.discover()  # [{name, description, version, path}]
    if not discovered:
        st.info("등록된 에이전트가 없습니다. `agents/<agent>/card.json`을 추가하세요.")
    else:
        names = [d["name"] for d in discovered]
        name_to_path = {d["name"]: d["path"] for d in discovered}

        selected = st.selectbox("Agent 카드 미리보기", names, index=0)
        sel_path = Path(name_to_path[selected]) / "card.json"

        try:
            card_json = json.loads(Path(sel_path).read_text(encoding="utf-8"))
        except Exception as e:
            card_json = {"error": f"card.json 로드 실패: {e}"}

        st.markdown("**선택된 Agent:** " + selected)
        st.code(json.dumps(card_json, ensure_ascii=False, indent=2), language="json")

# -----------------------------
# 메세지 히스토리 렌더링
# -----------------------------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# -----------------------------
# 입력 & 실행
# -----------------------------
user_input = st.chat_input("무엇을 도와드릴까요?")
if user_input:
    # 대화 히스토리에 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 실행 (A2A 라우팅 + Agent 실행)
    resp = client.run(user_input, debug={})  # {"agent_name","result","debug"}
    agent_name = resp.get("agent_name")
    result = resp.get("result")
    debug = resp.get("debug", {})

    # 선택된 에이전트 표시(옵션)
    if agent_name:
        st.caption(f"🧭 라우팅된 Agent: **{agent_name}**")

    # 응답 렌더링
    with st.chat_message("assistant"):
        ph = st.empty()
        full = ""

        # 스트리밍 여부 판단
        is_stream = isinstance(result, GeneratorType) or (
            hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict, list, tuple))
        )

        if is_stream:
            for tok in result:
                full += tok
                ph.markdown(full)
        else:
            if isinstance(result, str):
                full = result
            elif isinstance(result, (dict, list, tuple)):
                full = json.dumps(result, ensure_ascii=False, indent=2)
            else:
                full = str(result)
            ph.markdown(full)

    # 대화 히스토리에 어시스턴트 메시지 추가
    st.session_state.messages.append({"role": "assistant", "content": full})

    # -------------------------
    # 🛠️ Agent 실행 디버그 (툴 선택/Direct)
    # -------------------------
    ex = debug.get("execution", {})
    with st.expander("🛠️ Agent 실행 디버그 (툴 선택/Direct)", expanded=False):

        if "prompt" in debug:
            st.markdown("**라우팅 프롬프트 (A2A → LLM)**")
            st.code(debug["prompt"], language="markdown")
        if "decision" in debug:
            st.markdown("**라우팅 결과 (LLM JSON)**")
            st.code(json.dumps(debug["decision"], ensure_ascii=False, indent=2), language="json")

        # 실행 전략/사유
        plan = ex.get("plan")
        if plan:
            st.markdown("**실행 전략(plan)**")
            st.code(json.dumps(plan, ensure_ascii=False, indent=2), language="json")

        # MCP 도구가 등록되어 있고 판단을 수행한 경우에만 노출
        if "tool_selection_prompt" in ex:
            st.markdown("**Tool 선택 프롬프트**")
            st.code(ex["tool_selection_prompt"], language="markdown")

        if "decision" in ex:
            dec = ex["decision"]
            if isinstance(dec, dict) and "reason" in dec:
                st.markdown(f"**선택 사유(reason):** {dec['reason']}")
            st.markdown("**Tool 선택 결과 (LLM JSON)**")
            st.code(json.dumps(dec, ensure_ascii=False, indent=2), language="json")

        if "validation" in ex:
            st.markdown("**인자 검증 결과 (JSON Schema)**")
            st.code(json.dumps(ex["validation"], ensure_ascii=False, indent=2), language="json")

        # Direct로 갔을 때만 Direct 프롬프트 미리보기 노출
        if "direct" in ex and "prompt" in ex["direct"]:
            st.markdown("**Direct 프롬프트 (미리보기)**")
            st.code(ex["direct"]["prompt"], language="markdown")

    with st.expander("🧾 실행 로그 (모든 이벤트)", expanded=False):
        run_log = debug.get("log", [])
        if run_log:
            st.code(json.dumps(run_log, ensure_ascii=False, indent=2), language="json")
            st.download_button(
                label="로그 JSON 다운로드",
                data=json.dumps(run_log, ensure_ascii=False, indent=2),
                file_name="agent_run_log.json",
                mime="application/json",
            )
        else:
            st.info("현재 실행에서 수집된 로그가 없습니다.")