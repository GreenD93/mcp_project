from pathlib import Path
from typing import Iterator, Dict, Any, Optional
import json
from openai import OpenAI
from agents.agent_base import MCPAgentBase


class Agent(MCPAgentBase):
    """
    정책:
      - MCP 도구가 선택·검증·호출까지 성공하면, 결과 데이터를 근거로 Topline 요약(스트리밍)
      - 그렇지 않으면 Direct로 Topline 요약(스트리밍)
    """
    init_system = (
        "너는 주식과 관련된 업무를 처리하는 전문 Agent야."
    )

    def __init__(self, llm_client: OpenAI):
        super().__init__(llm_client, agent_dir=Path(__file__).parent)

    def _direct_stream(self, user_input: str, debug: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        user_prompt = (
            "사용자 요청에 대해서 너의 인사이트와 정보를 알려줘\n"
            f"사용자 요청 : {user_input}"
        )
        if debug is not None:
            debug.setdefault("execution", {}).setdefault("direct", {})["prompt"] = f"""
[시스템 프롬프트]
{self.init_system}

[유저 프롬프트]
{user_prompt}
            """

        messages = [
            {"role": "system", "content": self.init_system},
            {"role": "user", "content": user_prompt},
        ]
        resp = self.llm.chat.completions.create(model="gpt-4o", messages=messages, stream=True)
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content

    def _summarize_with_data(self, user_input: str, data) -> Iterator[str]:
        try:
            data_text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
            
        except Exception:
            data_text = str(data)

        messages = [
            {"role": "system", "content": self.init_system},
            {"role": "user", "content":
                "다음 '참고 자료'를 근거로 핵심 정보와 결과를 요역해서 작성해줘.\n"
                f"요청: {user_input}\n\n 참고 자료:\n{data_text}\n\n"
                "- 핵심 인사이트(3~5개)\n- 대외 상황 및 경쟁사 정보들"
            },
        ]
        resp = self.llm.chat.completions.create(model="gpt-4o", messages=messages, stream=True)
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content

    def execute(self, user_input: str, debug: Optional[Dict[str, Any]] = None):
        if debug is None:
            debug = {}

        has_tools = any(self.registry.values())
        if has_tools:
            tool_prompt = self.build_tool_selection_prompt(user_input)
            debug.setdefault("execution", {})["tool_selection_prompt"] = tool_prompt

            decision = self.ask_gpt_for_tool(user_input, prompt_override=tool_prompt)
            debug["execution"]["decision"] = decision

            if decision.get("route") == "TOOL":
                mcp = decision["mcp"]
                tool = decision["tool_name"]
                args = decision.get("arguments", {})

                v = self.validate_args(mcp, tool, args)
                debug["execution"]["validation"] = v
                if v["ok"]:
                    try:

                        data = self.call_mcp(mcp, tool, args, stream=False)

                        data = data["info"]

                        debug["execution"]["plan"] = {"mode": "mcp", "mcp": mcp, "tool": tool}

                        yield from self._summarize_with_data(user_input, data)
                        return
                    except Exception as ex:
                        debug["execution"]["plan"] = {"mode": "direct", "reason": f"mcp_call_failed: {ex}"}
                        yield "[MCP 호출 실패 → Direct로 전환]\n"
                else:
                    debug["execution"]["plan"] = {"mode": "direct", "reason": "validation_failed"}
                    yield "[인자 검증 실패 → Direct로 전환]\n"
                    for e in v["errors"]:
                        yield f"- {e}\n"
            else:
                debug["execution"]["plan"] = {"mode": "direct", "reason": decision.get("reason", "llm_decision_direct")}
        else:
            debug.setdefault("execution", {})["plan"] = {"mode": "direct", "reason": "no_tools"}

        # Direct
        yield from self._direct_stream(user_input, debug=debug)