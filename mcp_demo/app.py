import streamlit as st
import requests
import json
from openai import OpenAI

openai_key = ""  # 실제 키로 교체
client = OpenAI(api_key=openai_key)

MCP_SERVERS = {
    "weather": "http://localhost:8001",
    "news": "http://localhost:8002"
}

def fetch_tool_metadata():
    tools = []
    for name, base_url in MCP_SERVERS.items():
        try:
            res = requests.get(f"{base_url}/tools")
            for tool in res.json():
                tools.append({"mcp": name, "tool": tool})
        except Exception as e:
            st.error(f"[ERROR] {name} 서버 연결 실패: {e}")
    return tools

def ask_gpt_for_tool(user_input, tool_metadata):
    prompt = f"""
사용자 입력: "{user_input}"

아래는 사용 가능한 MCP 툴 목록입니다:
{json.dumps(tool_metadata, indent=2, ensure_ascii=False)}

당신의 임무는 사용자의 요청에 적절한 MCP Tool이 있는지 판단하고, 있다면 어떤 Tool이고 어떤 파라미터를 넘겨야 하는지를 결정하는 것입니다.

응답 형식은 반드시 다음 중 하나여야 합니다:

1. 사용자의 요청에 적절한 Tool이 존재하고, 파라미터도 충분히 주어진 경우:
{{
  "mcp": "<mcp 이름>",
  "tool_name": "<tool 이름>",
  "arguments": {{ <파라미터 키:값> }},
  "route": "TOOL"
}}

2. MCP Tool 목록 중 사용자 요청에 대응할 수 있는 Tool이 없거나, 필요한 파라미터가 부족하여 호출이 불가능한 경우:
{{
  "route": "DIRECT"
}}

응답은 반드시 코드 블록 없이 순수 JSON 형태로 반환하세요. (예: ```json 같은 포맷 없이)
"""
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    print('-'*50)
    print(prompt)
    print('-'*50)

    print('-'*50)
    print(res.choices[0].message.content)
    print('-'*50)

    return json.loads(res.choices[0].message.content)

def call_mcp(mcp_name, tool_name, args):
    try:
        url = f"{MCP_SERVERS[mcp_name]}/tool/{tool_name}"
        with requests.post(url, json=args, stream=True) as res:
            response_text = ""
            for chunk in res.iter_content(chunk_size=None):
                if chunk:
                    text = chunk.decode()
                    response_text += text
                    yield text
    except Exception as e:
        yield f"[ERROR] MCP 호출 실패: {e}"

def direct_response(user_input):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "당신은 사용자의 질문에 친절하게 대답하는 AI 비서입니다."},
            {"role": "user", "content": user_input}
        ],
        stream=True
    )
    for chunk in response:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

# --- Streamlit UI ---
st.set_page_config(page_title="MCP 챗봇", layout="centered")
st.title("🤖 MCP 챗봇")

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

if "tool_metadata" not in st.session_state:
    st.session_state.tool_metadata = fetch_tool_metadata()

# 이전 메시지 히스토리 렌더링
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력
user_input = st.chat_input("무엇을 도와드릴까요?")
if user_input:
    # 히스토리에 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 챗봇 응답 렌더링
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""

        decision = ask_gpt_for_tool(user_input, st.session_state.tool_metadata)

        if decision.get("route") == "DIRECT":
            for token in direct_response(user_input):
                full_response += token
                response_placeholder.markdown(full_response)
        else:
            mcp = decision["mcp"]
            tool = decision["tool_name"]
            args = decision["arguments"]
            for token in call_mcp(mcp, tool, args):
                full_response += token
                response_placeholder.markdown(full_response)

    # 히스토리에 챗봇 응답 추가
    st.session_state.messages.append({"role": "assistant", "content": full_response})
