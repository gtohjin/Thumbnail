"""
Exporter: Job 결과를 export 폴더로 정리

출력물:
  export/
  ├─ top_results/       # 상위 이미지 (rank01_... ~ rank05_...)
  ├─ prompt_log.json    # 전체 프롬프트·variation·점수 로그
  └─ results_summary.csv

create_zip(): 전체 images/ + export/ 를 ZIP으로 패키징
"""

import csv
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from app.schemas.job import Job, JobStatus


class Exporter:
    def export(self, job: Job) -> Path:
        """전체 결과 export 폴더 생성"""
        export_dir = job.output_dir / "export"
        export_dir.mkdir(exist_ok=True)

        self._export_top_images(job, export_dir)
        self._export_prompt_log(job, export_dir)
        self._export_csv_summary(job, export_dir)

        return export_dir

    def _export_top_images(self, job: Job, export_dir: Path):
        top_dir = export_dir / "top_results"
        top_dir.mkdir(exist_ok=True)

        task_map = {t.task_id: t for t in job.completed_tasks}

        for rank, task_id in enumerate(job.top_results, 1):
            task = task_map.get(task_id)
            if task and task.output_path and Path(task.output_path).exists():
                dst = top_dir / f"rank{rank:02d}_{task.preset_id}_{task_id}.png"
                shutil.copy2(task.output_path, dst)

    def _export_prompt_log(self, job: Job, export_dir: Path):
        log_path = export_dir / "prompt_log.json"
        log_data = {
            "job_id": job.job_id,
            "created_at": str(job.created_at),
            "completed_at": str(job.completed_at),
            "product_image": str(job.product_image_path),
            "preset_collection": job.preset_collection_id,
            "total_generated": len(job.completed_tasks),
            "top_results": job.top_results,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "preset_id": t.preset_id,
                    "prompt": t.prompt,
                    "variation": t.variation,
                    "status": t.status,
                    "score": t.score,
                    "is_top": t.task_id in job.top_results,
                    "output_path": str(t.output_path) if t.output_path else None,
                }
                for t in job.tasks
            ],
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2, default=str)

    def _export_csv_summary(self, job: Job, export_dir: Path):
        csv_path = export_dir / "results_summary.csv"
        fieldnames = [
            "rank", "task_id", "preset_id", "score", "status",
            "is_top", "background", "shadow", "angle", "spacing", "prop",
            "prompt_snippet",
        ]

        ranked_tasks = sorted(
            job.completed_tasks, key=lambda t: t.score or 0.0, reverse=True
        )
        top_ids = set(job.top_results)

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rank, task in enumerate(ranked_tasks, 1):
                var = task.variation
                writer.writerow({
                    "rank": rank,
                    "task_id": task.task_id,
                    "preset_id": task.preset_id,
                    "score": f"{task.score:.4f}" if task.score is not None else "",
                    "status": task.status,
                    "is_top": "Y" if task.task_id in top_ids else "",
                    "background": var.get("background", ""),
                    "shadow": var.get("shadow", ""),
                    "angle": var.get("angle", ""),
                    "spacing": var.get("spacing", ""),
                    "prop": var.get("prop", ""),
                    "prompt_snippet": task.prompt[:120],
                })

    def create_zip(self, job: Job) -> Path:
        """전체 결과물을 ZIP으로 패키징"""
        export_dir = self.export(job)
        zip_path = job.output_dir / f"{job.job_id}_results.zip"

        with ZipFile(zip_path, "w") as zf:
            images_dir = job.output_dir / "images"
            if images_dir.exists():
                for img_file in images_dir.glob("*.png"):
                    zf.write(img_file, f"images/{img_file.name}")

            for f in export_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f"export/{f.relative_to(export_dir)}")

        return zip_path
