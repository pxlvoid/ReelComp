"""
File Manager Utility

Handles file operations including creating directories, saving files,
and cleaning up temporary files.
"""

import os
import time
import uuid
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union, BinaryIO

from loguru import logger

from src.utils.config_loader import AppConfig, Config


class FileManager:
    """
    Manages file operations for the application including creation and cleanup of directories.
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the file manager with application configuration.
        
        Args:
            config: Application configuration
        """
        from src.utils.config_loader import ConfigLoader
        
        self.config = config or ConfigLoader().get_config()
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """
        Ensure all required directories exist.
        """
        os.makedirs(self.config.app.download_dir, exist_ok=True)
        os.makedirs(self.config.app.compilation_dir, exist_ok=True)
        os.makedirs(self.config.app.thumbnail_dir, exist_ok=True)
        os.makedirs(self.config.app.temp_dir, exist_ok=True)
        os.makedirs(self.config.app.shorts_dir, exist_ok=True)
        logger.debug("Ensured all required directories exist")
    
    def get_temp_path(self, extension: str = "mp4") -> str:
        """
        Generate a path for a temporary file.
        
        Args:
            extension: File extension without dot
            
        Returns:
            Path to the temporary file
        """
        filename = f"{uuid.uuid4()}.{extension}"
        return str(Path(self.config.app.temp_dir) / filename)
    
    def get_download_path(self, video_id: str, extension: str = "mp4") -> str:
        """
        Generate a path for a downloaded video.
        
        Args:
            video_id: TikTok video ID
            extension: File extension without dot
            
        Returns:
            Path to the downloaded video
        """
        filename = f"{video_id}.{extension}"
        return str(Path(self.config.app.download_dir) / filename)
    
    def get_compilation_path(self, prefix: str = "compilation", extension: str = "mp4", title: str = None) -> str:
        """
        Generate a path for a compilation video.
        
        Args:
            prefix: Filename prefix
            extension: File extension without dot
            title: Optional title to use in filename
            
        Returns:
            Path to the compilation video
        """
        timestamp = int(time.time())
        
        if title:
            # Convert title to a filename-friendly format
            safe_title = "".join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in title)
            safe_title = safe_title.strip().replace(' ', '_')
            filename = f"{prefix}_{safe_title}_{timestamp}.{extension}"
        else:
            filename = f"{prefix}_{timestamp}.{extension}"
            
        return str(Path(self.config.app.compilation_dir) / filename)
    
    def get_thumbnail_path(self, prefix: str = "thumbnail", extension: str = "jpg", title: str = None) -> str:
        """
        Generate a path for a thumbnail image.
        
        Args:
            prefix: Filename prefix
            extension: File extension without dot
            title: Optional title to use in filename
            
        Returns:
            Path to the thumbnail image
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if title:
            # Convert title to a filename-friendly format
            safe_title = "".join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in title)
            safe_title = safe_title.strip().replace(' ', '_')
            filename = f"{prefix}_{safe_title}_{timestamp}.{extension}"
        else:
            filename = f"{prefix}_{timestamp}.{extension}"
            
        return str(Path(self.config.app.thumbnail_dir) / filename)
    
    def get_short_path(self, video_id: str, title: str = None) -> str:
        """
        Generate a path for a YouTube Short video.
        
        Args:
            video_id: TikTok video ID
            title: Optional title to use in filename
            
        Returns:
            Path for the YouTube Short video
        """
        timestamp = int(time.time())
        
        if title:
            # Convert title to a filename-friendly format
            safe_title = "".join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in title)
            safe_title = safe_title.strip().replace(' ', '_')
            filename = f"short_{safe_title}_{timestamp}.mp4"
        else:
            filename = f"short_{video_id}_{timestamp}.mp4"
            
        return str(Path(self.config.app.shorts_dir) / filename)
    
    def save_file(self, content: Union[bytes, BinaryIO], file_path: str) -> str:
        """
        Save content to a file.
        
        Args:
            content: File content as bytes or file-like object
            file_path: Path to save the file
            
        Returns:
            Path to the saved file
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            if isinstance(content, bytes):
                with open(file_path, "wb") as f:
                    f.write(content)
            else:
                # Assume file-like object
                with open(file_path, "wb") as f:
                    shutil.copyfileobj(content, f)
            
            logger.debug(f"Saved file: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error saving file {file_path}: {str(e)}")
            raise
    
    def cleanup_temp_files(self) -> None:
        """
        Clean up temporary files created during processing.
        """
        try:
            # Check if temporary directory exists
            if not os.path.exists(self.config.app.temp_dir):
                logger.debug("No temporary directory to clean up")
                return
            
            # Get list of files
            files = [f for f in os.listdir(self.config.app.temp_dir) 
                    if os.path.isfile(os.path.join(self.config.app.temp_dir, f))]
            
            if not files:
                logger.debug("No temporary files to clean up")
                return
            
            # Remove each file
            for file in files:
                file_path = os.path.join(self.config.app.temp_dir, file)
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed temporary file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file {file_path}: {str(e)}")
            
            logger.debug(f"Cleaned up {len(files)} temporary files")
            
        except Exception as e:
            logger.warning(f"Error during temporary file cleanup: {str(e)}")
    
    def cleanup_old_files(self, days: int = 30) -> Dict[str, int]:
        """
        Clean up files older than the specified number of days.
        
        Args:
            days: Age threshold in days
            
        Returns:
            Dictionary with counts of removed files by type
        """
        counts = {
            "download": 0,
            "compilation": 0,
            "thumbnail": 0
        }
        
        # Calculate cutoff time
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_time = cutoff.timestamp()
        
        try:
            # Clean up downloaded videos
            for file_path in Path(self.config.app.download_dir).glob("*"):
                if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    counts["download"] += 1
            
            # Clean up compilation videos
            for file_path in Path(self.config.app.compilation_dir).glob("*"):
                if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    counts["compilation"] += 1
            
            # Clean up thumbnails
            for file_path in Path(self.config.app.thumbnail_dir).glob("*"):
                if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    counts["thumbnail"] += 1
            
            logger.info(f"Removed {sum(counts.values())} old files: "
                        f"{counts['download']} downloads, "
                        f"{counts['compilation']} compilations, "
                        f"{counts['thumbnail']} thumbnails")
            
            return counts
            
        except Exception as e:
            logger.error(f"Error cleaning up old files: {str(e)}")
            return counts


# Example usage
if __name__ == "__main__":
    from src.utils.logger_config import setup_logger
    setup_logger()
    
    # Create file manager
    file_manager = FileManager()
    
    # Generate paths
    temp_path = file_manager.get_temp_path()
    download_path = file_manager.get_download_path("test_video_id")
    compilation_path = file_manager.get_compilation_path()
    thumbnail_path = file_manager.get_thumbnail_path()
    short_path = file_manager.get_short_path("test_video_id")
    
    # Print paths
    logger.info(f"Temp path: {temp_path}")
    logger.info(f"Download path: {download_path}")
    logger.info(f"Compilation path: {compilation_path}")
    logger.info(f"Thumbnail path: {thumbnail_path}")
    logger.info(f"Short path: {short_path}")
    
    # Cleanup
    file_manager.cleanup_temp_files()
    file_manager.cleanup_old_files(days=7) 