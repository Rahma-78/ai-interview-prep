"""Resume file validation for interview preparation pipeline."""

from pathlib import Path
from typing import Set
import logging


class FileValidator:
    """
    Validates resume files.
    
    Responsibilities:
    - Check file exists
    - Validate file size
    - Verify file extension
    
    Follows Single Responsibility Principle.
    """
    
    VALID_EXTENSIONS: Set[str] = {'.pdf', '.txt', '.doc', '.docx'}
    
    def __init__(self, logger: logging.Logger = None):
        """
        Initialize file validator.
        
        Args:
            logger: Logger instance (optional)
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def validate(self, file_path: str) -> None:
        """
        Validate resume file.
        
        Args:
            file_path: Path to file to validate
            
        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file is invalid (empty or wrong extension)
        """
        path = Path(file_path)
        
        # Check existence
        if not path.exists():
            raise FileNotFoundError(f"Resume file not found: {file_path}")
        
        # Check it's a file
        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        
        # Check file size
        if path.stat().st_size == 0:
            raise ValueError(f"Resume file is empty: {file_path}")
        
        # Check extension
        if path.suffix.lower() not in self.VALID_EXTENSIONS:
            raise ValueError(
                f"Invalid file extension: {path.suffix}. "
                f"Supported: {', '.join(self.VALID_EXTENSIONS)}"
            )
        
        self.logger.info(f"Resume validation passed: {file_path}")
