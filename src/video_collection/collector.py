"""
TikTok Video Collector Module

Handles downloading videos from TikTok using TikTokApi and yt-dlp for downloading.
"""

import asyncio
import os
import re
import httpx
import yt_dlp
import tempfile
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import sys

from loguru import logger
from TikTokApi import TikTokApi
from TikTokApi.exceptions import TikTokException

from src.utils.file_manager import FileManager


@dataclass
class VideoMetadata:
    """Metadata for a TikTok video."""
    
    id: str
    author: str
    desc: str
    create_time: int
    duration: float
    height: int
    width: int
    cover: str
    download_url: str
    play_url: str
    music_author: str
    music_title: str
    likes: int = 0
    shares: int = 0
    comments: int = 0
    views: int = 0
    local_path: Optional[str] = None
    url: Optional[str] = None  # Original URL
    
    def to_dict(self) -> Dict:
        """
        Convert metadata to dictionary.
        
        Returns:
            Dictionary representation of metadata
        """
        return {
            "id": self.id,
            "author": self.author,
            "desc": self.desc,
            "create_time": self.create_time,
            "duration": self.duration,
            "height": self.height,
            "width": self.width,
            "cover": self.cover,
            "download_url": self.download_url,
            "play_url": self.play_url,
            "music_author": self.music_author,
            "music_title": self.music_title,
            "likes": self.likes,
            "shares": self.shares,
            "comments": self.comments,
            "views": self.views,
            "local_path": self.local_path,
            "url": self.url
        }


class TikTokCollector:
    """Collects and downloads TikTok videos using yt-dlp only (no TikTokApi)."""
    
    def __init__(self, config, file_manager: Optional[FileManager] = None):
        """
        Initialize the TikTok collector.
        
        Args:
            config: Application configuration
            file_manager: Optional file manager instance
        """
        self.config = config
        self.tiktok_config = config.tiktok
        self.file_manager = file_manager or FileManager()
        self.video_id_patterns = [
            r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/(\d+)',
            r'https?://(?:m\.)?tiktok\.com/v/(\d+)',
            r'https?://(?:vm|vt)\.tiktok\.com/(\w+)'
        ]
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """
        Extract video ID from a TikTok URL.
        
        Args:
            url: TikTok video URL
            
        Returns:
            Video ID if found, None otherwise
        """
        for pattern in self.video_id_patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        logger.warning(f"Could not extract video ID from URL: {url}")
        return None

    def _construct_video_url(self, video_id: str) -> str:
        """
        Construct a TikTok video URL from an ID.
        
        Args:
            video_id: TikTok video ID
            
        Returns:
            TikTok video URL
        """
        return f"https://www.tiktok.com/@placeholder/video/{video_id}"
    
    def _get_video_info_sync(self, video_url: str) -> Optional[VideoMetadata]:
        """
        Get video information using yt-dlp.
        
        Args:
            video_url: TikTok video URL
            
        Returns:
            VideoMetadata object if successful, None otherwise
        """
        try:
            # Extract video ID
            video_id = self._extract_video_id(video_url)
            if not video_id:
                logger.error(f"Failed to extract video ID from URL: {video_url}")
                return None
                
            logger.debug(f"Getting info for video using yt-dlp: {video_id}")
            
            # Use yt-dlp to get video info
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'skip_download': True,
                'cookiesfrombrowser': ('chrome',)
            }
            
            # Добавляем прокси из конфигурации, если он настроен
            if hasattr(self.tiktok_config, 'proxy') and self.tiktok_config.proxy:
                ydl_opts['proxy'] = self.tiktok_config.proxy
                logger.debug(f"Using proxy: {self.tiktok_config.proxy}")
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    video_info = ydl.extract_info(video_url, download=False)
            except Exception as e:
                logger.error(f"yt-dlp info extraction error: {str(e)}")
                return None
            
            if not video_info:
                logger.error(f"Failed to get video info for ID: {video_id}")
                return None
            
            # Extract video details from yt-dlp output
            author = video_info.get("uploader", "")
            desc = video_info.get("description", "")
            create_time = int(datetime.now().timestamp())  # yt-dlp doesn't provide exact upload date
            
            duration = video_info.get("duration", 0)
            height = video_info.get("height", 0)
            width = video_info.get("width", 0)
            cover = video_info.get("thumbnail", "")
            download_url = video_info.get("url", "")
            play_url = video_info.get("url", "")
            
            music_author = video_info.get("artist", author)
            music_title = video_info.get("track", "")
            
            # yt-dlp doesn't provide these stats
            likes = 0
            shares = 0
            comments = 0
            views = video_info.get("view_count", 0)
            
            # Create metadata object
            metadata = VideoMetadata(
                id=video_id,
                author=author,
                desc=desc,
                create_time=create_time,
                duration=duration,
                height=height,
                width=width,
                cover=cover,
                download_url=download_url,
                play_url=play_url,
                music_author=music_author,
                music_title=music_title,
                likes=likes,
                shares=shares,
                comments=comments,
                views=views,
                url=video_url
            )
            
            logger.debug(f"Successfully retrieved metadata for video {video_id} using yt-dlp")
            return metadata
            
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return None
    
    def _download_video_sync(self, video_metadata: VideoMetadata) -> Optional[str]:
        """
        Download a TikTok video using provided metadata.
        
        Args:
            video_metadata: Video metadata including download URL
            
        Returns:
            Path to downloaded video if successful, None otherwise
        """
        try:
            video_id = video_metadata.id
            logger.info(f"Downloading video {video_id} by @{video_metadata.author}")
            
            # Generate output path
            output_path = self.file_manager.get_download_path(video_id)
            
            # Use original URL if available
            video_url = video_metadata.url
            
            # Download using yt-dlp
            temp_dir = tempfile.mkdtemp()
            temp_output = os.path.join(temp_dir, 'video.mp4')
            
            try:
                # Configure yt-dlp options
                ydl_opts = {
                    'format': 'best',
                    'outtmpl': temp_output,
                    'quiet': True,
                    'no_warnings': True,
                    'ignoreerrors': False,
                    'noplaylist': True,
                    'cookiesfrombrowser': ('chrome',),  # Try to use browser cookies
                    'noprogress': True
                }
                
                # Добавляем прокси из конфигурации, если он настроен
                if hasattr(self.tiktok_config, 'proxy') and self.tiktok_config.proxy:
                    ydl_opts['proxy'] = self.tiktok_config.proxy
                    logger.debug(f"Using proxy for download: {self.tiktok_config.proxy}")
                
                # Download the video
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                
                # Check if the file was downloaded
                if os.path.exists(temp_output):
                    # Move to the final destination
                    shutil.copy2(temp_output, output_path)
                    
                    # Update metadata with local path
                    video_metadata.local_path = output_path
                    logger.success(f"Video {video_id} downloaded to {output_path}")
                    
                    return output_path
                else:
                    logger.error(f"Failed to download video {video_id} with yt-dlp")
                    return None
                    
            except Exception as e:
                logger.error(f"yt-dlp download error: {str(e)}")
                return None
            finally:
                # Clean up temporary directory
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"Error removing temporary directory: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error downloading video {video_metadata.id}: {str(e)}")
            return None
    
    async def download_videos(self, urls: List[str]) -> List[VideoMetadata]:
        """
        Download videos from a list of TikTok URLs.
        
        Args:
            urls: List of TikTok video URLs
            
        Returns:
            List of VideoMetadata objects for successfully downloaded videos
        """
        try:
            # Map URLs to video IDs
            valid_urls = [url.strip() for url in urls if url.strip()]
            if not valid_urls:
                logger.error("No valid TikTok URLs provided")
                return []
            
            logger.info(f"Processing {len(valid_urls)} TikTok URLs")
            
            # Get metadata and download videos without asyncio
            # Process in a thread pool to avoid blocking
            results = []
            
            # Define a function to process a single video
            def process_video(url):
                # Get video metadata
                metadata = self._get_video_info_sync(url)
                if not metadata:
                    return None
                
                # Download the video
                download_path = self._download_video_sync(metadata)
                if not download_path:
                    return None
                
                return metadata
            
            # Process videos in a thread pool
            loop = asyncio.get_event_loop()
            
            # Process videos one by one to avoid rate limiting
            for url in valid_urls:
                video_result = await loop.run_in_executor(None, process_video, url)
                if video_result:
                    results.append(video_result)
            
            logger.info(f"Successfully downloaded {len(results)} videos")
            return results
            
        except Exception as e:
            logger.error(f"Error downloading videos: {str(e)}")
            return []


# Example usage
if __name__ == "__main__":
    import asyncio
    import sys
    from src.utils.config_loader import ConfigLoader
    from src.utils.logger_config import setup_logger
    
    # Setup logger
    setup_logger("DEBUG")
    
    # Load configuration
    config = ConfigLoader().get_config()
    
    # Create TikTok collector
    collector = TikTokCollector(config)
    
    # Example TikTok URLs
    urls = [
        "https://www.tiktok.com/@username/video/1234567890123456789",
        "https://vm.tiktok.com/abcdefg/"
    ]
    
    # Use with asyncio
    async def main():
        results = await collector.download_videos(urls)
        print(f"Downloaded {len(results)} videos")
    
    # Run with proper async handling
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main()) 