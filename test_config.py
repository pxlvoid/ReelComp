#!/usr/bin/env python3
"""
Test script to verify ConfigLoader works properly.
"""

from src.utils.config_loader import ConfigLoader

# Create config loader with None parameter
config_loader = ConfigLoader(None)
config = config_loader.get_config(None)

print("Successfully created config:")
print(f"TikTok Config: {config.tiktok}")
print(f"YouTube Config: {config.youtube}")
print(f"App Config: {config.app}")

print("\nTest complete - ConfigLoader can handle None values correctly.") 