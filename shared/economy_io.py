#!/usr/bin/env python3
"""
Input/Output Operations
Handles configuration loading and file operations.
"""
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to config file (if None, uses default)
        
    Returns:
        Configuration dictionary
    """
    if config_path is None:
        # Return minimal defaults when no config path provided
        return {
            "history": {"days": 180},
            "grading": {
                "a_plus_threshold": 90,
                "a_threshold": 75,
                "b_threshold": 50,
                "c_threshold": 25
            },
            "fred": {
                "base_url": "https://api.stlouisfed.org/fred",
                "rate_limit_seconds": 0.1,
                "timeout_seconds": 30
            },
            "output": {
                "indent": 2,
                "ensure_ascii": False
            }
        }
    
    config_file = Path(config_path)
    
    if not config_file.exists():
        # Return minimal defaults if file doesn't exist
        return {
            "history": {"days": 180},
            "grading": {
                "a_plus_threshold": 90,
                "a_threshold": 75,
                "b_threshold": 50,
                "c_threshold": 25
            },
            "fred": {
                "base_url": "https://api.stlouisfed.org/fred",
                "rate_limit_seconds": 0.1,
                "timeout_seconds": 30
            },
            "output": {
                "indent": 2,
                "ensure_ascii": False
            }
        }
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config or {}


def save_json(data: Dict[str, Any], output_path: str, indent: int = 2) -> None:
    """
    Save data to JSON file.
    
    Args:
        data: Data to save
        output_path: Path to output file
        indent: JSON indentation (default 2)
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    
    print(f"✓ Saved: {output_file}")


def load_json(input_path: str) -> Dict[str, Any]:
    """
    Load data from JSON file.
    
    Args:
        input_path: Path to input file
        
    Returns:
        Loaded data
    """
    input_file = Path(input_path)
    
    if not input_file.exists():
        raise FileNotFoundError(f"File not found: {input_file}")
    
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    return data


def ensure_output_dir(output_path: str) -> Path:
    """
    Ensure output directory exists.
    
    Args:
        output_path: Path to output file
        
    Returns:
        Path object for output file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    return output_file
