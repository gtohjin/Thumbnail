"""
Batch Runner: Job 생성 및 비동기 병렬 실행

- create_job(): 프리셋 variation 조합으로 GenerationTask 목록 생성
- run(): 비동기 semaphore 기반 병렬 실행
- retry_failed(): 실패 태스크만 재실행
- load_job(): job_meta.json에서 Job 복원
"""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from app.config import settings
from app.schemas.job import GenerationTask, Job, JobStatus
from app.schemas.product_image import ProcessedImage
from app.schemas.prompt_preset import PresetCollection
from app.services.provider_client import BaseImageProvider, get_provider
from app.services.variation_builder import VariationBuilder

console = Console()


class BatchRunner:
    def __init__(self, provider: BaseImageProvider = None):
        self.provider = provider or get_provider()
        self.max_workers = settings.max_workers

    def create_job(
        self,
        processed_image: ProcessedImage,
        collection: PresetCollection,
        product_description: str,
        total_count: int = 20,
    ) -> Job:
        """variation 조합 기반 Job 생성 및 메타 저장"""
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
        output_dir = settings.output_dir / job_id

        builder = VariationBuilder()
        variations = builder.build_variations(collection, total_count)

        tasks = []
        for preset, var_dict, prompt_template in variations:
            final_prompt = builder.finalize_prompt(prompt_template, product_description)
            task = GenerationTask(
                task_id=f"t_{str(uuid.uuid4())[:8]}",
                job_id=job_id,
                preset_id=preset.id,
                variation=var_dict,
                prompt=final_prompt,
            )
            tasks.append(task)

        job = Job(
            job_id=job_id,
            product_image_id=processed_image.product_id,
            product_image_path=processed_image.path,
            preset_collection_id=collection.id,
            total_count=total_count,
            tasks=tasks,
            output_dir=output_dir,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        self._save_job_meta(job)
        return job

    async def run(self, job: Job, negative_prompt: str = "") -> Job:
        """전체 태스크 비동기 병렬 실행"""
        job.status = JobStatus.RUNNING
        images_dir = job.output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        pending_tasks = [t for t in job.tasks if t.status == JobStatus.PENDING]

        console.print(f"\n[bold green]▶ {job.job_id} 시작[/bold green]")
        console.print(
            f"  총 {len(pending_tasks)}장 생성 | provider: [cyan]{self.provider.name}[/cyan] | workers: {self.max_workers}"
        )

        semaphore = asyncio.Semaphore(self.max_workers)

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            prog_task = progress.add_task("[cyan]이미지 생성 중...", total=len(pending_tasks))

            async def run_single(gen_task: GenerationTask):
                async with semaphore:
                    result = await self.provider.generate(
                        prompt=gen_task.prompt,
                        reference_image_path=job.product_image_path,
                        negative_prompt=negative_prompt,
                    )

                    if result.success:
                        output_path = images_dir / f"{gen_task.task_id}_{gen_task.preset_id}.png"
                        output_path.write_bytes(result.image_data)
                        gen_task.output_path = output_path
                        gen_task.status = JobStatus.COMPLETED
                        gen_task.completed_at = datetime.now()
                    else:
                        gen_task.status = JobStatus.FAILED
                        gen_task.error = result.error
                        console.print(f"  [red]✗ {gen_task.task_id}: {result.error}[/red]")

                    progress.advance(prog_task)

            await asyncio.gather(*[run_single(t) for t in pending_tasks])

        completed = len(job.completed_tasks)
        failed = len(job.failed_tasks)
        job.status = JobStatus.COMPLETED if failed == 0 else JobStatus.PARTIAL
        job.completed_at = datetime.now()

        console.print(
            f"\n[bold]완료: {completed}장 성공[/bold]"
            + (f", [red]{failed}장 실패[/red]" if failed else "")
        )
        self._save_job_meta(job)
        return job

    async def retry_failed(self, job: Job) -> Job:
        """실패한 태스크만 PENDING으로 리셋 후 재실행"""
        failed = job.failed_tasks
        if not failed:
            console.print("[yellow]재시도할 실패 태스크가 없습니다.[/yellow]")
            return job

        console.print(f"[yellow]▶ {len(failed)}개 태스크 재시도[/yellow]")
        for t in failed:
            t.status = JobStatus.PENDING
            t.retry_count += 1
            t.error = None

        return await self.run(job)

    def _save_job_meta(self, job: Job):
        meta_path = job.output_dir / "job_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(job.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)

    @classmethod
    def load_job(cls, job_id: str) -> Optional[Job]:
        job_dir = settings.output_dir / job_id
        meta_path = job_dir / "job_meta.json"
        if not meta_path.exists():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Job(**data)
