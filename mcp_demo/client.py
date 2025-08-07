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
            print(f"[ERROR] {name} 서버 연결 실패: {e}")
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
    return json.loads(res.choices[0].message.content)

def call_mcp(mcp_name, tool_name, args):
    try:
        url = f"{MCP_SERVERS[mcp_name]}/tool/{tool_name}"
        with requests.post(url, json=args, stream=True) as res:
            for chunk in res.iter_content(chunk_size=None):
                if chunk:
                    print(chunk.decode(), end="", flush=True)
            print()
            return ""
    except Exception as e:
        return f"[ERROR] MCP 호출 실패: {e}"

def main():
    tool_metadata = fetch_tool_metadata()
    print("\n✅ MCP 클라이언트 시작")

    while True:
        user_input = input("\n💬 사용자 입력 (exit 종료): ")
        if user_input.lower() == "exit":
            break

        decision = ask_gpt_for_tool(user_input, tool_metadata)

        if decision.get("route") == "DIRECT":

            def direct_stream():
                prompt = user_input
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "당신은 사용자의 질문에 친절하게 대답하는 AI 비서입니다."},
                        {"role": "user", "content": prompt}
                    ],
                    stream=True
                )
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            print("🤖 직접 응답: ", end="", flush=True)
            for token in direct_stream():
                print(token, end="", flush=True)
            print()

        else:
            mcp = decision["mcp"]
            tool = decision["tool_name"]
            args = decision["arguments"]
            call_mcp(mcp, tool, args)

if __name__ == "__main__":
    main()

