import json
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.schemas.prompt_preset import PresetCollection, PromptPreset


class PresetManager:
    def __init__(self, presets_dir: Path = None):
        self.presets_dir = presets_dir or settings.presets_dir
        self._collections: dict[str, PresetCollection] = {}
        self._load_all()

    def _load_all(self):
        """presets 디렉토리의 모든 JSON 파일 로드"""
        if not self.presets_dir.exists():
            return
        for json_file in self.presets_dir.rglob("*.json"):
            try:
                self._load_file(json_file)
            except Exception as e:
                print(f"[WARNING] 프리셋 로드 실패 {json_file.name}: {e}")

    def _load_file(self, path: Path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        collection = PresetCollection(**data)
        self._collections[collection.id] = collection

    def get_collection(self, collection_id: str) -> Optional[PresetCollection]:
        return self._collections.get(collection_id)

    def list_collections(self) -> List[str]:
        return list(self._collections.keys())

    def get_preset(self, collection_id: str, preset_id: str) -> Optional[PromptPreset]:
        collection = self.get_collection(collection_id)
        if not collection:
            return None
        for p in collection.presets:
            if p.id == preset_id:
                return p
        return None

    def save_collection(self, collection: PresetCollection, path: Path = None):
        if path is None:
            path = self.presets_dir / f"{collection.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(collection.model_dump(), f, ensure_ascii=False, indent=2)
        self._collections[collection.id] = collection
        print(f"프리셋 저장 완료: {path}")

    def reload(self):
        """디렉토리에서 프리셋 다시 로드"""
        self._collections.clear()
        self._load_all()
