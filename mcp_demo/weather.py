import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from openai import OpenAI

app = FastAPI()
openai_key = ""
llm = OpenAI(api_key=openai_key)

class WeatherRequest(BaseModel):
    location: str

def weather_stream_generator(location: str):
    prompt = f"너는 기상 전문 AI야. '{location}' 지역의 날씨를 친절하고 정확하게 설명해줘."

    response = llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "당신은 친절한 기상 AI입니다."},
            {"role": "user", "content": prompt}
        ],
        stream=True
    )

    def generator():
        yield '{"location": "' + location + '", "tool": "get_weather", "result": "'
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
        yield '"}'

    return generator()

@app.post("/tool/get_weather")
def get_weather(request: WeatherRequest):
    return StreamingResponse(weather_stream_generator(request.location), media_type="application/json")

@app.get("/tools")
def list_tools():
    return [
        {
            "name": "get_weather",
            "description": "입력 지역의 날씨 정보를 알려줍니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "지역 이름"
                    }
                },
                "required": ["location"]
            }
        }
    ]

if __name__ == "__main__":
    uvicorn.run("weather:app", host="0.0.0.0", port=8001, reload=True)