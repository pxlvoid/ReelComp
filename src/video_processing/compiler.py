"""
Video Compiler Module

Handles the compilation of TikTok videos into a single highlight video with
transitions, intro/outro clips, and dynamic metadata.
"""

import asyncio
import os
import random
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple

import ffmpeg
import numpy as np
from loguru import logger
try:
    from moviepy.editor import (
        AudioFileClip,
        ColorClip,
        CompositeVideoClip,
        VideoFileClip,
        TextClip,
        concatenate_videoclips,
    )
    import moviepy.video.fx.all as vfx
except ImportError as e:
    logger.error(f"Error importing moviepy: {str(e)}")
    raise

from src.utils.file_manager import FileManager
from src.video_collection.collector import VideoMetadata


class TransitionMaker:
    """Creates transitions between video clips."""
    
    @staticmethod
    def fade(clip1, clip2, duration=0.5):
        """
        Create a fade transition between two clips.
        
        Args:
            clip1: First video clip
            clip2: Second video clip
            duration: Duration of the transition in seconds
            
        Returns:
            A single clip with the transition applied
        """
        clip1 = clip1.crossfadeout(duration)
        clip2 = clip2.crossfadein(duration)
        return concatenate_videoclips([clip1, clip2], method="compose")
    
    @staticmethod
    def crossfade(clip1, clip2, duration=1.0):
        """
        Create a crossfade transition between two clips.
        
        Args:
            clip1: First video clip
            clip2: Second video clip
            duration: Duration of the transition in seconds
            
        Returns:
            A single clip with the transition applied
        """
        clip1 = clip1.set_end(clip1.duration - duration)
        clip2 = clip2.set_start(duration)
        
        crossfade = CompositeVideoClip([
            clip1, 
            clip2.set_start(clip1.duration - duration)
        ])
        
        return crossfade
    
    @staticmethod
    def slide_left(clip1, clip2, duration=1.0):
        """
        Create a slide left transition between two clips.
        
        Args:
            clip1: First video clip
            clip2: Second video clip
            duration: Duration of the transition in seconds
            
        Returns:
            A single clip with the transition applied
        """
        def slide_func(t):
            """Slide position function."""
            if t < duration:
                return {'x': t * clip1.w / duration - clip1.w, 'y': 0}
            else:
                return {'x': 0, 'y': 0}
        
        clip2 = clip2.set_position(slide_func)
        clip2 = clip2.set_start(clip1.duration - duration)
        
        return CompositeVideoClip([clip1, clip2]).set_duration(clip1.duration + clip2.duration - duration)
    
    @staticmethod
    def slide_right(clip1, clip2, duration=1.0):
        """
        Create a slide right transition between two clips.
        
        Args:
            clip1: First video clip
            clip2: Second video clip
            duration: Duration of the transition in seconds
            
        Returns:
            A single clip with the transition applied
        """
        def slide_func(t):
            """Slide position function."""
            if t < duration:
                return {'x': clip1.w - t * clip1.w / duration, 'y': 0}
            else:
                return {'x': 0, 'y': 0}
        
        clip2 = clip2.set_position(slide_func)
        clip2 = clip2.set_start(clip1.duration - duration)
        
        return CompositeVideoClip([clip1, clip2]).set_duration(clip1.duration + clip2.duration - duration)
    
    @staticmethod
    def zoom_in(clip1, clip2, duration=1.0):
        """
        Create a zoom in transition between two clips.
        
        Args:
            clip1: First video clip
            clip2: Second video clip
            duration: Duration of the transition in seconds
            
        Returns:
            A single clip with the transition applied
        """
        clip2 = clip2.set_start(clip1.duration - duration)
        clip2 = clip2.fx(vfx.resize, lambda t: max(0.1, min(1, t/duration)) if t < duration else 1)
        
        return CompositeVideoClip([clip1, clip2]).set_duration(clip1.duration + clip2.duration - duration)
    
    @staticmethod
    def zoom_out(clip1, clip2, duration=1.0):
        """
        Create a zoom out transition between two clips.
        
        Args:
            clip1: First video clip
            clip2: Second video clip
            duration: Duration of the transition in seconds
            
        Returns:
            A single clip with the transition applied
        """
        clip1 = clip1.fx(vfx.resize, lambda t: max(0.1, min(1, 1-(t-(clip1.duration-duration))/duration)) if t > clip1.duration-duration else 1)
        clip2 = clip2.set_start(clip1.duration - duration)
        
        return CompositeVideoClip([clip1, clip2]).set_duration(clip1.duration + clip2.duration - duration)


class VideoCompiler:
    """Compiles TikTok videos into a highlight video."""
    
    # Available transition types
    TRANSITIONS = {
        "fade": TransitionMaker.fade,
        "crossfade": TransitionMaker.crossfade, 
        "slide_left": TransitionMaker.slide_left,
        "slide_right": TransitionMaker.slide_right,
        "zoom_in": TransitionMaker.zoom_in,
        "zoom_out": TransitionMaker.zoom_out,
        "random": None,  # Will be chosen randomly
    }
    
    def __init__(self, config, file_manager: Optional[FileManager] = None):
        """
        Initialize the video compiler.
        
        Args:
            config: Application configuration object
            file_manager: Optional file manager instance
        """
        self.config = config
        self.app_config = config.app
        self.file_manager = file_manager or FileManager()
    
    def _create_title_clip(
        self,
        text: str,
        duration: float = 3.0,
        font_size: int = 70,
        color: str = "white",
        bg_color: str = "black",
        fontname: str = "Arial"
    ) -> VideoFileClip:
        """
        Create a title clip with text.
        
        Args:
            text: Text to display
            duration: Duration of the clip in seconds
            font_size: Font size
            color: Text color
            bg_color: Background color
            fontname: Font name
            
        Returns:
            VideoFileClip with the title
        """
        # Create a text clip
        txt_clip = TextClip(
            text,
            fontsize=font_size,
            color=color,
            font=fontname,
            align="center",
            size=(self.app_config.video_width, None)
        )
        
        # Create a background clip
        bg_clip = ColorClip(
            size=(self.app_config.video_width, self.app_config.video_height),
            color=bg_color
        )
        bg_clip = bg_clip.set_duration(duration)
        
        # Position the text in the center of the background
        txt_clip = txt_clip.set_duration(duration)
        txt_clip = txt_clip.set_position("center")
        
        # Combine the text and background
        result = CompositeVideoClip([bg_clip, txt_clip])
        
        return result
    
    async def _prepare_clip(
        self,
        video_metadata: VideoMetadata,
        output_size: Tuple[int, int] = None,
        add_title: bool = True,
        max_duration: float = None,
        title_duration: float = 1.5,
        volume: float = 1.0
    ) -> Optional[VideoFileClip]:
        """
        Prepare a TikTok video clip for compilation with side panels and branding.
        
        Args:
            video_metadata: Video metadata
            output_size: Target size (width, height) for the clip
            add_title: Whether to add title overlay
            max_duration: Maximum duration of the clip in seconds (None for full length)
            title_duration: Duration of the title overlay in seconds
            volume: Volume multiplier for the clip's audio
            
        Returns:
            Prepared video clip
        """
        try:
            video_path = video_metadata.local_path
            if not video_path or not os.path.exists(video_path):
                logger.error(f"Video file not found: {video_path}")
                return None
            
            # Get target size - ensure we use 16:9 landscape format (1920x1080)
            if output_size is None:
                output_size = (1920, 1080)
            
            # Load video
            clip = VideoFileClip(video_path)
            
            # Trim clip if max_duration is specified and video is longer
            if max_duration is not None and clip.duration > max_duration:
                # Keep the middle section
                clip = clip.subclip(clip.duration / 2 - max_duration / 2, clip.duration / 2 + max_duration / 2)
                logger.info(f"Trimmed video {video_metadata.id} to {max_duration}s (from {clip.duration:.2f}s)")
            else:
                logger.info(f"Using full length of video {video_metadata.id} ({clip.duration:.2f}s)")
            
            # Create a black background for our 16:9 format
            bg = ColorClip(output_size, color=(0, 0, 0))
            bg = bg.set_duration(clip.duration)
            
            # Calculate the size for the vertical video in the center
            # For vertical TikTok videos (9:16) inside a 16:9 frame
            # We maintain the original aspect ratio while fitting within the height
            center_height = output_size[1]
            center_width = int(center_height * 9/16)  # Width for 9:16 ratio
            
            # Resize clip to fit in the center while maintaining aspect ratio
            resized_clip = clip.resize(height=center_height)
            
            # If the video is too wide after resizing, crop it to 9:16 aspect ratio
            if resized_clip.w > center_width:
                # Center crop
                x_center = resized_clip.w / 2
                x1 = x_center - center_width / 2
                x2 = x_center + center_width / 2
                resized_clip = resized_clip.crop(x1=x1, x2=x2, y1=0, y2=center_height)
            
            # Position the clip in the center
            x_pos = (output_size[0] - center_width) / 2
            resized_clip = resized_clip.set_position((x_pos, 0))
            
            # Create side panels with black background
            left_panel_width = int(x_pos)
            right_panel_width = int(x_pos)
            
            left_panel = ColorClip((left_panel_width, output_size[1]), color=(0, 0, 0))
            left_panel = left_panel.set_duration(clip.duration)
            left_panel = left_panel.set_position((0, 0))
            
            right_panel = ColorClip((right_panel_width, output_size[1]), color=(0, 0, 0))
            right_panel = right_panel.set_duration(clip.duration)
            right_panel = right_panel.set_position((output_size[0] - right_panel_width, 0))
            
            # Create TikTok logos for left and right sides
            logo_base_size = int(min(left_panel_width * 0.5, output_size[1] * 0.3))
            
            # Left TikTok logo - "Tik" with pink color (#ff0050)
            left_logo = TextClip(
                "Tik",
                fontsize=logo_base_size,
                color='#ff0050',  # TikTok pink/red color
                font='Arial-Bold',
                align="center"
            )
            left_logo = left_logo.set_duration(clip.duration)
            left_logo = left_logo.set_position((left_panel_width/2 - left_logo.w/2, output_size[1]/2 - left_logo.h/2))
            
            # Right TikTok logo - "Tok" with cyan color (#00f2ea)
            right_logo = TextClip(
                "Tok",
                fontsize=logo_base_size,
                color='#00f2ea',  # TikTok teal/cyan color
                font='Arial-Bold',
                align="center"
            )
            right_logo = right_logo.set_duration(clip.duration)
            right_logo = right_logo.set_position((output_size[0] - right_panel_width/2 - right_logo.w/2, output_size[1]/2 - right_logo.h/2))
            
            # Add TikTok watermark
            tiktok_watermark = TextClip(
                "TikTok",
                fontsize=24,
                color='white',
                font='Arial-Bold',
                align="center"
            )
            tiktok_watermark = tiktok_watermark.set_duration(clip.duration)
            tiktok_watermark = tiktok_watermark.set_position((output_size[0] - tiktok_watermark.w - 10, 10))
            
            # Creator username at the top
            elements = [bg, left_panel, right_panel, resized_clip, left_logo, right_logo, tiktok_watermark]
            
            if add_title and self.app_config.include_video_titles and video_metadata.author:
                creator_text = TextClip(
                    f"@{video_metadata.author}",
                    fontsize=36,
                    color='white',
                    font='Arial-Bold',
                    align="center"
                )
                creator_text = creator_text.set_duration(clip.duration)
                creator_text = creator_text.set_position(("center", 30))
                elements.append(creator_text)
            
            # Add channel name at the bottom
            channel_name = "TikTokWeeklyTop"
            channel_text = TextClip(
                f"@{channel_name}",
                fontsize=48,
                color='white',
                font='Arial-Bold',
                align="center"
            )
            channel_text = channel_text.set_duration(clip.duration)
            channel_text = channel_text.set_position(("center", output_size[1] - 100))
            elements.append(channel_text)
            
            # Add subscribe text
            subscribe_text = TextClip(
                "SUBSCRIBE FOR MORE TIKTOK COMPILATIONS",
                fontsize=30,
                color='white',
                font='Arial-Bold',
                align="center"
            )
            subscribe_text = subscribe_text.set_duration(clip.duration)
            subscribe_text = subscribe_text.set_position(("center", output_size[1] - 50))
            elements.append(subscribe_text)
            
            # Small TikTok logo in bottom right corner
            tiktok_icon = TextClip(
                "♫",  # Musical note symbol
                fontsize=36,
                color='#00f2ea',  # TikTok teal color
                font='Arial-Bold',
                align="center"
            )
            tiktok_icon = tiktok_icon.set_duration(clip.duration)
            tiktok_icon = tiktok_icon.set_position((output_size[0] - 50, output_size[1] - 50))
            elements.append(tiktok_icon)
            
            # Create the final composite
            final_clip = CompositeVideoClip(elements)
            
            # Adjust volume
            if clip.audio is not None and volume != 1.0:
                final_clip = final_clip.volumex(volume)
            
            return final_clip
            
        except Exception as e:
            logger.error(f"Error preparing clip {video_metadata.id}: {str(e)}")
            return None
    
    def _select_transition(self, transition_type: str = None) -> callable:
        """
        Select a transition function.
        
        Args:
            transition_type: Type of transition to use, or "random" for a random one
            
        Returns:
            Transition function
        """
        if transition_type is None:
            transition_type = self.app_config.transition_type
        
        if transition_type == "random" or transition_type not in self.TRANSITIONS:
            # Choose a random transition, excluding "random" itself
            transition_types = list(self.TRANSITIONS.keys())
            transition_types.remove("random")
            transition_type = random.choice(transition_types)
        
        return self.TRANSITIONS[transition_type]
    
    async def create_compilation(
        self,
        video_metadata_list: List[VideoMetadata],
        title: Optional[str] = None,
        max_videos: Optional[int] = None,
        min_videos: Optional[int] = None,
        transition_type: Optional[str] = None,
        include_intro: Optional[bool] = None,
        include_outro: Optional[bool] = None,
        intro_path: Optional[str] = None,
        outro_path: Optional[str] = None,
        max_duration_per_clip: Optional[float] = None
    ) -> Optional[str]:
        """
        Create a compilation video from a list of TikTok videos using direct ffmpeg commands.
        
        Args:
            video_metadata_list: List of video metadata
            title: Title for the compilation
            max_videos: Maximum number of videos to include
            min_videos: Minimum number of videos required
            transition_type: Type of transition to use between clips
            include_intro: Whether to include an intro clip
            include_outro: Whether to include an outro clip
            intro_path: Path to intro video file
            outro_path: Path to outro video file
            max_duration_per_clip: Maximum duration per clip in seconds (None to use full length)
            
        Returns:
            Path to the compilation video if successful, None otherwise
        """
        try:
            # Use config defaults if not specified
            if max_videos is None:
                max_videos = self.app_config.max_videos_per_compilation
            
            if min_videos is None:
                min_videos = self.app_config.min_videos_per_compilation
            
            if include_intro is None:
                include_intro = self.app_config.use_intro
            
            if include_outro is None:
                include_outro = self.app_config.use_outro
            
            if intro_path is None:
                intro_path = self.app_config.intro_path
            
            if outro_path is None:
                outro_path = self.app_config.outro_path
            
            if max_duration_per_clip is None:
                max_duration_per_clip = self.app_config.max_duration_per_clip
            
            # Ensure we have enough videos
            if len(video_metadata_list) < min_videos:
                logger.error(f"Not enough videos for compilation. Need at least {min_videos}, got {len(video_metadata_list)}")
                return None
            
            # Select videos to include (up to max_videos)
            selected_videos = video_metadata_list[:max_videos]
            logger.info(f"Selected {len(selected_videos)} videos for compilation")
            
            # Create a temporary directory for processing
            temp_dir = Path(self.app_config.temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # List to store all video segments
            final_clips = []
            
            # Set correct output dimensions for 16:9 horizontal format
            output_width = 1920
            output_height = 1080
            
            # Add title slide if needed
            if title:
                # Create title text
                txt_clip = TextClip(
                    title,
                    fontsize=70,
                    color="white",
                    font="Arial",
                    bg_color="black",
                    align="center",
                    size=(output_width, None)
                )
                txt_clip = txt_clip.set_position("center")
                txt_clip = txt_clip.set_duration(3.0)
                
                # Create a background
                bg_clip = ColorClip(
                    size=(output_width, output_height),
                    color=(0, 0, 0)
                )
                bg_clip = bg_clip.set_duration(3.0)
                
                # Combine text and background
                title_clip = CompositeVideoClip([bg_clip, txt_clip])
                final_clips.append(title_clip)
                logger.info("Added title slide to compilation")
            
            # Process intro if specified
            if include_intro and intro_path and os.path.exists(intro_path):
                try:
                    intro_clip = VideoFileClip(intro_path)
                    # Resize intro to match output dimensions
                    intro_clip = intro_clip.resize(width=output_width, height=output_height)
                    final_clips.append(intro_clip)
                    logger.info(f"Added intro clip: {intro_path}")
                except Exception as e:
                    logger.error(f"Error loading intro clip {intro_path}: {str(e)}")
            
            # Process each video with watermarks
            for i, metadata in enumerate(selected_videos):
                try:
                    # Prepare clip with watermarks - use 16:9 aspect ratio
                    prepared_clip = await self._prepare_clip(
                        metadata,
                        output_size=(output_width, output_height),
                        add_title=True,
                        max_duration=max_duration_per_clip
                    )
                    
                    if prepared_clip:
                        final_clips.append(prepared_clip)
                        logger.info(f"Added video {i+1}/{len(selected_videos)}: {metadata.id} (duration: {prepared_clip.duration:.2f}s)")
                    else:
                        logger.warning(f"Failed to prepare video {metadata.id}")
                except Exception as e:
                    logger.error(f"Error processing video {metadata.id}: {str(e)}")
            
            # Process outro if specified
            if include_outro and outro_path and os.path.exists(outro_path):
                try:
                    outro_clip = VideoFileClip(outro_path)
                    # Resize outro to match output dimensions
                    outro_clip = outro_clip.resize(width=output_width, height=output_height)
                    final_clips.append(outro_clip)
                    logger.info(f"Added outro clip: {outro_path}")
                except Exception as e:
                    logger.error(f"Error loading outro clip {outro_path}: {str(e)}")
            
            if not final_clips:
                logger.error("No valid video clips to compile")
                return None
            
            # Generate output path with title if provided
            timestamp = int(datetime.datetime.now().timestamp())
            if title:
                # Create safe filename from title
                safe_title = "".join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in title)
                safe_title = safe_title.strip().replace(' ', '_')
                output_filename = f"compilation_{safe_title}_{timestamp}.mp4"
            else:
                output_filename = f"compilation_{timestamp}.mp4"
                
            output_path = os.path.join(self.app_config.compilation_dir, output_filename)
            
            # Ensure the output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Concatenate clips
            logger.info(f"Concatenating {len(final_clips)} video clips")
            final_compilation = concatenate_videoclips(final_clips, method="chain")
            
            # Write the final video - force 16:9 aspect ratio
            logger.info(f"Writing compilation to {output_path}")
            final_compilation.write_videofile(
                output_path,
                codec="libx264",
                audio_codec="aac",
                bitrate="4000k",
                audio_bitrate="192k",
                threads=4,
                preset="medium"
            )
            
            # Close all clips to free resources
            for clip in final_clips:
                clip.close()
            
            logger.success(f"Compilation created: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error creating compilation: {str(e)}")
            return None


# Example usage
if __name__ == "__main__":
    import datetime
    from src.utils.config_loader import ConfigLoader
    from src.utils.logger_config import setup_logger
    
    # Setup logger
    setup_logger("DEBUG")
    
    # Load configuration
    config = ConfigLoader().get_config()
    
    # Create video compiler
    compiler = VideoCompiler(config)
    
    # Example metadata
    metadata = VideoMetadata(
        id="123456",
        author="example_user",
        desc="Example video",
        create_time=int(datetime.datetime.now().timestamp()),
        duration=10.0,
        height=1920,
        width=1080,
        cover="",
        download_url="",
        play_url="",
        music_author="",
        music_title="",
        local_path="example.mp4"
    )
    
    # Create compilation
    async def main():
        result = await compiler.create_compilation([metadata], title="Test Compilation")
        print(f"Compilation created: {result}")
    
    asyncio.run(main()) 