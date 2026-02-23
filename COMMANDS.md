# YJ MASTER COMMAND REFERENCE
# 이 파일 하나로 모든 시스템을 컨트롤한다

---

## ═══════════════════════════════════════
## 🎯 TIER 1: 매일 쓰는 핵심 명령어
## ═══════════════════════════════════════

### [Claude Code] 시스템 상태 한눈에
```bash
python -m command_center.claude_helper --status
python -m command_center.claude_helper --status --json    # 프로그램 연동용
```

### [Claude Code] AI에게 물어보기 (무료 우선 자동)
```bash
python -m command_center.claude_helper --ai "프랜차이즈 카페 시장 분석해줘"
python -m command_center.claude_helper --ai "이 코드 리뷰해줘: $(cat file.py)"
python -m command_center.claude_helper --ai "블로그 글 써줘: 치킨 프랜차이즈 비교" --provider gemini
```

### [Claude Code] 텔레그램 알림 보내기
```bash
python -m command_center.claude_helper --telegram "✅ 작업 완료: 블로그 3건 발행"
python -m command_center.claude_helper --telegram "🚨 긴급: alpha-engine 다운"
```

### [OpenClaw] 텔레그램에서 AI 대화 (폰에서)
```
@yj_ai_command_bot에게 DM:
"사이트 상태 알려줘"
"프랜차이즈 트렌드 분석해줘"
"이 기사 요약해줘: [URL]"
```

---

## ═══════════════════════════════════════
## 🔥 TIER 2: 파워 유저 명령어
## ═══════════════════════════════════════

### [Claude Code] AI 프로바이더 선택 호출
```bash
# Gemini (무료) — 일반 분석, 번역, 요약
python -m command_center.claude_helper --gemini "경쟁사 BBQ치킨 분석"

# Claude Haiku (저가 $0.001/1K) — 빠른 코딩
python -m command_center.claude_helper --claude "이 함수 리팩토링해줘: ..." --model claude-haiku-4-5-20251001

# Claude Sonnet (고가 $0.003/1K) — 최고 품질 코딩
python -m command_center.claude_helper --claude "아키텍처 설계해줘" --model claude-sonnet-4-6-20250610

# OpenAI GPT-4o-mini (저가) — 범용
python -m command_center.claude_helper --openai "마케팅 카피 써줘"

# OpenAI GPT-4o (중가) — 고급 분석
python -m command_center.claude_helper --openai "심층 시장분석" --model gpt-4o

# 프로바이더 상태 확인
python -m command_center.claude_helper --ai-providers
```

### [Claude Code] 비용 관리
```bash
python -m command_center.claude_helper --cost           # 오늘/월 비용
python -m command_center.claude_helper --cost --json     # JSON
```

### [Claude Code] 사이트 건강검진
```bash
python -m command_center.claude_helper --health          # 15개 사이트 체크
python -m command_center.claude_helper --health --json
```

### [Claude Code] 통합 검색
```bash
python -m command_center.claude_helper --search "쿠팡"   # 코드+DB+로그 검색
python -m command_center.claude_helper --search "에러"
```

---

## ═══════════════════════════════════════
## 🦞 TIER 3: OpenClaw 직접 제어
## ═══════════════════════════════════════

### 게이트웨이 관리
```bash
openclaw gateway                    # 게이트웨이 시작
openclaw health                     # 게이트웨이 상태
openclaw status                     # 채널+세션 상태
openclaw logs                       # 실시간 로그
openclaw doctor                     # 문제 진단+자동 수리
```

### 메시지 직접 전송
```bash
# 텔레그램으로 메시지 보내기
openclaw message send --channel telegram --to 8355543463 --message "안녕하세요"

# 미디어 첨부
openclaw message send --channel telegram --to 8355543463 --message "리포트" --media report.png
```

### AI 에이전트 직접 호출
```bash
# 기본 에이전트 (Gemini)
openclaw agent --message "사이트 상태 분석해줘"

# 프랜차이즈 전문 에이전트
openclaw agent --agent franchise --message "치킨 프랜차이즈 시장 분석"

# 텔레그램으로 답변 전달
openclaw agent --message "오늘 요약" --deliver --channel telegram --to 8355543463

# 사고력 레벨 조절
openclaw agent --message "심층 분석" --thinking high
```

### 크론 작업 관리 (자동화의 핵심!)
```bash
openclaw cron list                  # 모든 예약 작업 확인
openclaw cron status                # 스케줄러 상태

# 기존 크론 (이미 설정됨)
# - morning-report: 매일 08:00 오전 브리핑
# - night-report: 매일 22:00 일일 마감
# - health-check: 30분마다 사이트 체크
# - cost-alert: 6시간마다 비용 체크

# 새 크론 추가 예시
openclaw cron add --name "blog-reminder" \
  --cron "0 14 * * 1,3,5" --tz "Asia/Seoul" \
  --message "블로그 포스팅 시간! 이번 주 핫 프랜차이즈 토픽 3개 추천해줘." \
  --announce --to 8355543463 --channel telegram

# 크론 수동 실행 (테스트)
openclaw cron run <JOB_ID>

# 크론 비활성화/활성화
openclaw cron disable <JOB_ID>
openclaw cron enable <JOB_ID>
```

### 스킬 관리
```bash
openclaw skills list                # 설치된 스킬 목록
openclaw skills check               # 스킬 상태 체크

# 새 스킬 설치
npx clawhub search "keyword"        # 스킬 검색
npx clawhub install skill-name      # 설치

# 설치된 핵심 스킬:
# - gemini: Gemini AI 직접 호출
# - nano-banana-pro: 이미지 생성 (Gemini 3 Pro)
# - summarize: URL/문서 요약
# - blogwatcher: 블로그 RSS 모니터링
# - coding: 코딩 보조
# - github: GitHub 관리
# - weather: 날씨 정보
```

---

## ═══════════════════════════════════════
## 🎨 TIER 4: 고급 시나리오 조합
## ═══════════════════════════════════════

### 시나리오 1: 블로그 자동 포스팅 파이프라인
```bash
# 1) Gemini로 주제 리서치 (무료)
python -m command_center.claude_helper --gemini "2026년 프랜차이즈 카페 트렌드 TOP 5" --json > /tmp/research.json

# 2) Gemini로 블로그 초안 작성 (무료)
python -m command_center.claude_helper --gemini "위 트렌드를 바탕으로 네이버 블로그 글 써줘. SEO 최적화, 2000자, 소제목 포함" --json > /tmp/draft.json

# 3) Claude Code가 네이버 블로그에 발행 (구독 내)
# → 브라우저 제어로 직접 발행

# 4) 텔레그램 알림
python -m command_center.claude_helper --telegram "📝 블로그 발행 완료: 프랜차이즈 카페 트렌드"
```

### 시나리오 2: 경쟁사 모니터링 자동화
```bash
# OpenClaw 크론으로 매일 체크
openclaw cron add --name "competitor-watch" \
  --cron "0 9 * * *" --tz "Asia/Seoul" \
  --message "프랜차이즈 경쟁사 블로그 새 글 확인해줘. 교촌치킨, BBQ, BHC, 굽네치킨 중심으로." \
  --announce --to 8355543463 --channel telegram
```

### 시나리오 3: 이미지 생성 + 블로그
```bash
# OpenClaw 텔레그램에서:
# "나노바나나 프로로 프랜차이즈 카페 매장 인테리어 이미지 만들어줘"
# → nano-banana-pro 스킬이 Gemini 3 Pro로 이미지 생성
```

### 시나리오 4: 긴급 장애 대응
```bash
# 1) 자동 감지 (health-check 크론이 30분마다)
# 2) 텔레그램 알림 자동 수신
# 3) Claude Code로 긴급 대응:
python -m command_center.claude_helper --health
# 4) 문제 해결 후 보고:
python -m command_center.claude_helper --telegram "🔧 alpha-engine 복구 완료 (DNS 이슈)"
```

---

## ═══════════════════════════════════════
## 💰 비용 최적화 의사결정 트리
## ═══════════════════════════════════════

```
질문/작업 발생
  │
  ├─ 간단한 질문? ──→ OpenClaw 텔레그램 (Gemini 무료)
  │
  ├─ 분석/리서치? ──→ --gemini 또는 --ai (Gemini 무료)
  │
  ├─ 코딩 필요? ──→ Claude Code 직접 (구독 내, 추가비용 0)
  │
  ├─ 브라우저 필요? ──→ Claude Code + Chrome (구독 내)
  │
  ├─ 최고 품질? ──→ --claude --model claude-sonnet-4-6-20250610
  │                   (W4.5/1K tok, 필요할 때만!)
  │
  └─ 이미지 필요? ──→ OpenClaw nano-banana-pro (Gemini 무료)
```

---

## ═══════════════════════════════════════
## ⚡ 원커맨드 시스템 점검
## ═══════════════════════════════════════

```bash
# 전체 시스템 원샷 점검
python -m command_center.claude_helper --status && python -m command_center.claude_helper --health && python -m command_center.claude_helper --cost && openclaw health && openclaw cron list
```

---
> 최종 업데이트: 2026-02-24
> 시스템: Claude Code + Gemini + OpenClaw v2026.2.22-2
> 프로바이더: 6개 (Gemini/Claude Haiku/Claude Sonnet/GPT-4o-mini/GPT-4o/O1)
> 크론: 4개 (오전브리핑/야간마감/헬스체크/비용경고)
> 스킬: 13개 (gemini/nano-banana-pro/summarize/blogwatcher/coding/github + 7개)
