"""
Configuration Loader Utility

Loads configuration from environment variables and JSON files, using Pydantic for validation.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Any

from dotenv import load_dotenv
from loguru import logger
from pydantic_settings import BaseSettings


class TikTokConfig(BaseSettings):
    """TikTok API configuration settings."""
    
    # TikTok authentication tokens
    ms_token: Optional[str] = None
    session_id: Optional[str] = None
    
    # Simplified TikTok configuration (no API credentials needed)
    
    class Config:
        env_prefix = "TIKTOK_"
        extra = "ignore"


class YoutubeConfig(BaseSettings):
    """YouTube API configuration settings."""
    
    # Basic YouTube settings
    default_category_id: str = "22"  # People & Blogs
    privacy_status: str = "private"
    client_secrets_path: str = "credentials/client_secret.json"
    token_path: str = "credentials/youtube_token.json"
    
    class Config:
        env_prefix = "YOUTUBE_"
        extra = "ignore"


class AppConfig(BaseSettings):
    """Application configuration settings."""
    
    debug: bool = False
    log_level: str = "INFO"
    base_dir: str = "data"
    temp_dir: str = "data/temp"
    download_dir: str = "data/downloaded_videos"
    compilation_dir: str = "data/compilations"
    thumbnail_dir: str = "data/thumbnails"
    shorts_dir: str = "data/shorts"  # Directory for YouTube Shorts
    log_dir: str = "logs"
    max_file_age_days: int = 7
    max_videos_per_compilation: int = 200
    min_videos_per_compilation: int = 3
    video_width: int = 1080
    video_height: int = 1920
    use_intro: bool = False
    intro_path: Optional[str] = None
    use_outro: bool = False
    outro_path: Optional[str] = None
    include_video_titles: bool = True
    transition_type: str = "random"
    thumbnail_width: int = 1280
    thumbnail_height: int = 720
    auto_upload: bool = False
    assets_dir: str = "data/assets"
    max_duration_per_clip: Optional[float] = None  # None means use full video length
    
    class Config:
        env_prefix = "APP_"
        extra = "ignore"


class Config:
    """Main configuration class combining all settings."""
    
    def __init__(self):
        """Initialize the Config object with default settings."""
        self.tiktok = TikTokConfig()
        self.youtube = YoutubeConfig()
        self.app = AppConfig()


class ConfigLoader:
    """Loads and manages application configuration."""
    
    def __init__(self, env_file: Optional[str] = ".env"):
        """
        Initialize the configuration loader.
        
        Args:
            env_file: Path to .env file (optional)
        """
        self.env_file = env_file
        
        # Load environment variables from .env file if it exists and is not None
        if env_file is not None and os.path.exists(env_file):
            load_dotenv(dotenv_path=env_file)
            logger.debug(f"Loaded environment variables from {env_file}")
    
    def get_config(self, config_file: Optional[str] = None) -> Config:
        """
        Get application configuration from environment and optional config file.
        
        Args:
            config_file: Optional path to JSON configuration file
            
        Returns:
            Config object with all configuration settings
        """
        # Create config object
        config = Config()
        
        # Load from config file if provided and it exists
        if config_file is not None and os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    file_config = json.load(f)
                
                logger.info(f"Loaded configuration from {config_file}")
                
                # Update tiktok config
                if "tiktok" in file_config:
                    for key, value in file_config["tiktok"].items():
                        if hasattr(config.tiktok, key):
                            setattr(config.tiktok, key, value)
                
                # Update youtube config
                if "youtube" in file_config:
                    for key, value in file_config["youtube"].items():
                        if hasattr(config.youtube, key):
                            setattr(config.youtube, key, value)
                
                # Update app config
                if "app" in file_config:
                    for key, value in file_config["app"].items():
                        if hasattr(config.app, key):
                            setattr(config.app, key, value)
                            
            except Exception as e:
                logger.error(f"Error loading config file {config_file}: {str(e)}")
        
        return config


# Example usage
if __name__ == "__main__":
    # Load configuration
    config_loader = ConfigLoader()
    config = config_loader.get_config()
    
    # Print configuration
    print(f"TikTok Config: {config.tiktok}")
    print(f"YouTube Config: {config.youtube}")
    print(f"App Config: {config.app}") 