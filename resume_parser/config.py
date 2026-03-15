from pathlib import Path


class Settings:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self.base_dir = base_dir
        self.data_dir = base_dir / "data"
        self.upload_dir = self.data_dir / "uploads"
        self.db_path = self.data_dir / "resume_parser.db"
        self.review_threshold = 0.75


settings = Settings()
