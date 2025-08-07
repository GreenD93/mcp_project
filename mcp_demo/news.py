import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from openai import OpenAI

app = FastAPI()
openai_key = ""
llm = OpenAI(api_key=openai_key)

class NewsRequest(BaseModel):
    topic: str

def news_stream_generator(topic: str):
    prompt = f"너는 주식 뉴스 분석가야. '{topic}' 종목에 대해 투자자 관점에서 요약해줘."

    response = llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "당신은 종목 뉴스에 정통한 투자 분석가입니다."},
            {"role": "user", "content": prompt}
        ],
        stream=True
    )

    def generator():
        yield '{"topic": "' + topic + '", "tool": "get_news", "result": "'
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
        yield '"}'

    return generator()

@app.post("/tool/get_news")
def get_news(request: NewsRequest):
    return StreamingResponse(news_stream_generator(request.topic), media_type="application/json")

@app.get("/tools")
def list_tools():
    return [
        {
            "name": "get_news",
            "description": "뉴스 주제에 대한 요약을 제공합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "뉴스 주제 (회사, 인물, 사건 등)"
                    }
                },
                "required": ["topic"]
            }
        }
    ]

if __name__ == "__main__":
    uvicorn.run("news:app", host="0.0.0.0", port=8002, reload=True)