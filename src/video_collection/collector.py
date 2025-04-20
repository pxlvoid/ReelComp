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
    """Collects and downloads TikTok videos."""
    
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
        self.api = None
        self.initialized = False
        self.video_id_patterns = [
            r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/(\d+)',
            r'https?://(?:m\.)?tiktok\.com/v/(\d+)',
            r'https?://(?:vm|vt)\.tiktok\.com/(\w+)'
        ]
    
    async def _initialize_api(self) -> None:
        """Initialize the TikTok API."""
        try:
            if not self.initialized:
                # For TikTokApi v7.0.0, initialization is different
                logger.info("Initializing TikTokApi v7.0.0")
                self.api = TikTokApi()
                
                # Create a temporary data directory if it doesn't exist
                data_dir = Path("./data/tiktok_api")
                data_dir.mkdir(parents=True, exist_ok=True)
                
                # The API requires browser data to be accessible
                ms_tokens = None
                if self.tiktok_config.ms_token:
                    ms_tokens = [self.tiktok_config.ms_token]
                
                # In v7.0.0, session IDs are handled as cookies, not as a direct parameter
                cookies = None
                if self.tiktok_config.session_id:
                    cookies = [{"msToken": self.tiktok_config.ms_token if self.tiktok_config.ms_token else "",
                              "sessionid": self.tiktok_config.session_id}]
                
                # In v7.0.0, 'proxies' is a list, not 'proxy'
                await self.api.create_sessions(
                    num_sessions=1, 
                    headless=True,
                    ms_tokens=ms_tokens,
                    cookies=cookies,
                    browser="chromium"
                )
                
                self.initialized = True
                logger.debug("TikTok API initialized successfully")
        
        except Exception as e:
            logger.error(f"Error initializing TikTok API: {str(e)}")
            raise
    
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
    
    async def _get_video_info(self, video_id: str, original_url: str = None) -> Optional[VideoMetadata]:
        """
        Get video information from TikTok API.
        
        Args:
            video_id: TikTok video ID
            original_url: Original TikTok URL
            
        Returns:
            VideoMetadata object if successful, None otherwise
        """
        try:
            # Ensure API is initialized
            if not self.initialized:
                await self._initialize_api()
            
            # Get video by ID
            logger.debug(f"Getting info for video: {video_id}")
            
            # In TikTokApi v7.0.0, we need to use the URL
            video_url = original_url if original_url else self._construct_video_url(video_id)
            
            # Create a video object with the URL
            video_obj = self.api.video(url=video_url)
            
            # Get the video info
            video_data = await video_obj.info()
            
            if not video_data:
                logger.error(f"Failed to get video info for ID: {video_id}")
                return None
            
            # Extract video details, the structure is different in v7
            author = video_data.get("author", {}).get("uniqueId", "")
            desc = video_data.get("desc", "")
            create_time = video_data.get("createTime", 0)
            
            video_info = video_data.get("video", {})
            duration = video_info.get("duration", 0)
            height = video_info.get("height", 0)
            width = video_info.get("width", 0)
            cover = video_info.get("cover", "")
            download_url = video_info.get("downloadAddr", "")
            play_url = video_info.get("playAddr", "")
            
            music_info = video_data.get("music", {})
            music_author = music_info.get("authorName", "")
            music_title = music_info.get("title", "")
            
            stats = video_data.get("stats", {})
            likes = stats.get("diggCount", 0)
            shares = stats.get("shareCount", 0)
            comments = stats.get("commentCount", 0)
            views = stats.get("playCount", 0)
            
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
            
            logger.debug(f"Successfully retrieved metadata for video {video_id}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error getting video info for {video_id}: {str(e)}")
            return None
    
    def _download_with_ytdlp(self, url: str, output_path: str) -> bool:
        """
        Download a video using yt-dlp.
        
        Args:
            url: Video URL to download
            output_path: Path to save the video
            
        Returns:
            True if download was successful, False otherwise
        """
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
            
            # Download the video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Check if the file was downloaded
            if os.path.exists(temp_output):
                # Move to the final destination
                shutil.copy2(temp_output, output_path)
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"yt-dlp download error: {str(e)}")
            return False
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Error removing temporary directory: {str(e)}")
    
    async def _download_video(self, video_metadata: VideoMetadata) -> Optional[str]:
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
            
            # Download using yt-dlp (synchronously)
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, 
                self._download_with_ytdlp, 
                video_url, 
                output_path
            )
            
            if not success:
                logger.error(f"Failed to download video {video_id} with yt-dlp")
                return None
            
            # Update metadata with local path
            video_metadata.local_path = output_path
            logger.success(f"Video {video_id} downloaded to {output_path}")
            
            return output_path
            
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
            # Ensure API is initialized
            await self._initialize_api()
            
            # Map URLs to video IDs
            url_to_id = {}
            for url in urls:
                url = url.strip()
                video_id = self._extract_video_id(url)
                if video_id:
                    url_to_id[url] = video_id
            
            if not url_to_id:
                logger.error("No valid TikTok URLs provided")
                return []
            
            logger.info(f"Extracted {len(url_to_id)} video IDs from URLs")
            
            # Get metadata and download videos
            results = []
            for url, video_id in url_to_id.items():
                # Get video metadata
                metadata = await self._get_video_info(video_id, url)
                if metadata:
                    # Download the video
                    download_path = await self._download_video(metadata)
                    if download_path:
                        results.append(metadata)
            
            logger.info(f"Successfully downloaded {len(results)} videos")
            return results
            
        except Exception as e:
            logger.error(f"Error downloading videos: {str(e)}")
            return []
        finally:
            # Close the API sessions when done
            if self.initialized and self.api:
                try:
                    await self.api.close_sessions()
                except Exception as e:
                    logger.warning(f"Error closing TikTok API sessions: {str(e)}")


# Example usage
if __name__ == "__main__":
    import asyncio
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
    
    # Download videos
    async def main():
        results = await collector.download_videos(urls)
        print(f"Downloaded {len(results)} videos")
    
    asyncio.run(main()) 