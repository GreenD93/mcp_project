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

아래는 사용 가능한 MCP 툴입니다:
{json.dumps(tool_metadata, indent=2, ensure_ascii=False)}

The result should be a plain json format, without code block formatting (like ```json).

요청을 분석하여 어떤 MCP를 사용할지 판단하고, 해당 MCP tool에 전달할 파라미터를 추출하세요.

응답 형식:
{{
  "mcp": "<mcp 이름>",
  "tool_name": "<tool 이름>",
  "arguments": {{ <파라미터 키:값> }},
  "route": "TOOL"
}}
v
필요한 정보가 부족하면 다음처럼:
{{
  "route": "DIRECT"
}}
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

