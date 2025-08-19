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
        "너는 사용자 질의를 바탕으로 수신 거래(입금, 이체)를 도와주는 Agent야."
    )

    def __init__(self, llm_client: OpenAI):
        super().__init__(llm_client, agent_dir=Path(__file__).parent)

    def _direct_stream(self, user_input: str, debug: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        user_prompt = (
            "실패 이유를 토대로 사용자에게 양해를 구해줘.\n"
            f"사용자 요청 : {user_input}"
            f"실패 이유 : {debug}"
        )
        if debug is not None:
            debug.setdefault("execution", {}).setdefault("direct", {})["prompt"] = f"""
[시스템 프롬프트]
{self.init_system}

[유저 프롬프트]
{user_prompt}
            """
        self._log(debug, "direct.start", user_input=user_input)

        messages = [
            {"role": "system", "content": self.init_system},
            {"role": "user", "content": user_prompt},
        ]
        resp = self.llm.chat.completions.create(model="gpt-4o", messages=messages, stream=True)
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content
        self._log(debug, "direct.end")

    def execute(self, user_input: str, debug: Optional[Dict[str, Any]] = None):

        if debug is None:
            debug = {}
        # 여기서 execute_stream을 돌려서 문자열로 모으거나,
        # TOOL-분기는 아예 별도로 빠르게 처리하고 dict을 바로 반환
        # ───────── 빠른 TOOL 분기 ─────────
        has_tools = any(self.registry.values())

        if has_tools:
            tool_prompt = self.build_tool_selection_prompt(user_input)
            self._log(debug, "tool.prompt.ready")
            debug["execution"]["tool_selection_prompt"] = tool_prompt

            decision = self.ask_gpt_for_tool(user_input, prompt_override=tool_prompt)
            self._log(debug, "tool.decision", decision=decision)
            debug["execution"]["decision"] = decision

            if decision.get("route") == "TOOL":

                mcp = decision["mcp"]
                tool = decision["tool_name"]
                args = decision.get("arguments", {})
                
                debug["execution"]["plan"] = {"mode": "mcp", "mcp": mcp, "tool": tool, "args": args}

                v = self.validate_args(mcp, tool, args)

                if v["ok"]:

                    # 여기선 진짜로 dict를 'return'
                    self._log(debug, "run.end", status="ok")
                    debug["log"] = debug.get("events", [])   # ← 추가

                    return decision
                
                # 검증 실패 시 Direct로 내려가서 텍스트 생성

                # ───────── Direct 텍스트 생성 ─────────

                chunks = []
                for ch in self._direct_stream(user_input, debug=debug):
                    chunks.append(ch)
                return "".join(chunks)