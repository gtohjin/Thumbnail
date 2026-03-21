# 스마트스토어 대표이미지 자동 생성 시스템

누끼 처리된 상품 PNG를 참조 이미지로 사용해
**고정 프리셋 5개 × variation 조합**으로 대표이미지 후보를 한 번에 20장 생성하는 배치 파이프라인.

---

## 빠른 시작

```bash
# 1. 환경 설정
cp .env.example .env
# .env 파일에 API 키 입력

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 이미지 생성
python -m app.main generate \
  --image product_nukki.png \
  --product "스킨케어 세럼 50ml" \
  --count 20

# 4. 결과 확인
# outputs/job_YYYYMMDD_.../export/top_results/ 폴더
```

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| 누끼 이미지 전처리 | 알파 채널 기준 상품 영역 감지 → 1024×1024 정사각형 정규화 |
| 프롬프트 프리셋 | 5개 고정 슬롯 (화이트 기본·그림자·프리미엄·감성·스탠드) |
| Variation 빌더 | 배경·그림자·각도·여백·소품 파라미터 조합으로 다양성 생성 |
| 병렬 생성 | asyncio + Semaphore 기반 병렬 API 호출 |
| 자동 랭킹 | 식별성·중심성·배경 단순성·중복 제거 기반 상위 5장 선별 |
| 결과 내보내기 | top_results 폴더, prompt_log.json, results_summary.csv, ZIP |

---

## CLI 명령어

```bash
# 이미지 생성
python -m app.main generate \
  --image <누끼_PNG_경로> \
  --product <상품_설명> \
  --preset smartstore_default \
  --count 20 \
  --provider openai \
  --top 5

# 기존 Job 재평가
python -m app.main rerank <job_id>

# 결과 내보내기
python -m app.main export <job_id> [--zip]

# 목록 조회
python -m app.main list-jobs
python -m app.main list-presets
```

---

## 지원 Provider

| Provider | 모델 | 특징 |
|---|---|---|
| `openai` (기본) | DALL-E 2 images/edits | 참조 이미지 + 프롬프트 편집 |
| `stability` | SDXL img2img | 참조 이미지 strength 기반 |

`.env`의 `DEFAULT_PROVIDER` 또는 `--provider` 옵션으로 선택.

---

## 프리셋 5개 슬롯

| # | ID | 이름 | 특징 |
|---|---|---|---|
| 1 | preset_01_white_basic | 화이트 배경 기본형 | 범용, 스마트스토어 기본 기준 |
| 2 | preset_02_soft_shadow | 소프트 그림자형 | 자연 그림자로 입체감 |
| 3 | preset_03_premium_minimal | 프리미엄 미니멀형 | 넓은 여백, 고급 브랜드 톤 |
| 4 | preset_04_lifestyle_minimal | 감성 배경 최소형 | 텍스처 배경, 따뜻한 무드 |
| 5 | preset_05_display_stand | 디스플레이 스탠드형 | 받침대 연출, 카탈로그 스타일 |

`presets/smartstore_default.json` 에서 직접 편집 가능.

---

## 출력 구조

```
outputs/
└─ job_20240101_120000_ab12/
   ├─ job_meta.json          ← Job 전체 메타 + 태스크 목록
   ├─ images/                ← 생성 이미지 전체 (20장)
   └─ export/
      ├─ top_results/        ← 상위 5장 (rank01~05)
      ├─ prompt_log.json     ← 프롬프트·variation·점수 로그
      └─ results_summary.csv ← 랭킹 요약 CSV
```

---

## 환경 변수 (.env)

```env
OPENAI_API_KEY=sk-...
STABILITY_API_KEY=sk-...
DEFAULT_PROVIDER=openai
CANVAS_SIZE=1024
MAX_WORKERS=4
```

---

## 테스트

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## 새 Provider 추가

`app/services/provider_client.py`에서 `BaseImageProvider` 상속:

```python
class MyProvider(BaseImageProvider):
    @property
    def name(self) -> str:
        return "myprovider"

    async def generate(self, prompt, reference_image_path, negative_prompt=""):
        # 구현
        ...
```

`get_provider()`에 `elif name == "myprovider": return MyProvider()` 추가.
