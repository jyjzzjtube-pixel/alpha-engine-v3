# YJ Partners - Claude 작업 프로토콜

## 세션 시작 시 자동 실행
매 세션 시작 시 반드시 실행:
```bash
python -m command_center.claude_helper --status
```
DOWN 사이트나 예산 경고가 있으면 즉시 사용자에게 보고할 것.

## AI 활용 규칙 (비용 최적화)
- 코드 분석, 리서치, 번역, 요약 등 → Gemini(무료) 우선 사용:
  ```bash
  python -m command_center.claude_helper --gemini "분석할 내용"
  ```
- 복잡한 코딩/리팩토링 → Claude Code 직접 수행 (이미 실행 중이므로 추가 비용 없음)
- Claude API 직접 호출은 Gemini 실패 시에만
- 비용에 예민하다 — 불필요한 유료 API 호출 금지

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

## 코드 규칙
- `load_dotenv(override=True)` 항상 사용
- 한국어 주석 사용
- 커밋 메시지는 영어
