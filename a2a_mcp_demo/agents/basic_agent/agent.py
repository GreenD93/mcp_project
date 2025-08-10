from pathlib import Path
from typing import Iterator, Dict, Any, Optional
from openai import OpenAI
from agents.agent_base import MCPAgentBase


class Agent(MCPAgentBase):
    """
    최소 기능:
      - 초기 system/user 프롬프트로 바로 LLM 호출(스트리밍)
      - 디버그 이벤트 로깅(self._log)만 사용
      - MCP 도구 선택/검증/호출은 수행하지 않음(필요 시 추후 확장)
    """
    # 기본 프롬프트
    init_system = "당신은 사용자의 질문에 친절하게 대답하는 AI 비서입니다."
    init_user_prompt = "{user_input}"

    def __init__(self, llm_client: OpenAI):
        # agent_dir는 카드/툴 메타를 찾을 때 쓰이므로 기본값 유지
        super().__init__(llm_client, agent_dir=Path(__file__).parent)

    # 보기용: 실제 전송 메시지 구성
    def build_messages(self, user_input: str):
        return [
            {"role": "system", "content": self.init_system},
            {"role": "user",   "content": self.init_user_prompt.format(user_input=user_input)},
        ]

    # 엔트리 포인트: Direct 스트리밍만 수행
    def execute(self, user_input: str, debug: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        if debug is None:
            debug = {}
        self._log(debug, "run.start", user_input=user_input)

        # 메시지 준비 + 프롬프트 원문 보관
        messages = self.build_messages(user_input)
        debug.setdefault("execution", {})["init_messages"] = f"""
[시스템 프롬프트]
{self.init_system}

[유저 프롬프트]
{self.init_user_prompt.format(user_input=user_input)}
        """.strip()
        self._log(debug, "messages.ready", roles=[m["role"] for m in messages])

        # LLM 호출(스트리밍)
        try:
            self._log(debug, "llm.call.start", model="gpt-4o", stream=True)
            resp = self.llm.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=True,
            )
            for chunk in resp:
                if getattr(chunk.choices[0].delta, "content", None):
                    yield chunk.choices[0].delta.content
            self._log(debug, "llm.call.end", status="ok")
        except Exception as ex:
            self._log(debug, "llm.call.error", error=str(ex))
            yield "[응답 생성 중 오류가 발생했습니다. 잠시 뒤 다시 시도해주세요.]\n"

        self._log(debug, "run.end", status="ok")
        debug["log"] = debug.get("events", [])