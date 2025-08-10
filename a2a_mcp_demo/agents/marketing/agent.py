class Agent:
    def __init__(self, llm_client):
        self.llm = llm_client
        self.init_system = (
            "너는 실무형 마케팅 전략가다. 간결하지만 실행 가능한 제안을 한다. "
            "모든 제안은 한국어로, 불릿 3~5개, 각 불릿은 1문장."
        )
        self.init_user_prompt = (
            "다음 요청을 기반으로 캠페인 아이디어/핵심 카피/추천 채널 믹스를 제안해줘.\n"
            "요청: {user_input}\n"
            "- 아이디어: ...\n- 핵심 카피: ...\n- 채널 믹스: ...\n"
        )

    def build_messages(self, user_input: str):
        return [
            {"role": "system", "content": self.init_system},
            {"role": "user",   "content": self.init_user_prompt.format(user_input=user_input)},
        ]

    def execute(self, user_input: str):
        # 내부적으로 랭그래프/검색/MCP툴 등을 여러 단계로 써도 OK
        messages = self.build_messages(user_input)
        resp = self.llm.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            stream=True,
        )
        for chunk in resp:
            if getattr(chunk.choices[0].delta, "content", None):
                yield chunk.choices[0].delta.content