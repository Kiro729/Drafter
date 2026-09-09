# -*- coding: utf-8 -*-
"""파이프라인 튠 값. 폴더 배치와 실행 폴더는 core/paths.py.

프로젝트 루트의 .env 는 이 모듈이 임포트되는 순간 환경변수로 올라간다 (이미 설정된 변수는 유지).
그래서 아래에서 os.environ 을 읽는 설정(SCHOLAR_BACKEND, CHROME_PATH, ARCHIFY_HOME …)과
core.clients 가 실행 시점에 읽는 키·모델(OPENAI_API_KEY, OPENAI_MODEL …)이 모두 .env 값을 본다.
테스트는 DRAFTER_SKIP_DOTENV=1 로 .env 를 무시한다.
"""
import os
from pathlib import Path

from core.paths import PROJECT_ROOT, VENDOR_DIR

ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path = ENV_FILE) -> int:
    """`KEY=VALUE` 줄을 환경변수로 올린다. 이미 설정된 변수는 건드리지 않는다. 읽어 들인 개수를 돌려준다."""
    if os.environ.get("DRAFTER_SKIP_DOTENV") or not Path(path).exists():
        return 0
    loaded = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value
            loaded += 1
    return loaded


ENV_LOADED = load_env_file()        # 이 줄 아래의 os.environ.get 들이 .env 값을 본다

# LLM 모델. .env 또는 환경변수 OPENAI_MODEL 이 있으면 그 값을 쓴다 (core.clients.resolve_llm_model 이 실행 시점에 읽는다).
DEFAULT_LLM_MODEL = "gpt-5.1"

MAX_SEARCH = 3              # Collector 검색 라운드 최대 횟수 (각 A/B/C 별도). 갭 분석이 충분하다고 하면 일찍 끝난다
MAX_REVIEW_ROUNDS = 2       # 심사 라운드 최대 횟수
MAX_CLARIFY_QUESTIONS = 3   # scope 단계 진단형 질문 최대 개수 (1 Problem → 2 Solution → 3 정합성)

# ── Research 단계 (출처 카드 파이프라인, code/research/cards.py) ────────────────────
# 검색 결과 → LLM 카드 압축(요지·관련도·범위 판정) → 중복 제거 → 관련도순 선별 → 렌더링.
# writer 는 "앞 N자" 가 아니라 예산 안에서 선별된 카드 묶음을 받는다 (reporter 는 LLM 입력이 없고 카드를 인용 대조에만 쓴다).
QUERIES_PER_ROUND = 3           # 라운드당 LLM 이 만드는 검색 쿼리 수
TAVILY_MAX_RESULTS = 5          # 쿼리당 Tavily 결과 수
TAVILY_SEARCH_DEPTH = "advanced"  # basic | advanced (advanced 가 본문 추출 품질이 높다)
RAW_CONTENT_CHAR_LIMIT = 6000   # 결과 1건당 LLM 에 넣는 본문 최대 글자수
MIN_RELEVANCE = 2               # 이 미만 관련도(0~5)의 카드는 버린다
EVIDENCE_TOP_N = {"A": 12, "B": 12, "C": 15}   # 채널별 writer 에게 넘기는 카드 최대 장수
EVIDENCE_CHAR_LIMIT = 12000     # 채널별 렌더링 글자 예산 (선별은 이 안에서 멈춘다)

# ── 학술 검색 (Collector C, code/research/scholar.py) ─────────────────────────────
# 하이브리드: Liner Scholar Search 로 찾고(제목·저자·연도·학술지·인용 수), 초록은 ABSTRACT_SOURCES 순서로
# 보강한다. 기본은 arXiv 만: URL 이 arXiv 인 논문은 ID 일괄 조회로 초록을 받고, 그 외는 Liner 스니펫을 쓴다.
# Liner 키가 없으면 기존 arXiv 검색을 그대로 쓴다.
SCHOLAR_BACKEND = os.environ.get("SCHOLAR_BACKEND", "auto").lower()   # auto | liner | arxiv
LINER_API_URL = "https://platform.liner.com/api/v1/tools/search/scholar"
LINER_MAX_RESULTS = 15          # 쿼리당 Liner 결과 수 (API 상한 20)
LINER_TIMEOUT = 30              # 초
LINER_LANG = None               # None 이면 서버 기본. 쿼리는 영어이므로 보통 비워 둔다
SCHOLAR_YEARS_BACK = 5          # 최근 N년 결과를 우선 유지 (소프트 필터)
SCHOLAR_MIN_RECENT = 6          # 최근 결과가 이보다 적으면 오래된 결과도 모두 유지
# 초록 보강 시도 순서. 기본은 arXiv 만 (사용자 결정, 2026-09-08). OpenAlex 와 Semantic Scholar 코드는
# research/scholar.py 에 남아 있으므로 필요하면 ("arxiv", "openalex", "semanticscholar") 로 되살릴 수 있다.
#   openalex        — 무료, 키 불필요. 제목 검색은 재게재본에 매칭될 수 있어 연도 일치 시에만 메타데이터를 채운다.
#   semanticscholar — S2_API_KEY 가 있을 때만 동작 (키 없으면 즉시 429).
ABSTRACT_SOURCES = ("arxiv",)
ENRICH_WORKERS = 4              # OpenAlex 동시 조회 수 (openalex 를 켰을 때만 의미 있음)
OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "")        # openalex 를 켰을 때 polite pool 용 이메일
S2_API_KEY = os.environ.get("S2_API_KEY")                      # semanticscholar 를 켰을 때 필요한 키

# arXiv 직접 검색 (Liner 미사용 시, 그리고 Reviewer 의 검증 검색, Liner 결과의 초록 보강)
ARXIV_MAX_RESULTS = 8           # 쿼리당 arXiv 결과 수
ARXIV_YEARS_BACK = 5            # arXiv 1차 검색의 최근 N년 필터. 0 이면 필터 없음
ARXIV_MIN_BEFORE_FALLBACK = 4   # 날짜 필터 결과가 이보다 적으면 무필터 검색으로 보충

# arXiv 요청 관문 (research/search.py arxiv_call). 모든 arXiv 요청이 여기를 지난다.
# arXiv 이용 약관: 요청 간 3초 이상, 동시 연결 1개. 429 를 받은 뒤 짧게 재요청하면 제한이 길어지므로
# 첫 429 에는 ARXIV_429_WAIT 만큼 기다린 뒤 딱 한 번 재시도하고, 재시도도 429 면 이번 실행에서는
# arXiv 요청을 더 보내지 않는다 (남은 쿼리는 건너뛰고 파이프라인은 계속 진행).
ARXIV_MIN_INTERVAL = 4.0        # 초. 요청 간 최소 간격 (약관 3초보다 넉넉히)
ARXIV_429_WAIT = 300            # 초. 첫 429 뒤 재시도 전 대기 (5분)


def resolve_scholar_backend() -> str:
    """실제로 쓸 학술 검색 백엔드. auto 는 LINER_API_KEY 유무로 정한다."""
    if SCHOLAR_BACKEND in ("liner", "arxiv"):
        return SCHOLAR_BACKEND
    return "liner" if os.environ.get("LINER_API_KEY") else "arxiv"


# ── Write · Finalize 양식 검사 (code/write/lint.py, lint_loop.py · code/finalize/references.py) ─────
# Writer 초안·재작성 뒤와 Reporter(심사 통과본을 코드가 표기 정리한 뒤)에 코드가 양식(구조·불릿 수·글자수·문체·표기·인용)을 검사하고,
# 오류가 있을 때만 위반을 고치는 LLM 호출을 최대 아래 횟수 반복한다. 참고문헌은 LLM 이 쓰지 않고 학술 카드에서 코드가 만든다.
MAX_LINT_FIX_ROUNDS = 2

# 분량·불릿 수 검사 강도 (2026-09-09 완화). 오류(error)만 수정 루프를 돌리고, 경고(warning)는 "가능하면" 으로 전달.
#   항목 글자수: 목표 대비 +LINT_LENGTH_WARN 까지 통과, 그 위 ~ +LINT_LENGTH_ERROR 는 경고, 초과는 오류.
#              부족은 -LINT_LENGTH_UNDER_WARN 아래일 때만 경고 (근거 없는 채우기를 유도하지 않는다).
#   전체 글자수: +LINT_TOTAL_ERROR 초과만 오류.
#   불릿 수: 지정보다 LINT_BULLET_SLACK 개까지 많은 것은 경고, 그 이상은 오류. 적은 것은 경고.
#           (사용자 결정: 1~2개 초과는 허용하고 3개 이상 초과만 오류)
LINT_LENGTH_WARN = 0.15
LINT_LENGTH_ERROR = 0.35
LINT_LENGTH_UNDER_WARN = 0.30
LINT_TOTAL_ERROR = 0.20
LINT_BULLET_SLACK = 2

# Reporter(심사 뒤) 의 위반 수정본에만 적용하는 변경 범위 가드 (09-09). 심사 통과본은 다시 쓰지 않는다는 원칙을
# 코드가 보증한다: LLM 이 돌려준 수정본을 줄 단위 diff 로 재어, 허용 변경 줄 수 = max(2 × 이 값, 이 값 × 지목 건수) 를
# 넘으면 지목되지 않은 곳까지 고친 것으로 보고 버린다. None 이면 끄기. Writer 단계(초안 직후)에는 적용하지 않는다.
LINT_FIX_MAX_LINES_PER_ISSUE = 4

# ── Review 단계 ───────────────────────────────────────────────────────────────────
# 심사 판정은 코드가 결정한다: Reviewer A(내용)·B(가독성) 의 VERDICT 가 모두 PASS 여야 통과.
# Editor LLM 은 두 피드백을 Writer 가 고치기 쉬운 형태로 정리만 한다.
REVIEWER_B_SEARCH = False       # B 는 본문만 읽는다. 검증 검색은 A 만.

# ── 도해 (Archify, code/finalize/diagram_agent.py) ─────────────────────────────────
# 심사(reviewer → editor)가 끝난 본문의 연구 방법론 절로 한 번 그린다 (editor PASS → plot_framework → reporter).
# LLM 이 Archify workflow JSON 스펙을 쓰고, Archify(Node CLI) 가 검증·렌더, Playwright(Chromium) 가 SVG/PNG 를 추출한다.

# Archify 패키지 루트 (bin/archify.mjs 가 있는 폴더). 기본은 vendor/ 에 동봉된 사본이며
# 환경변수 ARCHIFY_HOME 으로 다른 위치(패키지 루트 또는 리포 루트)를 지정할 수 있다.
ARCHIFY_HOME = Path(os.environ.get("ARCHIFY_HOME") or (VENDOR_DIR / "archify"))

# Chrome/Chromium 실행 파일. 비워 두면 Playwright 번들 브라우저(playwright install chromium)를 쓴다.
CHROME_PATH = os.environ.get("CHROME_PATH") or None

MAX_DIAGRAM_REPAIR_ROUNDS = 3          # Archify 검증 실패 시 LLM 수리 최대 횟수 (Archify 자체 솔버와 동일)
DIAGRAM_QUALITY = "showcase"           # Archify 품질 프로필: 기본 검사 9개 + 마감 검사(통로 공유 등) 전부 통과해야 PASS
# showcase 가 수리 한도까지 실패하면 이 품질로 한 번 더 검증·렌더한다 (기본 검사 9개는 유지, 마감 검사만 제외).
# 그림이 빠지는 것보다 마감이 덜 된 그림이 낫다는 판단. None 이면 폴백 없이 그림 없이 진행. 결과에 "(standard)" 표시.
DIAGRAM_FALLBACK_QUALITY = "standard"
DIAGRAM_EXPORT_FORMATS = ("svg", "png")  # PNG 는 PDF 조판에, SVG 는 보관·재사용에 쓴다
