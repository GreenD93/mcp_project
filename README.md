```markdown
# 프로젝트 설명

이 프로젝트는 a2a_mcp 구현과 mcp_demo 구현 예제를 포함합니다. 
- `a2a_mcp_demo`: 다양한 에이전트(basic, marketing, stock, survey)와 툴(ad_minder, news)을 포함한 MCP 클라이언트/서버 구현
- `mcp_demo`: 뉴스/날씨 서버와 클라이언트를 포함한 간단한 MCP 데모

## 프로젝트 구조

├── a2a_mcp_demo
│   ├── a2a_client.py
│   ├── agents/
│   │   ├── agent_base.py
│   │   ├── basic_agent/
│   │   ├── marketing/
│   │   ├── stock_agent/
│   │   └── survey_agent/
│   ├── app.py
│   ├── tools/
│   │   ├── ad_minder/
│   │   └── news/
├── langgraph_tutorial.ipynb
├── mcp_demo
│   ├── app.py
│   ├── client.py
│   ├── news.py
│   ├── weather.py
├── mcp_test.ipynb
├── meta/overview.png
├── README.md
├── requirements.txt
└── test.py
```

## 실행 방법
```bash
sh a2a_mcp_demo/run_client_server.sh # client(Chatbot)
sh a2a_mcp_demo/tools/news/run_ad_minder_server.sh # 마케팅 배너 실적 조회 Tool
sh a2a_mcp_demo/tools/ad_miner/run_news_server.sh # 뉴스종목 검색 Tool
```

## 시스템 개요
![시스템 개요](./meta/overview.png)
```
