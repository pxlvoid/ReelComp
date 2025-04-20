"""
Thumbnail Generator Module

Handles the generation of engaging thumbnails for YouTube videos by extracting
frames from original videos, selecting the most engaging frames, and adding text overlays.
"""

import asyncio
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from loguru import logger
from moviepy.editor import VideoFileClip
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps

from src.utils.file_manager import FileManager
from src.video_collection.collector import VideoMetadata


class FrameScorer:
    """Scores frames based on their potential to create engaging thumbnails."""
    
    @staticmethod
    def calculate_brightness(frame: np.ndarray) -> float:
        """
        Calculate the brightness of a frame.
        
        Args:
            frame: Frame as numpy array in BGR format
            
        Returns:
            Brightness score between 0 and 1
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Calculate brightness (0-255)
        brightness = np.mean(gray)
        
        # Normalize to 0-1 range
        normalized = brightness / 255.0
        
        # Score is higher for moderate brightness (0.4-0.7)
        if 0.4 <= normalized <= 0.7:
            score = normalized
        else:
            # Penalize too dark or too bright images
            score = max(0, 1 - abs(normalized - 0.55) * 2)
        
        return score
    
    @staticmethod
    def calculate_contrast(frame: np.ndarray) -> float:
        """
        Calculate the contrast of a frame.
        
        Args:
            frame: Frame as numpy array in BGR format
            
        Returns:
            Contrast score between 0 and 1
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Calculate standard deviation
        std_dev = np.std(gray)
        
        # Normalize to 0-1 range (typical std_dev values range from 0 to around 80)
        normalized = min(1.0, std_dev / 80.0)
        
        return normalized
    
    @staticmethod
    def detect_faces(frame: np.ndarray) -> int:
        """
        Detect faces in a frame and return the count.
        
        Args:
            frame: Frame as numpy array in BGR format
            
        Returns:
            Number of faces detected
        """
        try:
            # Load pre-trained face detector
            face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            face_cascade = cv2.CascadeClassifier(face_cascade_path)
            
            # Convert to grayscale for face detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Detect faces
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )
            
            return len(faces)
            
        except Exception as e:
            logger.warning(f"Error detecting faces: {str(e)}")
            return 0
    
    @staticmethod
    def calculate_saliency(frame: np.ndarray) -> float:
        """
        Calculate the saliency of a frame (how visually distinctive it is).
        
        Args:
            frame: Frame as numpy array in BGR format
            
        Returns:
            Saliency score between 0 and 1
        """
        try:
            # Check if OpenCV has saliency module
            if hasattr(cv2, 'saliency'):
                # Create saliency detector
                saliency = cv2.saliency.StaticSaliencyFineGrained_create()
                
                # Compute saliency
                success, saliency_map = saliency.computeSaliency(frame)
                
                if success:
                    # Normalize to 0-1 range
                    saliency_score = np.mean(saliency_map)
                    return float(saliency_score)
            
            # Fallback to simpler method if saliency module missing or computation fails
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            saturation = np.mean(hsv[:, :, 1]) / 255.0  # Saturation channel
            value = np.mean(hsv[:, :, 2]) / 255.0  # Value channel
            
            # Higher saturation and value typically indicate more salient regions
            return (saturation * 0.7 + value * 0.3)
                
        except Exception as e:
            logger.warning(f"Error calculating saliency: {str(e)}")
            # Fallback to even simpler method
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            saturation = np.mean(hsv[:, :, 1]) / 255.0  # Saturation channel
            return saturation
    
    @staticmethod
    def score_frame(frame: np.ndarray) -> float:
        """
        Score a frame based on multiple criteria for thumbnail potential.
        
        Args:
            frame: Frame as numpy array in BGR format
            
        Returns:
            Combined score between 0 and 1
        """
        # Calculate individual scores
        brightness_score = FrameScorer.calculate_brightness(frame)
        contrast_score = FrameScorer.calculate_contrast(frame)
        face_count = FrameScorer.detect_faces(frame)
        saliency_score = FrameScorer.calculate_saliency(frame)
        
        # Calculate face score (0-1)
        face_score = min(1.0, face_count / 2)  # Score maxes out at 2 faces
        
        # Combine scores with weights
        combined_score = (
            brightness_score * 0.2 +
            contrast_score * 0.3 +
            face_score * 0.3 +
            saliency_score * 0.2
        )
        
        return combined_score


class ThumbnailGenerator:
    """Generates thumbnails for compilation videos."""
    
    def __init__(self, config, file_manager: Optional[FileManager] = None):
        """
        Initialize the thumbnail generator.
        
        Args:
            config: Application configuration
            file_manager: Optional FileManager instance
        """
        self.config = config
        self.app_config = config.app
        self.file_manager = file_manager or FileManager()
        
        # Get thumbnail dimensions
        self.width = self.app_config.thumbnail_width
        self.height = self.app_config.thumbnail_height
    
    async def _extract_best_frames(
        self, 
        video_paths: List[str], 
        frames_per_video: int = 5, 
        min_frame_interval: float = 1.0
    ) -> List[Tuple[np.ndarray, float]]:
        """
        Extract and score frames from videos to find the best ones for thumbnails.
        
        Args:
            video_paths: List of paths to video files
            frames_per_video: Number of frames to extract per video
            min_frame_interval: Minimum interval between frames in seconds
            
        Returns:
            List of tuples containing (frame, score)
        """
        all_frames = []
        
        for video_path in video_paths:
            try:
                # Open the video
                cap = cv2.VideoCapture(video_path)
                
                if not cap.isOpened():
                    logger.warning(f"Could not open video: {video_path}")
                    continue
                
                # Get video properties
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = frame_count / fps if fps > 0 else 0
                
                if duration <= 0:
                    logger.warning(f"Invalid video duration: {video_path}")
                    cap.release()
                    continue
                
                # Skip very short videos
                if duration < 2:
                    logger.debug(f"Video too short, skipping: {video_path}")
                    cap.release()
                    continue
                
                # Calculate frame interval
                frame_interval = max(
                    int(min_frame_interval * fps),
                    int(fps)  # At least 1 second apart
                )
                
                # Determine frames to extract, skipping first and last second
                skip_frames = int(fps)
                total_frames_to_check = frame_count - (2 * skip_frames)
                
                if total_frames_to_check <= 0:
                    logger.debug(f"Not enough frames after skipping: {video_path}")
                    cap.release()
                    continue
                
                # Calculate frame positions to extract (evenly distributed through the video)
                frame_positions = []
                if frames_per_video == 1:
                    # Just pick the middle frame
                    frame_positions = [frame_count // 2]
                else:
                    # Distribute frames evenly through the video
                    for i in range(frames_per_video):
                        pos = skip_frames + int(i * total_frames_to_check / (frames_per_video - 1))
                        frame_positions.append(min(pos, frame_count - 1))
                
                # Extract and score frames
                for position in frame_positions:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, position)
                    ret, frame = cap.read()
                    
                    if not ret:
                        continue
                    
                    # Score the frame
                    score = FrameScorer.score_frame(frame)
                    all_frames.append((frame, score))
                    
                    logger.debug(f"Extracted frame at {position} with score {score:.2f}")
                
                cap.release()
                
            except Exception as e:
                logger.error(f"Error extracting frames from {video_path}: {str(e)}")
        
        # Sort frames by score (descending)
        all_frames.sort(key=lambda x: x[1], reverse=True)
        
        logger.info(f"Extracted {len(all_frames)} frames from {len(video_paths)} videos")
        return all_frames
    
    def _create_thumbnail_manually(
        self,
        frames: List[np.ndarray],
        title: str,
        output_path: str,
        width: int = 1280,
        height: int = 720
    ) -> str:
        """
        Create a thumbnail image manually using OpenCV and PIL.
        
        Args:
            frames: List of frames to use
            title: Title to display on the thumbnail
            output_path: Path to save the thumbnail
            width: Width of the thumbnail
            height: Height of the thumbnail
            
        Returns:
            Path to the created thumbnail
        """
        try:
            # Create a date string for weekly branding
            current_date = datetime.now()
            date_str = current_date.strftime("%B %d, %Y")
            week_of_year = current_date.strftime("%V")  # Week number of the year
            month_str = current_date.strftime("%B")
            
            # Format the thumbnail title to include date information
            if "week" not in title.lower() and "top" not in title.lower():
                # Add week information if not already present
                title = f"TikTok Weekly Top - {month_str} {current_date.year}"
                subtitle = f"Week {week_of_year}"
            else:
                subtitle = f"{month_str} {current_date.year}"
            
            # Create a new PIL image with a black background
            pil_img = Image.new('RGB', (width, height), color=(0, 0, 0))
            
            # If we have frames, add them to the thumbnail
            if frames:
                try:
                    # Prepare main frame for background
                    main_frame = frames[0]
                    
                    # Convert main frame from BGR to RGB
                    main_frame_rgb = cv2.cvtColor(main_frame, cv2.COLOR_BGR2RGB)
                    main_pil = Image.fromarray(main_frame_rgb)
                    
                    # Resize to fill the background while maintaining aspect ratio
                    main_pil = self._resize_image_aspect_fill(main_pil, width, height)
                    
                    # Apply gaussian blur to the background
                    main_pil = main_pil.filter(ImageFilter.GaussianBlur(radius=5))
                    
                    # Darken the image for better text contrast
                    enhancer = ImageEnhance.Brightness(main_pil)
                    main_pil = enhancer.enhance(0.6)  # Darken to 60% brightness
                    
                    # Paste the blurred image as background
                    pil_img.paste(main_pil, (0, 0))
                    
                    # Overlay additional frames if available
                    if len(frames) > 1:
                        # Calculate frame sizes and positions
                        frame_width = width // 3
                        frame_height = int(frame_width * 16 / 9)  # 16:9 aspect ratio
                        y_pos = height - frame_height - 20  # 20px from bottom
                        
                        for i, frame in enumerate(frames[1:4]):  # Use up to 3 additional frames
                            try:
                                # Convert frame from BGR to RGB
                                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                frame_pil = Image.fromarray(frame_rgb)
                                
                                # Resize to thumbnail size
                                frame_pil = self._resize_image_aspect_fill(frame_pil, frame_width, frame_height)
                                
                                # Add border
                                bordered_frame = ImageOps.expand(frame_pil, border=3, fill='white')
                                
                                # Calculate x position
                                x_pos = 20 + (i * (frame_width + 20))
                                
                                # Paste the frame
                                pil_img.paste(bordered_frame, (x_pos, y_pos))
                                
                                if i >= 2:  # Limit to 3 frames
                                    break
                            except Exception as e:
                                logger.warning(f"Error adding frame {i+1}: {str(e)}")
                                continue
                except Exception as e:
                    logger.warning(f"Error processing frames: {str(e)}")
            
            # Add semi-transparent overlay at the top for better text visibility
            overlay = Image.new('RGBA', (width, height // 3), (0, 0, 0, 180))
            pil_img.paste(Image.composite(overlay, pil_img.convert('RGBA'), overlay), (0, 0))
            
            # Add TikTok branding elements
            draw = ImageDraw.Draw(pil_img)
            
            # Add TikTok logo text on left and right
            try:
                logo_font_size = width // 10
                try:
                    logo_font = ImageFont.truetype("Arial Bold", logo_font_size)
                except:
                    # Fallback to default font
                    logo_font = ImageFont.load_default()
                
                # Draw "Tik" in pink (left)
                tik_text = "Tik"
                tik_color = (255, 0, 80)  # TikTok pink color
                tik_bbox = draw.textbbox((0, 0), tik_text, font=logo_font)
                tik_width = tik_bbox[2] - tik_bbox[0]
                draw.text((width * 0.05, height * 0.5), tik_text, fill=tik_color, font=logo_font)
                
                # Draw "Tok" in cyan (right)
                tok_text = "Tok"
                tok_color = (0, 242, 234)  # TikTok cyan color
                tok_bbox = draw.textbbox((0, 0), tok_text, font=logo_font)
                tok_width = tok_bbox[2] - tok_bbox[0]
                draw.text((width * 0.95 - tok_width, height * 0.5), tok_text, fill=tok_color, font=logo_font)
            except Exception as e:
                logger.warning(f"Error adding TikTok branding: {str(e)}")
            
            # Add main title at the top
            try:
                # Calculate font size based on title length
                title_length = len(title)
                title_font_size = width // 20
                if title_length > 30:
                    title_font_size = width // 25
                
                try:
                    title_font = ImageFont.truetype("Arial Bold", title_font_size)
                except:
                    # Fallback to default font
                    title_font = ImageFont.load_default()
                
                # Add shadow for better visibility
                shadow_offset = 2
                shadow_color = (0, 0, 0)
                
                # First draw shadow
                for offset in [(0, shadow_offset), (shadow_offset, 0), (shadow_offset, shadow_offset)]:
                    draw.text((width // 2 + offset[0], height // 6 + offset[1]), 
                            title, font=title_font, fill=shadow_color, anchor="mm", align="center")
                
                # Then draw text
                draw.text((width // 2, height // 6), 
                         title, font=title_font, fill="white", anchor="mm", align="center")
            except Exception as e:
                logger.warning(f"Error adding title: {str(e)}")
            
            # Add subtitle (date info)
            try:
                subtitle_font_size = width // 30
                try:
                    subtitle_font = ImageFont.truetype("Arial", subtitle_font_size)
                except:
                    # Fallback to default font
                    subtitle_font = ImageFont.load_default()
                
                # Draw subtitle with shadow
                draw.text((width // 2 + shadow_offset, height // 6 + title_font_size + shadow_offset), 
                         subtitle, font=subtitle_font, fill=shadow_color, anchor="mm", align="center")
                draw.text((width // 2, height // 6 + title_font_size), 
                         subtitle, font=subtitle_font, fill=(220, 220, 220), anchor="mm", align="center")
            except Exception as e:
                logger.warning(f"Error adding subtitle: {str(e)}")
            
            # Save the final image
            pil_img.save(output_path, format="JPEG", quality=95)
            logger.info(f"Thumbnail created and saved to {output_path}")
            
            return output_path
        
        except Exception as e:
            logger.error(f"Error creating thumbnail: {str(e)}")
            
            # Create a simple fallback thumbnail
            try:
                # Create a black image
                img = Image.new('RGB', (width, height), color=(0, 0, 0))
                draw = ImageDraw.Draw(img)
                
                # Add title
                try:
                    font = ImageFont.truetype("Arial", 60)
                except:
                    font = ImageFont.load_default()
                
                draw.text((width // 2, height // 2), title, fill="white", font=font, anchor="mm", align="center")
                img.save(output_path, format="JPEG", quality=95)
                
                logger.info(f"Fallback thumbnail created and saved to {output_path}")
                return output_path
            except Exception as e:
                logger.error(f"Failed to create even a fallback thumbnail: {str(e)}")
                return ""
    
    async def create_thumbnail(
        self,
        video_metadata_list=None,
        compilation_path: str = None,
        title: str = "",
        output_path: str = None,
        method: str = "auto"
    ) -> Optional[str]:
        """
        Create a thumbnail for a TikTok video compilation.
        
        Args:
            video_metadata_list: List of VideoMetadata objects for the videos in the compilation
            compilation_path: Path to the compiled video file
            title: Title to display on the thumbnail
            output_path: Path to save the thumbnail
            method: Method to use for thumbnail creation ('auto', 'manual', 'api')
            
        Returns:
            Path to the created thumbnail, None if failed
        """
        try:
            # Generate output path if not provided
            if output_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                if title:
                    # Convert title to a filename-friendly format
                    safe_title = "".join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in title)
                    safe_title = safe_title.strip().replace(' ', '_')
                    output_path = os.path.join(self.app_config.thumbnail_dir, f"thumbnail_{safe_title}_{timestamp}.jpg")
                else:
                    output_path = os.path.join(self.app_config.thumbnail_dir, f"thumbnail_{timestamp}.jpg")
            
            # Make sure the output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Create a date string for the subtitle
            date_str = f"Week of {datetime.now().strftime('%B %d, %Y')}"
            
            logger.info(f"Generating thumbnail for '{title}'")
            
            # Extract frames from source material
            frames = []
            
            # If we have a compilation path, extract frames from it
            if compilation_path and os.path.exists(compilation_path):
                # Extract frames from the compilation
                try:
                    compilation_frames = []
                    video = VideoFileClip(compilation_path)
                    
                    # Skip the title screen if there is one (first 3 seconds)
                    if video.duration > 4:
                        # Extract frames from various points in the video
                        times = [3.5]  # Start after title
                        if video.duration > 20:
                            times.extend([video.duration * 0.25, video.duration * 0.5, video.duration * 0.75])
                        
                        for t in times:
                            frame = video.get_frame(t)
                            # Convert from RGB to BGR for OpenCV
                            frame = frame[:, :, ::-1].copy()
                            compilation_frames.append(frame)
                    
                    frames.extend(compilation_frames)
                    logger.info(f"Extracted {len(compilation_frames)} frames from compilation video")
                except Exception as e:
                    logger.warning(f"Error extracting frames from compilation: {str(e)}")
            
            # If we have video metadata, extract frames from individual videos
            if video_metadata_list and not frames:
                # Get paths to all downloaded videos
                video_paths = [m.local_path for m in video_metadata_list if m.local_path and os.path.exists(m.local_path)]
                
                if video_paths:
                    # Extract best frames from each video
                    all_video_frames = []
                    for path in video_paths[:3]:  # Limit to first 3 videos for performance
                        try:
                            # Extract frames from this video
                            video_frames = []
                            video = VideoFileClip(path)
                            
                            # Extract 5 frames from each video
                            for t in [
                                video.duration * 0.2,
                                video.duration * 0.4,
                                video.duration * 0.6
                            ]:
                                if t > 0 and t < video.duration:
                                    frame = video.get_frame(t)
                                    # Convert from RGB to BGR for OpenCV
                                    frame = frame[:, :, ::-1].copy()
                                    video_frames.append(frame)
                            
                            all_video_frames.extend(video_frames)
                        except Exception as e:
                            logger.warning(f"Error extracting frames from {path}: {str(e)}")
                    
                    frames.extend(all_video_frames)
                    logger.info(f"Extracted {len(all_video_frames)} frames from source videos")
            
            if not frames:
                logger.warning("No frames extracted, creating basic thumbnail")
                return self._create_basic_thumbnail(title, date_str, output_path)
            
            # Score frames to find the best one
            frame_scores = []
            for frame in frames:
                try:
                    # Score the frame
                    score = FrameScorer.score_frame(frame)
                    frame_scores.append((frame, score))
                except Exception as e:
                    logger.warning(f"Error scoring frame: {str(e)}")
            
            # Sort frames by score (highest first)
            frame_scores.sort(key=lambda x: x[1], reverse=True)
            
            # Select best frames
            best_frames = [f[0] for f in frame_scores[:3]] if frame_scores else frames[:3]
            
            # Create thumbnail with the best frames
            thumbnail_path = self._create_thumbnail_manually(
                frames=best_frames,
                title=title,
                output_path=output_path,
                width=self.width,
                height=self.height
            )
            
            logger.success(f"Thumbnail created successfully: {thumbnail_path}")
            return thumbnail_path
            
        except Exception as e:
            logger.error(f"Error creating thumbnail: {str(e)}")
            return None

    def _create_basic_thumbnail(
        self,
        title: str,
        subtitle: str = None,
        output_path: str = None,
        width: int = None,
        height: int = None,
    ) -> Optional[str]:
        """
        Create a basic thumbnail with text and TikTok branding when no frames are available.
        
        Args:
            title: Title text for the thumbnail
            subtitle: Optional subtitle text (e.g., date)
            output_path: Path to save the thumbnail
            width: Width of the thumbnail image
            height: Height of the thumbnail image
            
        Returns:
            Path to the created thumbnail
        """
        try:
            # Use default dimensions if not specified
            if width is None:
                width = self.width
            if height is None:
                height = self.height
            
            # Create a new image with gradient background
            from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
            
            # Create a gradient background (black to dark gray)
            image = Image.new('RGB', (width, height), color=(0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            # Add a gradient overlay
            for y in range(height):
                # Create a gradient from top to bottom
                r = int(20 * (1 - y / height))
                g = int(20 * (1 - y / height))
                b = int(30 * (1 - y / height))
                draw.line([(0, y), (width, y)], fill=(r, g, b))
            
            # Add TikTok branding elements
            # Left side "Tik" in TikTok pink color
            try:
                font_size = width // 8
                try:
                    font = ImageFont.truetype("Arial Bold", font_size)
                except:
                    # Fallback to default font
                    font = ImageFont.load_default()
                
                # Draw "Tik" in pink
                tik_text = "Tik"
                tik_color = (255, 0, 80)  # TikTok pink/red color
                tik_bbox = draw.textbbox((0, 0), tik_text, font=font)
                tik_width = tik_bbox[2] - tik_bbox[0]
                draw.text((width * 0.15, height // 2 - font_size // 2), tik_text, fill=tik_color, font=font)
                
                # Draw "Tok" in cyan
                tok_text = "Tok"
                tok_color = (0, 242, 234)  # TikTok teal/cyan color
                tok_bbox = draw.textbbox((0, 0), tok_text, font=font)
                tok_width = tok_bbox[2] - tok_bbox[0]
                draw.text((width * 0.85 - tok_width, height // 2 - font_size // 2), tok_text, fill=tok_color, font=font)
            except Exception as e:
                logger.warning(f"Error adding TikTok branding: {str(e)}")
            
            # Add title text
            try:
                # Use dynamic font size based on title length
                title_font_size = min(width // 15, 120)
                title_font_size = max(title_font_size, 60)  # Minimum size
                
                try:
                    title_font = ImageFont.truetype("Arial Bold", title_font_size)
                except:
                    # Fallback to default font
                    title_font = ImageFont.load_default()
                
                # Draw title text with shadow for better visibility
                # First draw shadow
                shadow_offset = 3
                draw.text((width//2 - shadow_offset, height//4 - shadow_offset), title, fill=(0, 0, 0), 
                         font=title_font, anchor="mm", align="center")
                # Then draw text
                draw.text((width//2, height//4), title, fill=(255, 255, 255), 
                         font=title_font, anchor="mm", align="center")
            except Exception as e:
                logger.warning(f"Error adding title text: {str(e)}")
            
            # Add subtitle (date)
            if subtitle:
                try:
                    subtitle_font_size = min(width // 25, 48)
                    try:
                        subtitle_font = ImageFont.truetype("Arial", subtitle_font_size)
                    except:
                        # Fallback to default font
                        subtitle_font = ImageFont.load_default()
                    
                    # Draw subtitle
                    draw.text((width//2, height//4 + title_font_size), subtitle, fill=(200, 200, 200), 
                             font=subtitle_font, anchor="mm", align="center")
                except Exception as e:
                    logger.warning(f"Error adding subtitle text: {str(e)}")
            
            # Add "Weekly Top" text at the bottom
            try:
                bottom_text = "Weekly Top"
                bottom_font_size = min(width // 20, 72)
                try:
                    bottom_font = ImageFont.truetype("Arial Bold", bottom_font_size)
                except:
                    # Fallback to default font
                    bottom_font = ImageFont.load_default()
                
                # Draw bottom text
                draw.text((width//2, height * 0.75), bottom_text, fill=(255, 255, 255), 
                         font=bottom_font, anchor="mm", align="center")
            except Exception as e:
                logger.warning(f"Error adding bottom text: {str(e)}")
            
            # Save the image
            image.save(output_path, quality=95)
            logger.info(f"Basic thumbnail created and saved to {output_path}")
            return output_path
        
        except Exception as e:
            logger.error(f"Error creating basic thumbnail: {str(e)}")
            return None

    def _resize_image_aspect_fill(self, image, target_width, target_height):
        """
        Resize an image to fill the target dimensions while maintaining aspect ratio.
        
        Args:
            image: PIL Image to resize
            target_width: Target width
            target_height: Target height
            
        Returns:
            Resized PIL Image
        """
        # Get original dimensions
        original_width, original_height = image.size
        
        # Calculate ratios
        width_ratio = target_width / original_width
        height_ratio = target_height / original_height
        
        # Use the larger ratio to ensure the image fills the target dimensions
        ratio = max(width_ratio, height_ratio)
        
        # Calculate new dimensions
        new_width = int(original_width * ratio)
        new_height = int(original_height * ratio)
        
        # Resize the image
        resized_image = image.resize((new_width, new_height), Image.LANCZOS)
        
        # Crop the center portion if the image is larger than the target
        if new_width > target_width or new_height > target_height:
            left = (new_width - target_width) / 2
            top = (new_height - target_height) / 2
            right = (new_width + target_width) / 2
            bottom = (new_height + target_height) / 2
            
            # Crop to the target size
            resized_image = resized_image.crop((left, top, right, bottom))
        
        return resized_image


# Example usage
if __name__ == "__main__":
    import asyncio
    from src.utils.config_loader import ConfigLoader
    from src.utils.logger_config import setup_logger
    
    # Setup logger
    setup_logger("DEBUG")
    
    # Load configuration
    config = ConfigLoader().get_config()
    
    # Create a sample video metadata for testing
    class SampleVideoMetadata:
        def __init__(self, id, author, local_path):
            self.id = id
            self.author = author
            self.local_path = local_path
    
    # Replace with actual video path
    sample_video_path = "sample_videos/video1.mp4"
    compilation_path = "sample_videos/compilation.mp4"
    
    # Create thumbnail generator
    async def main():
        generator = ThumbnailGenerator(config)
        
        # Generate thumbnail
        sample_metadata = [
            SampleVideoMetadata("1", "user1", sample_video_path)
        ]
        
        thumbnail_path = await generator.create_thumbnail(
            video_metadata_list=sample_metadata,
            compilation_path=compilation_path,
            title="Weekly TikTok Highlights"
        )
        
        print(f"Thumbnail created: {thumbnail_path}")
    
    asyncio.run(main()) 