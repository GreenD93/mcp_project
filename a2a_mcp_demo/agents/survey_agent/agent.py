class Agent:
    def __init__(self, llm_client):
        self.llm = llm_client
        self.init_system = (
            "너는 데이터 기반의 리서치 분석가다. 응답 텍스트에서 핵심 주제/감성/개선 제안을 뽑아 간결하게 정리한다. "
            "가능하면 지표(응답 수, 긍/부/중립 비율 등)를 함께 제시하되, 입력에 숫자형 척도가 없으면 생략."
        )
        self.init_user_prompt = (
            "다음 설문 응답(또는 요약 요청)에 대해 Topline 요약을 작성해줘.\n"
            "요청: {user_input}\n\n"
            "- 핵심 인사이트(3~5개 불릿)\n"
            "- 긍/부/중립 비율(가능한 경우)\n"
            "- 대표 인용(익명, 선택)\n"
            "- 우선순위 액션 아이템(2~3개)\n"
        )

    def build_messages(self, user_input: str):
        return [
            {"role": "system", "content": self.init_system},
            {"role": "user",   "content": self.init_user_prompt.format(user_input=user_input)},
        ]

    def execute(self, user_input: str):
        messages = self.build_messages(user_input)
        resp = self.llm.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            stream=True,
        )
        for chunk in resp:
            if getattr(chunk.choices[0].delta, "content", None):
                yield chunk.choices[0].delta.content
