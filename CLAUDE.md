# YJ Partners - Claude 작업 프로토콜

## 세션 시작 시 자동 실행
매 세션 시작 시 반드시 실행:
```bash
python -m command_center.claude_helper --status
```
DOWN 사이트나 예산 경고가 있으면 즉시 사용자에게 보고할 것.

## AI 8개 프로바이더 (비용 최적화 필수!)
사용자는 비용에 극도로 예민하다. 무료부터 쓸 것.

### 무료 (적극 활용)
```bash
# Gemini Flash — 범용 (리서치, 번역, 요약, 분석)
python -m command_center.claude_helper --gemini "분석할 내용"

# Gemini Pro — 울트라급 심층 분석 (무료!)
python -m command_center.claude_helper --gemini-pro "심층 분석 내용"

# Ollama llama3.1 — 로컬 AI (오프라인도 가능, 완전 무료)
python -m command_center.claude_helper --ollama "질문"

# Claude Code 자체 — 코딩/브라우저/파일 (구독 내, 추가비용 0)
# → 복잡한 코딩, 리팩토링, 브라우저 제어는 직접 수행
```

### 유료 (무료 실패 시에만)
```bash
# 통합 AI (자동 폴백: Gemini → Ollama → Haiku → OpenAI → Sonnet)
python -m command_center.claude_helper --ai "질문"

# 직접 지정 (정말 필요할 때만)
python -m command_center.claude_helper --claude "질문"     # Haiku 저가
python -m command_center.claude_helper --openai "질문"     # GPT-4o-mini 저가
```

### AI 사용 의사결정
1. 리서치/분석/번역/요약 → `--gemini` (무료)
2. 심층 분석/복잡한 추론 → `--gemini-pro` (무료)
3. 빠른 간단 질문 → `--ollama` (로컬 무료)
4. 코딩/파일/브라우저 → Claude Code 직접 (구독 내)
5. 위 전부 실패 → `--ai` 자동 폴백
6. 유료 API 직접 호출은 최후의 수단

## 작업 완료 알림
중요 작업 완료 시 텔레그램 리포트:
```bash
python -m command_center.claude_helper --telegram "작업명 완료: 결과 요약"
```

## 비용 확인
비용에 예민한 작업 전후로 확인:
```bash
python -m command_center.claude_helper --cost
```

## 통합 검색
코드/DB/알림 검색:
```bash
python -m command_center.claude_helper --search "키워드"
```

## 사이트 건강검진
```bash
python -m command_center.claude_helper --health
```

## 관리 대상
- 사이트 15개 (GitHub Pages 10 + External 5)
- 봇 4개 (master-bot, kakao-bot, cost-api, shorts-factory)
- 블로그 2개: `jyjzzj` (브릿지원), `ezsbizteam` (쿠팡)

## OpenClaw 자동화 (24시간 무인)
게이트웨이: `ws://127.0.0.1:18792`
텔레그램 봇: @yj_ai_command_bot (Gemini 연동, 무료)

### 크론 작업 (자동 실행 중)
- `morning-report`: 매일 08:00 오전 브리핑 → 텔레그램
- `night-report`: 매일 22:00 일일 마감 → 텔레그램
- `health-check`: 30분마다 사이트 다운 감지 → 알림
- `cost-alert`: 6시간마다 비용 초과 경고 → 알림

### OpenClaw CLI (필요시)
```bash
openclaw health                    # 게이트웨이 상태
openclaw cron list                 # 크론 작업 확인
openclaw agent --message "질문"    # AI 에이전트 호출
openclaw message send --channel telegram --to 8355543463 --message "메시지"
```

## 풀파워 모드 (항상 활성)
- **브라우저 제어**: Claude in Chrome 확장프로그램으로 크롬 직접 제어
- **크롬 끊김 시**: 즉시 `mcp__Claude_in_Chrome__tabs_context_mcp` 재연결 시도
- **Gemini 활용 (무료 우선)**:
  - Gemini Flash: 리서치, 분석, 문장 생성, 번역
  - Gemini Pro: 심층 분석, 복잡한 추론
  - 나노바나나 Pro: 이미지 생성 (OpenClaw 스킬)
  - Canva: 디자인 편집
- **Ollama**: 로컬 llama3.1:8b, 오프라인 가능, localhost:11434
- **작업 원칙**: 멈추지 말 것. 병렬 처리. 빠르고 스마트하게.
- **도구 우선순위**: Gemini(무료) → Ollama(로컬무료) → Claude Code(구독내) → Claude API(최후)

## 코드 규칙
- `load_dotenv(override=True)` 항상 사용
- 한국어 주석 사용
- 커밋 메시지는 영어
