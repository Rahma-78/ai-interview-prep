"""Run metadata tracking for interview preparation pipeline."""

import time
from datetime import datetime
from typing import List, Dict, Any

from app.core.config import settings


class RunMetadata:
    """
    Encapsulates run metadata.
    
    Responsibilities:
    - Track run statistics
    - Manage run state
    - Format metadata for storage
    
    Follows Data Class pattern and Single Responsibility Principle.
    """
    
    def __init__(self, run_id: str):
        """
        Initialize run metadata.
        
        Args:
            run_id: Unique run identifier (timestamp)
        """
        self.run_id = run_id
        self.timestamp = datetime.now().isoformat()
        self.status = "running"
        self.skill_count = 0
        self.batch_count = 0
        self.batches_succeeded = 0
        self.batches_failed = 0
        self.errors: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self.config = {
            "skill_count": settings.SKILL_COUNT,
            "batch_size": settings.BATCH_SIZE,
            "max_concurrent_batches": settings.MAX_CONCURRENT_BATCHES
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert metadata to dictionary.
        
        Returns:
            Dictionary with all metadata fields
        """
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "skill_count": self.skill_count,
            "batch_count": self.batch_count,
            "batches_succeeded": self.batches_succeeded,
            "batches_failed": self.batches_failed,
            "errors": self.errors,
            "duration_seconds": round(time.time() - self.start_time, 2),
            "config": self.config
        }
    
    def mark_success(self) -> None:
        """Mark run as successful."""
        self.status = "success"
    
    def mark_failed(self) -> None:
        """Mark run as failed."""
        self.status = "failed"
    
    def add_error(self, stage: str, error: str, skills: List[str] = None) -> None:
        """
        Add error to metadata.
        
        Args:
            stage: Stage where error occurred (e.g., 'extraction', 'batch_1')
            error: Error message
            skills: Optional list of skills being processed when error occurred
        """
        error_entry = {"stage": stage, "error": error}
        if skills:
            error_entry["skills"] = skills
        self.errors.append(error_entry)
    
    def increment_success(self) -> None:
        """Increment successful batch counter."""
        self.batches_succeeded += 1
    
    def increment_failure(self) -> None:
        """Increment failed batch counter."""
        self.batches_failed += 1
