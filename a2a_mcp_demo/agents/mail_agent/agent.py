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
        "너는 메일 전송을 포함한 다양한 유틸리티성 업무(알림 전송, 간단 조회·정리 등)를 처리하는 에이전트야. "
        "항상 공손하고 간결하게, 과한 추측 없이 요점만 전달해."
    )

    def __init__(self, llm_client: OpenAI):
        super().__init__(llm_client, agent_dir=Path(__file__).parent)

    # ---- 도구 없음/미선택: 공손한 양해 안내 ----
    def _direct_stream(self, user_input: str, debug: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        ex = (debug or {}).get("execution", {}) or {}
        plan = ex.get("plan") or {}
        reason = plan.get("reason") or "사용 가능한 도구로는 요청을 처리하기 어렵습니다."

        user_prompt = (
            "현재 사용 가능한 도구로는 요청을 바로 처리하기 어렵다는 점을 공손하게 양해 구하는 메시지를 작성해줘. "
            "가능하면 사용자가 요청을 조금 바꿔서 다시 시도해 달라고 정중히 부탁해. "
            "장황한 대안/체크리스트는 넣지 말고 2~4문장으로 간단히.\n\n"
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
            "아래 실행 결과를 근거로, 사용자의 요청을 처리하기 위해 어떤 도구/조치를 수행했고 "
            "어떤 결과가 반환되었는지를 간단히 요약해줘. "
            "민감정보(이메일·전화·토큰 등)는 그대로 노출하지 말고 필요 시 일부 마스킹 해.\n\n"
            f"[사용자 요청]\n{user_input}\n\n"
            f"[도구]\n{mcp}.{tool}\n\n"
            f"[입력 인자]\n{json.dumps(args or {}, ensure_ascii=False, indent=2)}\n\n"
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

    # ---- 도구 사용 경로 실패: plan.reason으로 친절 안내 ----
    def _explain_failure_from_plan(self, user_input: str, debug: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        ex = (debug or {}).get("execution", {}) or {}
        plan = ex.get("plan") or {}
        reason = plan.get("reason") or "처리 중 문제가 발생했습니다."

        self._log(debug, "failure.explain.start", reason=reason)

        system_msg = (
            self.init_system
            + " 실패 사유를 2~4문장으로 공손하고 간단히 설명해. "
              "아래 '이유' 문장만 그대로 포함하고, 불필요한 추측/체크리스트는 넣지 마."
        )
        user_msg = (
            "아래 정보를 바탕으로, 도구 실행을 시도했지만 완료되지 않았음을 정중히 안내하는 메시지를 작성해줘. "
            "핵심은 '이유' 문장을 그대로 포함하는 거야.\n\n"
            f"[사용자 요청]\n{user_input}\n\n[이유]\n{reason}"
        )

        resp = self.llm.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            stream=True,
        )
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content

        self._log(debug, "failure.explain.end")

    # ---- 실행 엔트리포인트 ----
    def execute(self, user_input: str, debug: Optional[Dict[str, Any]] = None):
        if debug is None:
            debug = {}
        self._log(debug, "run.start", user_input=user_input)

        has_tools = any(self.registry.values())
        exec_ctx = debug.setdefault("execution", {})
        exec_ctx["plan"] = {"mode": None}
        self._log(debug, "registry", has_tools=has_tools, servers=list(self.registry.keys()))

        # 1) MCP 서버 없음 → 공손 양해
        if not has_tools:
            exec_ctx["plan"] = {"mode": "direct", "reason": "사용 가능한 도구가 없습니다."}
            for ch in self._direct_stream(user_input, debug=debug):
                yield ch
            self._log(debug, "run.end", status="failed:no_tools")
            debug["log"] = debug.get("events", [])   # ← 추가
            return

        # 2) 도구 선택
        tool_prompt = self.build_tool_selection_prompt(user_input)
        exec_ctx["tool_selection_prompt"] = tool_prompt
        decision = self.ask_gpt_for_tool(user_input, prompt_override=tool_prompt)
        exec_ctx["decision"] = decision

        # 2-1) 도구 미선택 → 공손 양해
        if decision.get("route") != "TOOL":
            exec_ctx["plan"] = {"mode": "direct", "reason": decision.get("reason", "적합한 도구를 선택하지 않았습니다.")}
            for ch in self._direct_stream(user_input, debug=debug):
                yield ch
            self._log(debug, "run.end", status="failed:tool_not_selected")
            debug["log"] = debug.get("events", [])   # ← 추가
            return

        # 3) 인자 검증
        mcp = decision.get("mcp")
        tool = decision.get("tool_name")
        args = decision.get("arguments", {}) or {}

        v = self.validate_args(mcp, tool, args)
        exec_ctx["validation"] = v
        if not v.get("ok"):
            # 도구 사용 경로 진입했으나 실패 → plan.reason으로 안내
            exec_ctx["plan"] = {
                "mode": "direct",
                "reason": decision.get("reason", "요청 인자 검증에 실패하여 호출하지 못했습니다."),
                "mcp": mcp,
                "tool": tool,
            }
            for ch in self._explain_failure_from_plan(user_input, debug=debug):
                yield ch
            self._log(debug, "run.end", status="failed:validation")
            debug["log"] = debug.get("events", [])   # ← 추가
            return

        # 4) 도구 호출
        try:
            self._log(debug, "mcp.call.start", mcp=mcp, tool=tool, args=args)
            data = self.call_mcp(mcp, tool, args, stream=False)
            self._log(debug, "mcp.call.ok")
                
            exec_ctx["plan"] = {"mode": "mcp", "mcp": mcp, "tool": tool}

            # 범용 요약
            for ch in self._summarize_tool_execution(
                user_input, data, debug=debug, mcp=mcp, tool=tool, args=args
            ):
                yield ch

            self._log(debug, "run.end", status="ok")
            debug["log"] = debug.get("events", [])   # ← 추가
            return

        except Exception as ex:
            exec_ctx["plan"] = {"mode": "direct", "reason": f"MCP 도구 호출 중 오류가 발생했습니다: {ex}", "mcp": mcp, "tool": tool}
            self._log(debug, "mcp.call.error", error=str(ex))
            for ch in self._explain_failure_from_plan(user_input, debug=debug):
                yield ch
            self._log(debug, "run.end", status="failed:mcp_call")
            debug["log"] = debug.get("events", [])   # ← 추가
            return
