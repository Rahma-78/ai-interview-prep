"""Resume file validation for interview preparation pipeline."""

from pathlib import Path
from typing import Set, Dict
import logging

from app.core.config import settings


class FileValidator:
    """
    Validates resume files.
    
    Responsibilities:
    - Check file exists
    - Validate file size (configurable max)
    - Verify file extension
    - Validate MIME type via magic bytes
    
    Follows Single Responsibility Principle.
    """
    
    VALID_EXTENSIONS: Set[str] = {'.pdf', '.txt', '.doc', '.docx'}
    
    # Magic bytes for MIME type detection
    MIME_SIGNATURES: Dict[str, bytes] = {
        '.pdf': b'%PDF',
        '.doc': b'\xd0\xcf\x11\xe0',  # OLE Compound Document
        '.docx': b'PK\x03\x04',        # ZIP (Office Open XML)
    }
    
    # Default max file size: 10MB
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
    
    def __init__(self, logger: logging.Logger = None, max_size_mb: int = None):
        """
        Initialize file validator.
        
        Args:
            logger: Logger instance (optional)
            max_size_mb: Maximum file size in MB (optional, defaults to 10MB)
        """
        self.logger = logger or logging.getLogger(__name__)
        if max_size_mb is not None:
            self.MAX_FILE_SIZE_BYTES = max_size_mb * 1024 * 1024
    
    def validate(self, file_path: str) -> None:
        """
        Validate resume file.
        
        Args:
            file_path: Path to file to validate
            
        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file is invalid (empty, wrong extension, bad MIME, too large)
        """
        path = Path(file_path)
        
        # Check existence
        if not path.exists():
            raise FileNotFoundError(f"Resume file not found: {file_path}")
        
        # Check it's a file
        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        
        file_size = path.stat().st_size
        
        # Check file size (empty)
        if file_size == 0:
            raise ValueError(f"Resume file is empty: {file_path}")
        
        # Check file size (too large)
        if file_size > self.MAX_FILE_SIZE_BYTES:
            max_mb = self.MAX_FILE_SIZE_BYTES / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            raise ValueError(
                f"Resume file too large: {actual_mb:.1f}MB exceeds {max_mb:.0f}MB limit"
            )
        
        # Check extension
        extension = path.suffix.lower()
        if extension not in self.VALID_EXTENSIONS:
            raise ValueError(
                f"Invalid file extension: {extension}. "
                f"Supported: {', '.join(self.VALID_EXTENSIONS)}"
            )
        
        # Validate MIME type via magic bytes (skip for .txt)
        if extension != '.txt':
            self._validate_mime_type(path, extension)
        
        self.logger.info(f"Resume validation passed: {file_path} ({file_size / 1024:.1f}KB)")
    
    def _validate_mime_type(self, path: Path, extension: str) -> None:
        """
        Validate file MIME type by checking magic bytes.
        
        Args:
            path: Path to file
            extension: File extension
            
        Raises:
            ValueError: If MIME type doesn't match extension
        """
        expected_signature = self.MIME_SIGNATURES.get(extension)
        if expected_signature is None:
            return  # No signature to check
        
        try:
            with open(path, 'rb') as f:
                file_header = f.read(len(expected_signature))
            
            if not file_header.startswith(expected_signature):
                raise ValueError(
                    f"File content does not match {extension} format. "
                    f"File may be corrupted or have wrong extension."
                )
        except IOError as e:
            self.logger.warning(f"Could not read file for MIME validation: {e}")
            # Don't fail on read errors, just log warning

