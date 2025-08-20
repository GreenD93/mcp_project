# agents/utility_agent.agent.py
from pathlib import Path
from typing import Iterator, Dict, Any, Optional
import json
from openai import OpenAI
from agents.agent_base import MCPAgentBase


class Agent(MCPAgentBase):
    """
    정책:
      - MCP 도구 호출 성공 → 결과 요약(LLM)
      - 도구 없음/미선택 → _direct_stream으로 공손한 양해 안내(LLM)
      - 도구 사용 경로에서 실패(검증 실패/호출 예외) → plan.reason으로 실패 사유 친절 안내(LLM)
    """
    init_system = (
        "너는 메일 발송, 회의록 요약, 알림/일정 안내, 간단 조회·변환 등 다양한 유틸리티 요청을 처리하는 에이전트야. "
        "가능하면 MCP 도구를 적절히 선택·호출하고, 불가한 경우에는 정중히 사유를 안내해. "
        "답변은 공손하고 간결하게 작성하고, 불필요한 추측은 하지 마. "
        "민감정보(이메일·전화번호·토큰 등)는 항상 일부 마스킹해."
    )

    def __init__(self, llm_client: OpenAI):
        super().__init__(llm_client, agent_dir=Path(__file__).parent)

    # ---- 도구 없음/미선택: 공손한 양해 안내 ----
    def _direct_stream(self, user_input: str, debug: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        ex = (debug or {}).get("execution", {}) or {}
        plan = ex.get("plan") or {}
        reason = plan.get("reason") or "사용 가능한 도구로는 요청을 처리하기 어렵습니다."

        user_prompt = (
            "다음 정보를 바탕으로, 현재 사용 가능한 도구로는 요청을 즉시 처리하기 어렵다는 점을 "
            "정중하게 안내하는 2~4문장을 작성해줘. 아래 '사유' 문장은 그대로 포함하고, "
            "필요하다면 사용자가 요청을 어떻게 바꾸면 좋을지 한 문장만 제안해(선택). "
            "체크리스트나 과도한 지시는 넣지 마.\n\n"
            f"[사용자 요청]\n{user_input}\n\n[사유]\n{reason}"
        )
        if debug is not None:
            debug.setdefault("execution", {}).setdefault("direct", {})["prompt"] = f"""
[시스템 프롬프트]
{self.init_system}

[유저 프롬프트]
{user_prompt}
            """
        self._log(debug, "direct.start", user_input=user_input, reason=reason)

        messages = [
            {"role": "system", "content": self.init_system},
            {"role": "user", "content": user_prompt},
        ]
        resp = self.llm.chat.completions.create(model="gpt-4o", messages=messages, stream=True)
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content
        self._log(debug, "direct.end")

    # ---- 도구 성공: 범용 결과 요약 ----
    def _summarize_tool_execution(
        self,
        user_input: str,
        data: Any,
        *,
        debug: Optional[Dict[str, Any]] = None,
        mcp: Optional[str] = None,
        tool: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
    ) -> Iterator[str]:
        try:
            data_text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            data_text = str(data)

        sys = self.init_system
        usr = (
            "성공/실패/부분 성공 여부가 드러나도록 쓰고, 민감정보는 일부 마스킹해. "
            "사용자가 읽기 편하게 줄바꿈, 띄어쓰기해서 잘 알려줘"
            
            f"[사용자 요청]\n{user_input}\n\n"
            f"[실행 결과]\n{data_text}"
        )
        self._log(debug, "summarize.start", mcp=mcp, tool=tool)
        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
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

                        yield from self._summarize_tool_execution(
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