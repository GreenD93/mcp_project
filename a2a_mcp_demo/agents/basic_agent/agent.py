class Agent:
    def __init__(self, llm_client):
        self.llm = llm_client
        # 시작점(공개): 초기 시스템/유저 프롬프트
        self.init_system = "당신은 사용자의 질문에 친절하게 대답하는 AI 비서입니다."
        self.init_user_prompt = "{user_input}"

    # 선택: 초기 메시지(보기용) — 디버그에서 펼쳐보려면 제공
    def build_messages(self, user_input: str):
        return [
            {"role": "system", "content": self.init_system},
            {"role": "user",   "content": self.init_user_prompt.format(user_input=user_input)},
        ]

    def execute(self, user_input: str):
        # 여기부터는 내부 그래프/체이닝 자유
        # 단순 예시(초기 메시지로 한 번 쏘고 스트리밍)
        messages = self.build_messages(user_input)
        resp = self.llm.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            stream=True,
        )
        for chunk in resp:
            if getattr(chunk.choices[0].delta, "content", None):
                yield chunk.choices[0].delta.content