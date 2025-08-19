# a2a_client.py — LLM 기반 에이전트 선택 + execute() 통일 (히스토리 미사용)

import json
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Iterator, Union, Optional  # ★ Optional 추가

Chat = List[Dict[str, str]]

@dataclass
class AgentCard:
    schema_version: str
    name: str
    description: str = ""
    version: str = "0.0.1"
    capabilities: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_file(path: Path) -> "AgentCard":
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentCard(
            schema_version=data.get("schema_version", "1.0"),
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "0.0.1"),
            capabilities=data.get("capabilities", []),
            metadata=data.get("metadata", {}),
        )

class A2AClient:
    def __init__(self, agents_root: str, llm_client, fallback_agent_dir: str = "agents/basic_agent"):
        self.llm = llm_client
        self.root = Path(agents_root)
        self._agents: List[Dict[str, Any]] = self._load_cards()

        self._fallback_path = Path(fallback_agent_dir)
        self._fallback = self._load_agent_runner(self._fallback_path / "agent.py")
        fb_card = self._read_card_safely(self._fallback_path / "card.json")
        self._fallback_name = (fb_card.get("name") if isinstance(fb_card, dict) else None) or self._fallback_path.name

    # ---------- 입력 정규화 (마지막 user_input만 추출) ----------
    def _normalize_input(self, messages_or_text: Union[str, Chat]) -> tuple[Chat, str]:
        if isinstance(messages_or_text, str):
            msgs: Chat = [{"role": "user", "content": messages_or_text}]
            return msgs, messages_or_text
        msgs: Chat = messages_or_text
        last_user = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
        return msgs, last_user

    # ---------- 카드 로딩 ----------
    def _load_cards(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not self.root.exists():
            return items
        for pkg in sorted(self.root.iterdir()):
            if not pkg.is_dir():
                continue
            card_path = pkg / "card.json"
            if not card_path.exists():
                continue
            try:
                card = AgentCard.from_file(card_path)
                items.append({"path": pkg, "card": card})
            except Exception:
                continue
        return items

    # ---------- LLM으로 에이전트 선택 (user_input만 사용) ----------
    def _ask_gpt_for_agent(self, user_input: str) -> tuple[Dict[str, Any], str]:
        brief_cards = [
            {
                "name": it["card"].name,
                "description": it["card"].description,
                "keywords": it["card"].metadata.get("keywords", []),
            }
            for it in self._agents
        ]

        prompt = f"""
최신 사용자 입력: "{user_input}"

아래는 사용할 수 있는 Agent 목록(요약):
{json.dumps(brief_cards, ensure_ascii=False, indent=2)}

당신의 임무는 이 요청을 가장 잘 처리할 Agent를 '정확한 이름으로 1개' 선택하는 것입니다.

반드시 아래 JSON 형식으로만 답변하세요(코드블록 금지):
{{
  "route": "AGENT",
  "agent_name": "<선택한 Agent name>",
  "reason": "이 Agent를 선택한 이유"
}}
"""
        res = self.llm.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = res.choices[0].message.content.strip()
        try:
            decision = json.loads(raw)
        except Exception:
            decision = {"route": "DIRECT", "reason": "parse_error"}
        return decision, prompt

    # ---------- 카드 목록 (UI 확인용) ----------
    def discover(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": it["card"].name,
                "description": it["card"].description,
                "version": it["card"].version,
                "path": str(it["path"]),
            }
            for it in self._agents
        ]

    # ---------- 선택 + 실행 ----------
    # 반환: {"agent_name": str|None, "result": Iterator[str] | Dict[str, Any], "debug": {...}}
    def run(self, messages_or_text: Union[str, Chat], debug: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        app.py에서 debug=dict()를 넘기면, 에이전트가 내부 디버그를 채워서 되돌려줍니다.
        """
        if debug is None:
            debug = {}

        _, user_input = self._normalize_input(messages_or_text)
        decision, prompt = self._ask_gpt_for_agent(user_input)

        debug.update({
            "prompt": prompt,           # A2A → LLM 라우팅 프롬프트
            "decision": decision,       # LLM 선택 결과(JSON)
            "execution": {
                "requested_agent_input": user_input,  # A2A → Agent 전달 입력
            }
        })

        def attach_init_and_preview(runner):
            # 시작점(초기 프롬프트) 명시
            init_info = {}
            if hasattr(runner, "init_system"):
                init_info["system"] = getattr(runner, "init_system")
            if hasattr(runner, "init_user_prompt"):
                init_info["user_template"] = getattr(runner, "init_user_prompt")
            if init_info:
                debug["execution"]["init"] = init_info

            # (선택) initial_messages 미리보기
            preview = getattr(runner, "build_messages", None)
            if preview:
                try:
                    msgs = preview(user_input)
                    debug["execution"]["initial_messages"] = msgs
                except Exception:
                    pass

        # 선택된 에이전트 실행
        if decision.get("route") == "AGENT":
            target_name = decision.get("agent_name")
            target = next((it for it in self._agents if it["card"].name == target_name), None)
            if target is not None:
                runner = self._load_agent_runner(target["path"] / "agent.py")
                if runner is not None and hasattr(runner, "execute"):
                    attach_init_and_preview(runner)  # 실행 전에 디버그 확정
                    try:
                        # ★ debug를 그대로 넘겨서 에이전트가 tool 선택/검증/plan/프롬프트를 채우게 함
                        return {"agent_name": target_name, "result": runner.execute(user_input, debug=debug), "debug": debug}
                    except Exception:
                        pass

        # 폴백
        if self._fallback and hasattr(self._fallback, "execute"):
            attach_init_and_preview(self._fallback)
            try:
                return {"agent_name": self._fallback_name, "result": self._fallback.execute(user_input, debug=debug), "debug": debug}
            except Exception:
                return {"agent_name": self._fallback_name, "result": {"error": "Fallback agent failed"}, "debug": debug}

        return {"agent_name": None, "result": {"error": "No agent could handle the request"}, "debug": debug}

    # ---------- 동적 로더 ----------
    def _load_agent_runner(self, agent_py_path: Path):
        if not agent_py_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            f"agents.{agent_py_path.parent.name}.agent", str(agent_py_path)
        )
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        AgentCls = getattr(mod, "Agent", None)
        if AgentCls is None:
            return None
        try:
            return AgentCls(self.llm)
        except Exception:
            return None

    def _read_card_safely(self, card_path: Path):
        try:
            if card_path.exists():
                return json.loads(card_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return None
