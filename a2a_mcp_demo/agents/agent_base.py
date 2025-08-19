import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterator

import requests
from openai import OpenAI

try:
    from jsonschema import Draft7Validator  # optional
except Exception:
    Draft7Validator = None


class MCPAgentBase:
    """
    최소 책임:
      - tools/*/manifest.json + tools/mcp_servers.json 로 레지스트리 구성
      - LLM으로 MCP 도구 선택 질의 (ask_gpt_for_tool)
      - 선택된 도구 호출 (call_mcp)
      - arguments JSON Schema 검증 (validate_args)
    """

    init_system: str = ""

    def __init__(self, llm_client: OpenAI, agent_dir: Optional[Path] = None):
        self.llm: OpenAI = llm_client
        self.agent_dir: Path = agent_dir or Path(__file__).parent
        # 🔹 run 별 누적 로그 버퍼
        self.run_log: List[Dict[str, Any]] = []

        # card.json
        self.card: Dict[str, Any] = self._read_json(self.agent_dir / "card.json") or {}
        meta: Dict[str, Any] = self.card.get("metadata") or {}

        raw_tools = meta.get("tools", [])
        self.allow_all_tools: bool = False
        if isinstance(raw_tools, str) and raw_tools.strip() == "*":
            self.allow_all_tools = True
            self.allowed_servers: set[str] = set()
        elif isinstance(raw_tools, list):
            self.allowed_servers = set(raw_tools)
        else:
            self.allowed_servers = set()

        project_root = Path(__file__).resolve().parents[1]
        self.tools_root: Path = project_root / "tools"
        self.server_map: Dict[str, str] = self._read_json(self.tools_root / "mcp_servers.json") or {}
        self.registry: Dict[str, Dict[str, Dict[str, Any]]] = self._load_registry()

    # ---------------- Run-log helpers ----------------
    def reset_run_log(self):
        self.run_log = []

    def log(self, event: str, **fields):
        rec = {
            "ts": time.time(),
            "event": event,
            **fields
        }
        for k, v in list(rec.items()):
            if isinstance(v, str) and len(v) > 4000:
                rec[k] = v[:4000] + " …(truncated)"
        self.run_log.append(rec)

    # ---------------- IO helpers ----------------
    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load_registry(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        reg: Dict[str, Dict[str, Dict[str, Any]]] = {}
        if not self.tools_root.exists():
            return reg
        if not self.allow_all_tools and len(self.allowed_servers) == 0:
            return reg

        for server_dir in self.tools_root.iterdir():
            if not server_dir.is_dir():
                continue
            manifest = self._read_json(server_dir / "manifest.json")
            if not manifest:
                continue
            server = manifest.get("server")
            if not server:
                continue
            if not self.allow_all_tools and server not in self.allowed_servers:
                continue
            for t in manifest.get("tools", []):
                name = t.get("name")
                if not name:
                    continue
                reg.setdefault(server, {})[name] = {
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}) or {},
                    "path": t.get("path", f"/tool/{name}"),
                    "method": (t.get("method") or "POST").upper(),
                }
        return reg

    def list_tools_for_prompt(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for server, tools in self.registry.items():
            for name, spec in tools.items():
                out.append({
                    "mcp": server,
                    "tool_name": name,
                    "description": spec.get("description", ""),
                    "parameters": spec.get("parameters", {}),
                })
        return out

    def build_tool_selection_prompt(self, user_input: str) -> str:
        role_text = (
            self.init_system
            or (self.card.get("description") if isinstance(self.card, dict) else "")
            or "도구를 적절히 선택해 문제를 해결하는 전문가"
        )
        tool_metadata = self.list_tools_for_prompt()

        prompt = f"""
역할: {role_text}

사용자 입력: "{user_input}"

아래는 사용 가능한 MCP 툴 목록입니다:
{json.dumps(tool_metadata, indent=2, ensure_ascii=False)}

당신의 임무는 사용자의 요청에 적절한 MCP Tool이 있는지 판단하고, 있다면 어떤 Tool이고 어떤 파라미터를 넘겨야 하는지를 결정하는 것입니다.
선정/비선정의 이유(reason)를 1~2문장으로 함께 제공하세요.

출력 형식 규칙 (아주 중요):
- 반드시 아래 세 가지 형식 중 하나여야 합니다.
- JSON만 단독으로 출력해야 하며, 어떠한 설명, 코드블록(예: ```json), 주석, 추가 텍스트도 포함하지 마세요.
- JSON 키와 값은 정확히 지정된 구조만 사용하세요.

1) 호출 가능 (필수 파라미터 충족 → Tool 실행 가능)
{{
  "mcp": "<mcp 이름>",
  "tool_name": "<tool 이름>",
  "arguments": {{ <파라미터 키:값> }},
  "route": "TOOL",
  "reason": "왜 이 도구를 선택했는지 간단한 근거"
}}

2) 호출 불가 - Tool은 맞지만 필수 파라미터 부족
{{
  "route": "TOOL_INCOMPLETE",
  "reason": "Tool을 사용해야 하지만 필수 파라미터가 부족하여 호출 불가능한 이유"
}}

3) 호출 불가 - Tool이 없거나, 없어도 직접 해결 가능
{{
  "route": "DIRECT",
  "reason": "적합한 Tool이 없거나, Tool이 필요하지 않아 직접 처리 가능한 이유"
}}

""".strip()
        self.log("tool.prompt", role_text=role_text, user_input=user_input, tool_count=len(tool_metadata))
        return prompt

    def ask_gpt_for_tool(self, user_input: str, *, prompt_override: Optional[str] = None) -> Dict[str, Any]:
        prompt = prompt_override or self.build_tool_selection_prompt(user_input)
        res = self.llm.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (res.choices[0].message.content or "").strip()
        self.log("tool.decision.raw", raw=raw)
        try:
            data = json.loads(raw)
        except Exception:
            self.log("tool.decision.parse_error")
            return {"route": "DIRECT", "error": "parse_error", "raw": raw}
        if "server" in data and "mcp" not in data:
            data["mcp"] = data.pop("server")
        if data.get("route") == "TOOL":
            if not data.get("mcp") or not data.get("tool_name"):
                return {"route": "DIRECT", "error": "missing_keys", "raw": data}
            data.setdefault("arguments", {})
        self.log("tool.decision.parsed", decision=data)
        return data

    def call_mcp(self, mcp: str, tool_name: str, args: Dict[str, Any], *, stream: bool = True):
        if mcp not in self.registry or tool_name not in self.registry[mcp]:
            raise RuntimeError(f"Unregistered tool: {mcp}.{tool_name}")
        if mcp not in self.server_map:
            raise RuntimeError(f"Unknown server host: {mcp}")

        spec = self.registry[mcp][tool_name]
        base = self.server_map[mcp].rstrip("/")
        url = f"{base}{spec['path']}"
        method = (spec["method"] or "POST").upper()

        t0 = time.time()
        self.log("mcp.call.start", mcp=mcp, tool=tool_name, url=url, method=method, args=args, stream=stream)

        if method == "GET":
            res = requests.get(url, params=args or {}, stream=stream, timeout=None)
        else:
            res = requests.post(url, json=args or {}, stream=stream, timeout=None)

        self.log("mcp.call.response.head",
                 status=res.status_code,
                 headers=dict(res.headers),
                 elapsed_ms=int((time.time() - t0) * 1000))
        res.raise_for_status()

        if not stream:
            data = res.json()
            try:
                preview = json.dumps(data, ensure_ascii=False)[:1000]
            except Exception:
                preview = str(data)[:1000]
            self.log("mcp.call.response.body", size=len(preview), preview=preview)
            return data

        def gen() -> Iterator[str]:
            bytes_total = 0
            for chunk in res.iter_content(chunk_size=None):
                if chunk:
                    bytes_total += len(chunk)
                    yield chunk.decode(errors="ignore")
            self.log("mcp.call.stream.end",
                     bytes_total=bytes_total,
                     elapsed_ms=int((time.time() - t0) * 1000))
        return gen()

    def execute(self, user_input: str, debug: Optional[Dict[str, Any]] = None):
        raise NotImplementedError

    # --------------- JSON Schema 검증 ---------------
    def get_tool_schema(self, mcp: str, tool_name: str) -> Optional[Dict[str, Any]]:
        try:
            return self.registry[mcp][tool_name].get("parameters")
        except Exception:
            return None

    def validate_args(self, mcp: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        반환: {"ok": bool, "errors": [str], "warnings": [str]}
        """
        result: Dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
        schema = self.get_tool_schema(mcp, tool_name)
        if not schema:
            result["warnings"].append("no_schema: parameters schema not provided")
            return result

        # jsonschema 있으면 풀 검증
        if Draft7Validator is not None:
            try:
                validator = Draft7Validator(schema)
                errors = sorted(validator.iter_errors(arguments), key=lambda e: e.path)
                if errors:
                    result["ok"] = False
                    for e in errors:
                        loc = ".".join([str(p) for p in e.path]) or "(root)"
                        result["errors"].append(f"{loc}: {e.message}")
            except Exception as ex:
                result["ok"] = False
                result["errors"].append(f"validator_error: {ex}")
            return result

        # 폴백: 필수/간단 타입만
        try:
            req = list(schema.get("required") or [])
            props = dict(schema.get("properties") or {})
            for k in req:
                if k not in arguments:
                    result["ok"] = False
                    result["errors"].append(f"missing required property: '{k}'")

            _type_map = {
                "string": str, "number": (int, float), "integer": int,
                "boolean": bool, "object": dict, "array": list,
            }
            for k, v in arguments.items():
                if k in props:
                    t = props[k].get("type")
                    if t:
                        py = _type_map.get(t)
                        if py and not isinstance(v, py):
                            result["ok"] = False
                            result["errors"].append(
                                f"type mismatch at '{k}': expected {t}, got {type(v).__name__}"
                            )
            result["warnings"].append("fallback_validator: install 'jsonschema' for full validation")
        except Exception as ex:
            result["ok"] = False
            result["errors"].append(f"fallback_validator_error: {ex}")

        return result
    
    def _log(self, debug: Optional[Dict[str, Any]], event: str, **fields):
        """
        간단한 debug 로거: debug 딕셔너리에 events 리스트를 생성하고 이벤트를 추가
        """
        if debug is None:
            return
        try:
            debug.setdefault("events", []).append({"event": event, **fields})
        except Exception:
            pass

    def _incomplete_stream(self, user_input: str, reason: Optional[Dict[str, Any]] = None) -> Iterator[str]:

        user_prompt = (
            "실패 이유를 토대로 사용자에게 양해를 구해줘.\n"
            "사용자가 잘 이해할 수 있게 친절하고 줄바꿈해서!\n"
            f"사용자 요청 : {user_input}"
            f"실패 이유 : {reason}"
        )

        messages = [
            {"role": "user", "content": user_prompt},
        ]
        resp = self.llm.chat.completions.create(model="gpt-4o", messages=messages, stream=True)
        for ch in resp:
            if getattr(ch.choices[0].delta, "content", None):
                yield ch.choices[0].delta.content