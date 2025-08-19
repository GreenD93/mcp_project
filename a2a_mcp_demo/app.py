# app.py
import json
from pathlib import Path
import streamlit as st
from openai import OpenAI
from types import GeneratorType

from a2a_client import A2AClient

from components.banner import render_banner
from components.susin_modal import open_susin_modal
from components.signals import consume_signal

st.set_page_config(page_title="A2A → Agent → MCP Demo", layout="wide")
st.title("🤖 A2A → Agent → MCP 데모")

# -----------------------------
# 초기화
# -----------------------------
# OpenAI
OPENAI_API_KEY = ""

if not OPENAI_API_KEY:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. app.py를 확인해주세요.")

# -------------------------------------
# 세션 초기화
# -------------------------------------
if "llm" not in st.session_state:
    st.session_state.llm = OpenAI(api_key=OPENAI_API_KEY)

if "client" not in st.session_state:
    st.session_state.client = A2AClient(agents_root="agents", llm_client=st.session_state.llm)

client: A2AClient = st.session_state.client

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
    ]

# 배너 컨텍스트 + 버튼 키 충돌 방지용 일련번호
if "banner_ctx" not in st.session_state:
    st.session_state.banner_ctx = {}
if "banner_seq" not in st.session_state:
    st.session_state.banner_seq = 0

# -------------------------------------
# (전역) 수신 신호 소비: 토스트 + 배너 메시지 히스토리 삽입
# -------------------------------------
sig = consume_signal()
if sig:
    status = sig["status"]
    payload = sig.get("payload", {})
    msg = payload.get("message", "")
    chat_text = payload.get("chat", msg)  # chat 없으면 message 사용

    # ✅ 모달 클릭 직후에도 디버그를 보여주기 위해 일시 보류 플래그
    st.session_state["_suspend_debug_pop"] = True

    # 메인 토스트
    if status == "success":
        st.toast(f"✅ {msg}")
        # Susin 성공 → 배너 필요 시 컨텍스트 저장 + 히스토리에 배너 타입 메시지 삽입
        st.session_state.banner_ctx = payload
        st.session_state.banner_seq += 1
        st.session_state.messages.append({
            "role": "assistant",
            "type": "banner",           # 👈 렌더 루프에서 배너로 인식
            "seq": st.session_state.banner_seq
        })

    elif status == "error":
        st.toast(f"❌ {msg}")
        if chat_text:
            st.session_state.messages.append({"role": "assistant", "content": chat_text})

    elif status == "cancel":
        st.toast(f"⚪ {msg}")
        if chat_text:
            st.session_state.messages.append({"role": "assistant", "content": chat_text})

# -------------------------------------
# 사이드바: 에이전트 카드 탐색
# -------------------------------------
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

# -------------------------------------
# 메세지 히스토리 렌더링
# -------------------------------------

# 대화 초기화 버튼
if st.button("🗑 대화 초기화", key="reset_chat", type="primary"):
    st.session_state.messages = []
    st.session_state.pop("debug_to_render", None)
    st.session_state.pop("last_debug", None)
    st.session_state.pop("last_agent_name", None)
    st.session_state.pop("_suspend_debug_pop", None)
    st.session_state.pop("banner_ctx", None)
    st.session_state.pop("banner_seq", None)
    st.rerun()

# 히스토리 렌더링 (배너 타입 메시지면, chat_message 안에서 render_banner 호출)
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        if m.get("type") == "banner":
            # ✅ 이미 열린 chat_message 컨텍스트 안에서 배너 UI만 그린다
            seq = m.get("seq", 0)
            render_banner(seq=seq)
        else:
            st.markdown(m.get("content", ""))

# -------------------------------------
# 입력 & 실행
# -------------------------------------
user_input = st.chat_input("무엇을 도와드릴까요?")
if user_input:
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 실행 (A2A 라우팅 + Agent 실행)
    resp = client.run(user_input, debug={})  # {"agent_name","result","debug"}
    agent_name = resp.get("agent_name")
    result = resp.get("result")
    debug = resp.get("debug", {})

    # 🧭 라우팅 캡션
    st.caption(f"🧭 라우팅된 Agent: **{agent_name}**")

    # ✅ 모달 rerun 전에 세션 저장 (SusinAgent 클릭 직후에도 보여주기 위함)
    st.session_state["last_agent_name"] = agent_name
    st.session_state["debug_to_render"] = debug        # 1회 렌더용
    st.session_state["last_debug"] = debug             # 모달 클릭 직후 보이게 하는 백업

    # SusinAgent면: 모달만 열고, 이 자리에서는 결과를 채팅에 출력하지 않음
    handled_by_modal = (agent_name == "SusinAgent")
    
    if handled_by_modal:
        if isinstance(result, dict) and "tool_name" in result:
            open_susin_modal(result)  # 내부에서 emit_signal → st.rerun()

        else:
            reason = result['reason']
            result = client._direct_stream(user_input, reason)

            ph = st.empty()
            full = ""
            for tok in result:
                full += tok
                ph.markdown(full)

    else:
        # 일반 Agent: 기존처럼 결과 렌더
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

        st.session_state.messages.append({"role": "assistant", "content": full})

# -------------------------------------
# 🛠️ 디버그 + 🧾 로그 (채팅 '아래'에서 렌더)
# -------------------------------------
# 모달 신호 직후엔 pop을 보류해서(또는 last_debug로) 한 번 더 보여줌
_suspend = st.session_state.pop("_suspend_debug_pop", False)

if _suspend:
    # 모달 클릭으로 rerun된 사이클: pop하지 않고 보이기 (없으면 last_debug로 대체)
    _debug = st.session_state.get("debug_to_render") or st.session_state.get("last_debug")
else:
    # 일반 사이클: 이번 실행분을 1회만 보이도록 pop
    _debug = st.session_state.pop("debug_to_render", None)

if _debug:
    ex = _debug.get("execution", {})

    with st.expander("🛠️ Agent 실행 디버그 (툴 선택/Direct)", expanded=False):
        if "prompt" in _debug:
            st.markdown("**라우팅 프롬프트 (A2A → LLM)**")
            st.code(_debug["prompt"], language="markdown")
        if "decision" in _debug:
            st.markdown("**라우팅 결과 (LLM JSON)**")
            st.code(json.dumps(_debug["decision"], ensure_ascii=False, indent=2), language="json")

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

        if "direct" in ex and "prompt" in ex["direct"]:
            st.markdown("**Direct 프롬프트 (미리보기)**")
            st.code(ex["direct"]["prompt"], language="markdown")

        plan = ex.get("plan")
        if plan:
            st.markdown("**실행 전략(plan)**")
            st.code(json.dumps(plan, ensure_ascii=False, indent=2), language="json")


    with st.expander("🧾 실행 로그 (모든 이벤트)", expanded=False):
        run_log = _debug.get("log", [])
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