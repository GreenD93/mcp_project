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
        "너는 사용자의 거래(지출) 내역을 바탕으로 분석하고 응답을 수행하는 전문 Agent야."
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

    def _summarize_with_data(self, user_input: str, data, debug: Optional[Dict[str, Any]] = None,
                             mcp: Optional[str] = None, tool: Optional[str] = None, args: Optional[Dict[str, Any]] = None
                             ) -> Iterator[str]:
        
        # 데이터 프리뷰만 살짝 기록(너무 길어지지 않게)
        try:
            preview = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)[:500]
        except Exception:
            preview = str(data)[:500]
        self._log(debug, "summarize.start", mcp=mcp, tool=tool, args=args, data_preview=preview)

        try:
            data_text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            data_text = str(data)

        messages = [
            {"role": "system", "content": self.init_system},
            {"role": "user", "content":
                "다음 '거래 내역'을 마크다운 표 형태로 정리하고 그 이후에 이를 바탕으로 사용자 요청에 따라 친절하게 응대해줘.\n"
                "반드시 거래내역을 바탕으로 사용자 요청을 처리해야 돼.\n"
                f"요청: {user_input}\n\n 거래 내역:\n{data_text}\n\n"
            },
        ]
        resp = self.llm.chat.completions.create(model="gpt-4o", messages=messages, stream=True)
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content
        self._log(debug, "summarize.end")

    # ---- 실행 엔트리포인트 ----
    def execute(self, user_input: str, debug: Optional[Dict[str, Any]] = None):
        if debug is None:
            debug = {}
        self._log(debug, "run.start", user_input=user_input)

        has_tools = any(self.registry.values())
        debug.setdefault("execution", {})["plan"] = {"mode": None}
        self._log(debug, "registry", has_tools=has_tools, servers=list(self.registry.keys()))

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

                v = self.validate_args(mcp, tool, args)
                debug["execution"]["validation"] = v
                self._log(debug, "tool.validation", ok=v["ok"], errors=v["errors"], warnings=v["warnings"])

                if v["ok"]:
                    try:
                        self._log(debug, "mcp.call.start", mcp=mcp, tool=tool, args=args)
                        data = self.call_mcp(mcp, tool, args, stream=False)
                        self._log(debug, "mcp.call.ok")  # 상세 데이터는 summarize 단계에서 preview만 기록

                        debug["execution"]["plan"] = {"mode": "mcp", "mcp": mcp, "tool": tool}
                        self._log(debug, "plan", mode="mcp", mcp=mcp, tool=tool)

                        yield from self._summarize_with_data(
                            user_input, data, debug=debug, mcp=mcp, tool=tool, args=args
                        )
                        self._log(debug, "run.end", status="ok")
                        debug["log"] = debug.get("events", [])
                        return
                    
                    except Exception as ex:
                        debug["execution"]["plan"] = {"mode": "direct", "reason": f"mcp_call_failed: {ex}"}
                        self._log(debug, "mcp.call.error", error=str(ex))
                        yield from self._incomplete_stream(user_input, ex)

                else:
                    debug["execution"]["plan"] = {"mode": "direct", "reason": "validation_failed"}
                    self._log(debug, "plan", mode="direct", reason="validation_failed")
                    yield "[인자 검증 실패 → Direct로 전환]\n"
                    for e in v["errors"]:
                        yield f"- {e}\n"
            
            elif decision.get("route") == "TOOL_INCOMPLETE":

                reason = decision["reason"]
                debug["execution"]["plan"] = {"mode": "incomplete", "reason": decision.get("reason", reason)}
                self._log(debug, "plan", mode="incomplete", reason=decision.get("reason"))

                yield from self._incomplete_stream(user_input, reason)

            else:
                debug["execution"]["plan"] = {"mode": "direct", "reason": decision.get("reason", "llm_decision_direct")}
                self._log(debug, "plan", mode="direct", reason=decision.get("reason"))

                yield from self._direct_stream(user_input, debug=debug)
                
        else:
            yield from self._direct_stream(user_input, debug=debug)
            debug["execution"]["plan"] = {"mode": "direct", "reason": "no_tools"}
            self._log(debug, "plan", mode="direct", reason="no_tools")

        self._log(debug, "run.end", status="ok")
        debug["log"] = debug.get("events", [])   # ← 추가