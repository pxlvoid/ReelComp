#!/usr/bin/env python3
"""
Upload Existing Compilation to YouTube

This script uploads an existing compilation video to YouTube without 
redoing the video collection and compilation process.
"""

import asyncio
import argparse
import os
from pathlib import Path

from loguru import logger

from src.utils.config_loader import ConfigLoader
from src.utils.logger_config import setup_logger
from src.youtube_uploader.uploader import YouTubeUploader
from src.thumbnail_generator.generator import ThumbnailGenerator
from src.utils.file_manager import FileManager

async def upload_existing_compilation(
    video_path: str,
    title: str,
    description: str = None,
    thumbnail_path: str = None,
    generate_thumbnail: bool = False
):
    """
    Upload an existing compilation video to YouTube.
    
    Args:
        video_path: Path to the existing compilation video
        title: Title for the video on YouTube
        description: Description for the video (uses default if None)
        thumbnail_path: Path to the thumbnail image (optional)
        generate_thumbnail: Whether to generate a new thumbnail
    
    Returns:
        YouTube video ID if successful, None otherwise
    """
    # Ensure the video file exists
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return None
    
    # Initialize components
    config = ConfigLoader().get_config()
    file_manager = FileManager()
    uploader = YouTubeUploader(config, file_manager)
    
    # Generate default description if not provided
    if not description:
        description = (
            "🎬 Welcome to TikTok Weekly Top!\n\n"
            "Dive into this week's best TikToks—handpicked viral hits, hilarious moments, and trending clips "
            "that everyone's talking about! No endless scrolling needed; we've got your weekly dose of TikTok right here.\n\n"
            "🔥 New compilations uploaded weekly—Subscribe and turn notifications on!\n\n"
            "Disclaimer: All videos featured belong to their original creators. Follow and support their amazing content on TikTok!\n\n"
            "📧 Want your video featured? Submit your TikTok link in the comments below!\n\n"
            "Tags: #TikTok #TikTokWeekly #TikTokCompilation #Trending #ViralVideos #WeeklyTop"
        )
    
    # Generate thumbnail if requested and none provided
    if generate_thumbnail and not thumbnail_path:
        logger.info("Generating thumbnail from video...")
        thumbnail_generator = ThumbnailGenerator(config, file_manager)
        
        # Generate output path
        output_filename = f"thumbnail_{Path(video_path).stem}.jpg"
        output_path = os.path.join(config.app.thumbnail_dir, output_filename)
        
        # Generate the thumbnail
        thumbnail_path = await thumbnail_generator.create_basic_thumbnail(
            title=title,
            output_path=output_path
        )
        
        if thumbnail_path:
            logger.success(f"Generated thumbnail: {thumbnail_path}")
        else:
            logger.warning("Failed to generate thumbnail, continuing without it")
    
    # Authenticate with YouTube
    logger.info("Authenticating with YouTube...")
    if not uploader.authenticate():
        logger.error("YouTube authentication failed")
        return None
    
    # Upload the video
    logger.info(f"Uploading video '{title}' to YouTube...")
    video_id = uploader.upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=["tiktok", "compilation", "highlights", "trending", "funny", "viral"],
        privacy_status=config.youtube.privacy_status,
        thumbnail_path=thumbnail_path
    )
    
    if video_id:
        logger.success(f"Video uploaded successfully with ID: {video_id}")
        
        # Create or update playlist
        playlist_name = "TikTok Compilations"
        playlist_id = uploader.create_playlist(
            title=playlist_name,
            description="Automated TikTok compilations",
            privacy_status=config.youtube.privacy_status
        )
        
        if playlist_id:
            uploader.add_to_playlist(playlist_id, video_id)
            logger.info(f"Added to playlist: {playlist_name}")
            
        # Get the video URL
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Video URL: {video_url}")
        
        return video_id
    else:
        logger.error("Failed to upload video to YouTube")
        return None


async def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Upload existing compilation to YouTube")
    parser.add_argument("--video", "-v", required=True, help="Path to the existing compilation video")
    parser.add_argument("--title", "-t", required=True, help="Title for the YouTube video")
    parser.add_argument("--description", "-d", help="Description for the YouTube video")
    parser.add_argument("--thumbnail", "-i", help="Path to the thumbnail image")
    parser.add_argument("--generate-thumbnail", "-g", action="store_true", help="Generate a thumbnail from the video")
    parser.add_argument("--log-level", "-l", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    args = parser.parse_args()
    
    # Setup logger
    setup_logger(args.log_level)
    
    # Upload the video
    video_id = await upload_existing_compilation(
        video_path=args.video,
        title=args.title,
        description=args.description,
        thumbnail_path=args.thumbnail,
        generate_thumbnail=args.generate_thumbnail
    )
    
    if video_id:
        print(f"\nUpload successful! Video ID: {video_id}")
        print(f"Video URL: https://www.youtube.com/watch?v={video_id}")
        return 0
    else:
        print("\nUpload failed. See logs for details.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code) 