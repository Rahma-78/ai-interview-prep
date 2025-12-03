"""History management for interview preparation pipeline."""

import json
import shutil
from pathlib import Path
from typing import Optional
import logging

from app.core.config import settings


class HistoryManager:
    """
    Manages history folder operations.
    
    Responsibilities:
    - Create history directories
    - Save JSON data to history
    - Clear old history folders
    
    Follows Single Responsibility Principle.
    """
    
    def __init__(self, base_path: str = "app/history", logger: Optional[logging.Logger] = None):
        """
        Initialize history manager.
        
        Args:
            base_path: Base directory for history storage
            logger: Logger instance (optional)
        """
        self.base_path = Path(base_path)
        self.logger = logger or logging.getLogger(__name__)
    
    def clear_all(self) -> None:
        """
        Clear all history folders.
        
        This is called at the start of each run to ensure only
        the current run's data exists.
        """
        if not self.base_path.exists():
            return
        
        try:
            for run_dir in self.base_path.iterdir():
                if run_dir.is_dir():
                    try:
                        shutil.rmtree(run_dir)
                        self.logger.info(f"Cleared history: {run_dir.name}")
                    except Exception as e:
                        self.logger.warning(f"Failed to clear {run_dir.name}: {e}")
        except Exception as e:
            self.logger.warning(f"Error during history cleanup: {e}")
    
    def save(self, data: dict, filename: str, run_id: str) -> None:
        """
        Save data to history folder.
        
        Args:
            data: Dictionary to save as JSON
            filename: Output filename (e.g., 'extracted_skills.json')
            run_id: Run identifier (timestamp)
        """
        if not settings.ENABLE_DATA_HISTORY:
            self.logger.debug("History disabled, skipping save")
            return
        
        run_dir = self.base_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = run_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Saved: {file_path}")
    
    def get_latest_run_id(self) -> Optional[str]:
        """
        Get the ID of the most recent run.
        
        Returns:
            Run ID (timestamp) or None if no runs exist
        """
        if not self.base_path.exists():
            return None
        
        run_dirs = [d for d in self.base_path.iterdir() if d.is_dir()]
        if not run_dirs:
            return None
        
        # Sort by directory name (timestamp format: YYYYMMDD_HHMMSS)
        latest = max(run_dirs, key=lambda d: d.name)
        return latest.name
    
    def load(self, filename: str, run_id: Optional[str] = None) -> Optional[dict]:
        """
        Load data from history folder.
        
        Args:
            filename: File to load (e.g., 'extracted_skills.json')
            run_id: Run identifier (uses latest if not provided)
            
        Returns:
            Loaded data or None if not found
        """
        if run_id is None:
            run_id = self.get_latest_run_id()
            if run_id is None:
                return None
        
        file_path = self.base_path / run_id / filename
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load {file_path}: {e}")
            return None
