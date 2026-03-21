# 스마트스토어 대표이미지 자동 생성 - Streamlit UI
# 실행: streamlit run ui/app.py

import asyncio
import io
import sys
import tempfile
from pathlib import Path

import streamlit as st
from PIL import Image

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.image_preprocess import ImagePreprocessor
from app.services.preset_manager import PresetManager
from app.services.provider_client import get_provider
from app.services.batch_runner import BatchRunner
from app.services.ranker import ImageRanker
from app.services.exporter import Exporter
from app.config import settings

# ── 페이지 설정 ────────────────────────────────────────────────
st.set_page_config(
    page_title="스마트스토어 대표이미지 생성기",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.top-badge {
    background: linear-gradient(90deg, #FFD700, #FFA500);
    color: #000;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}
.rank-badge {
    background: #1e90ff;
    color: #fff;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 12px;
}
.score-text {
    color: #00cc66;
    font-weight: bold;
    font-size: 14px;
}
div[data-testid="stImage"] img {
    border-radius: 8px;
    border: 1px solid #e0e0e0;
}
</style>
""", unsafe_allow_html=True)

# ── 세션 상태 초기화 ───────────────────────────────────────────
for key, default in {
    "job": None,
    "generated": False,
    "processed_path": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ── 사이드바: 설정 패널 ────────────────────────────────────────
with st.sidebar:
    st.title("🛍️ 대표이미지 생성기")
    st.markdown("---")

    # 1. 이미지 업로드
    st.subheader("📁 1. 누끼 이미지 업로드")
    uploaded_file = st.file_uploader(
        "PNG 파일 (투명 배경 권장)",
        type=["png", "jpg", "jpeg"],
        help="누끼 처리된 투명 배경 PNG를 업로드하세요."
    )

    if uploaded_file:
        preview_img = Image.open(uploaded_file)
        st.image(preview_img, caption="업로드된 이미지", use_container_width=True)
        st.caption(f"{preview_img.width}×{preview_img.height}px | {uploaded_file.type}")
        uploaded_file.seek(0)

    st.markdown("---")

    # 2. 상품 설명
    st.subheader("📝 2. 상품 설명")
    product_desc = st.text_input(
        "상품명 / 설명",
        placeholder="예: 스킨케어 세럼 50ml, 무선 이어폰, 텀블러",
        help="프롬프트의 {product} 자리에 삽입됩니다."
    )

    st.markdown("---")

    # 3. 프리셋 선택
    st.subheader("🎨 3. 프리셋")
    manager = PresetManager(presets_dir=ROOT / "presets")
    collection_ids = manager.list_collections()

    preset_id = st.selectbox(
        "프리셋 컬렉션",
        options=collection_ids,
        format_func=lambda x: manager.get_collection(x).name if manager.get_collection(x) else x,
    )

    if preset_id:
        col = manager.get_collection(preset_id)
        with st.expander("프리셋 목록 보기"):
            for p in col.presets:
                st.markdown(f"**{p.name}** (weight: {p.weight})")
                st.caption(p.description)

    st.markdown("---")

    # 4. 생성 설정
    st.subheader("⚙️ 4. 생성 설정")
    count = st.slider("생성 수량", min_value=5, max_value=30, value=20, step=1)
    top_n = st.slider("상위 선별 수", min_value=3, max_value=10, value=5, step=1)

    provider_name = st.selectbox(
        "Provider",
        options=["openai", "stability"],
        index=0,
    )

    st.markdown("---")

    # 5. 생성 버튼
    generate_btn = st.button(
        "🚀 대표이미지 생성 시작",
        type="primary",
        use_container_width=True,
        disabled=not (uploaded_file and product_desc),
    )

    if not uploaded_file:
        st.caption("⬆️ 이미지를 먼저 업로드하세요.")
    elif not product_desc:
        st.caption("⬆️ 상품 설명을 입력하세요.")


# ── 메인 영역 ──────────────────────────────────────────────────
st.title("🛍️ 스마트스토어 대표이미지 자동 생성")

if not uploaded_file or not product_desc:
    # 초기 화면
    st.markdown("### 시작하려면 왼쪽 패널에서 이미지와 상품 설명을 입력하세요.")
    st.markdown("""
    **사용 방법:**
    1. 👈 왼쪽에서 누끼 PNG 이미지 업로드
    2. 상품 설명 입력 (예: 스킨케어 세럼 50ml)
    3. 프리셋·수량 설정 후 **생성 시작** 클릭
    4. 생성된 이미지 중 상위 후보 확인 및 다운로드

    **프리셋 구성 (5종):**
    | 슬롯 | 이름 | 특징 |
    |---|---|---|
    | 1 | 화이트 배경 기본형 | 가장 범용, 스마트스토어 기본 기준 |
    | 2 | 소프트 그림자형 | 자연 그림자로 입체감 |
    | 3 | 프리미엄 미니멀형 | 넓은 여백, 고급 브랜드 톤 |
    | 4 | 감성 배경 최소형 | 텍스처 배경, 따뜻한 무드 |
    | 5 | 디스플레이 스탠드형 | 받침대 연출, 카탈로그 스타일 |
    """)
    st.stop()


# ── 생성 실행 ──────────────────────────────────────────────────
if generate_btn:
    st.session_state.generated = False
    st.session_state.job = None

    collection = manager.get_collection(preset_id)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / uploaded_file.name
        tmp_path.write_bytes(uploaded_file.read())

        # 전처리
        status_box = st.empty()
        status_box.info("📐 이미지 전처리 중...")

        preprocessor = ImagePreprocessor(canvas_size=settings.canvas_size)
        try:
            product_img = preprocessor.load_and_validate(tmp_path)
        except Exception as e:
            st.error(f"이미지 오류: {e}")
            st.stop()

        processed_dir = settings.output_dir / "_preprocessed"
        processed = preprocessor.preprocess(product_img, processed_dir)
        st.session_state.processed_path = str(processed.path)

        # 배치 실행
        status_box.info(f"🎨 이미지 생성 중... (총 {count}장, 잠시 기다려 주세요)")

        progress_bar = st.progress(0, text="생성 준비 중...")

        try:
            provider = get_provider(provider_name)
        except ValueError as e:
            st.error(str(e))
            st.stop()

        runner = BatchRunner(provider=provider)
        job = runner.create_job(processed, collection, product_desc, total_count=count)

        # 진행률 추적을 위한 커스텀 실행
        completed_count = [0]
        total = len(job.tasks)

        async def run_with_progress():
            import asyncio
            from app.schemas.job import JobStatus
            from datetime import datetime

            semaphore = asyncio.Semaphore(settings.max_workers)
            images_dir = job.output_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

            async def run_single(task):
                async with semaphore:
                    result = await provider.generate(
                        prompt=task.prompt,
                        reference_image_path=job.product_image_path,
                        negative_prompt=collection.global_negative_prompt,
                    )
                    if result.success:
                        out_path = images_dir / f"{task.task_id}_{task.preset_id}.png"
                        out_path.write_bytes(result.image_data)
                        task.output_path = out_path
                        task.status = JobStatus.COMPLETED
                        task.completed_at = datetime.now()
                    else:
                        task.status = JobStatus.FAILED
                        task.error = result.error
                    completed_count[0] += 1
                    pct = completed_count[0] / total
                    progress_bar.progress(pct, text=f"생성 중... {completed_count[0]}/{total}장")

            await asyncio.gather(*[run_single(t) for t in job.tasks])

        asyncio.run(run_with_progress())

        from app.schemas.job import JobStatus
        from datetime import datetime
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now()
        runner._save_job_meta(job)

        # 랭킹
        progress_bar.progress(1.0, text="상위 이미지 선별 중...")
        ranker = ImageRanker()
        job = ranker.rank_job(job, top_n=top_n)

        # 내보내기
        exporter = Exporter()
        exporter.export(job)

        status_box.success(f"✅ 완료! {len(job.completed_tasks)}장 생성, 상위 {top_n}장 선별")
        progress_bar.empty()

        st.session_state.job = job
        st.session_state.generated = True


# ── 결과 출력 ──────────────────────────────────────────────────
if st.session_state.generated and st.session_state.job:
    job = st.session_state.job
    top_ids = set(job.top_results)

    completed = job.completed_tasks
    ranked = sorted(completed, key=lambda t: t.score or 0.0, reverse=True)

    # 탭 구성
    tab_top, tab_all, tab_log = st.tabs([
        f"⭐ 상위 {len(job.top_results)}장",
        f"📋 전체 {len(completed)}장",
        "📄 프롬프트 로그"
    ])

    # ── 상위 결과 탭
    with tab_top:
        st.markdown(f"### ⭐ 상위 {len(job.top_results)}장 — 스마트스토어 대표이미지 후보")

        top_tasks = [t for t in ranked if t.task_id in top_ids]
        cols = st.columns(min(len(top_tasks), 3))

        for i, task in enumerate(top_tasks):
            col = cols[i % len(cols)]
            if task.output_path and Path(task.output_path).exists():
                with col:
                    img = Image.open(task.output_path)
                    st.image(img, use_container_width=True)
                    st.markdown(
                        f'<span class="top-badge">★ #{i+1}</span> '
                        f'<span class="score-text">점수 {task.score:.3f}</span>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"{task.preset_id}")

                    # 개별 다운로드 버튼
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    st.download_button(
                        label=f"💾 다운로드",
                        data=buf.getvalue(),
                        file_name=f"rank{i+1:02d}_{task.preset_id}.png",
                        mime="image/png",
                        key=f"dl_top_{task.task_id}",
                        use_container_width=True,
                    )

        # 전체 ZIP 다운로드
        st.markdown("---")
        export_dir = job.output_dir / "export"
        exporter = Exporter()
        zip_path = exporter.create_zip(job)
        if zip_path.exists():
            st.download_button(
                label="📦 전체 결과 ZIP 다운로드",
                data=zip_path.read_bytes(),
                file_name=f"{job.job_id}_results.zip",
                mime="application/zip",
                use_container_width=True,
            )

    # ── 전체 결과 탭
    with tab_all:
        st.markdown(f"### 📋 전체 생성 결과 ({len(completed)}장)")

        cols_per_row = 4
        for row_start in range(0, len(ranked), cols_per_row):
            row_tasks = ranked[row_start: row_start + cols_per_row]
            cols = st.columns(cols_per_row)
            for col, task in zip(cols, row_tasks):
                if task.output_path and Path(task.output_path).exists():
                    rank = ranked.index(task) + 1
                    is_top = task.task_id in top_ids
                    with col:
                        img = Image.open(task.output_path)
                        st.image(img, use_container_width=True)
                        badge = f'<span class="top-badge">★ #{rank}</span>' if is_top else f'<span class="rank-badge">#{rank}</span>'
                        st.markdown(
                            f'{badge} <span class="score-text">{task.score:.3f}</span>',
                            unsafe_allow_html=True,
                        )
                        st.caption(task.preset_id.replace("preset_0", "P").replace("_", " "))
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        st.download_button(
                            label="💾",
                            data=buf.getvalue(),
                            file_name=f"rank{rank:02d}_{task.task_id}.png",
                            mime="image/png",
                            key=f"dl_all_{task.task_id}",
                            use_container_width=True,
                        )

    # ── 프롬프트 로그 탭
    with tab_log:
        st.markdown("### 📄 프롬프트 및 variation 로그")

        st.markdown(f"**Job ID:** `{job.job_id}`")
        st.markdown(f"**출력 폴더:** `{job.output_dir}`")

        log_data = []
        for rank, task in enumerate(ranked, 1):
            log_data.append({
                "순위": rank,
                "상위여부": "★" if task.task_id in top_ids else "",
                "프리셋": task.preset_id,
                "점수": f"{task.score:.4f}" if task.score else "-",
                "배경": task.variation.get("background", ""),
                "그림자": task.variation.get("shadow", ""),
                "각도": task.variation.get("angle", ""),
                "여백": task.variation.get("spacing", ""),
                "소품": task.variation.get("prop", ""),
            })

        import pandas as pd
        df = pd.DataFrame(log_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("**프롬프트 전문 (상위 결과)**")
        for task in ranked[:top_n]:
            with st.expander(f"#{ranked.index(task)+1} [{task.preset_id}] 점수: {task.score:.3f}"):
                st.code(task.prompt, language=None)
