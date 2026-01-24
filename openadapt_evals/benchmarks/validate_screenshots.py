"""Simple screenshot validation - detect blank/idle screenshots."""

from pathlib import Path
from PIL import Image
import numpy as np


def validate_screenshot(path: str, min_variance: float = 100.0) -> tuple[bool, str]:
    """Check if screenshot shows real content (not blank/idle).
    
    Args:
        path: Path to screenshot file
        min_variance: Minimum pixel variance threshold (default 100)
        
    Returns:
        (is_valid, reason) tuple
    """
    try:
        img = Image.open(path).convert('L')  # Grayscale
        arr = np.array(img)
        variance = float(arr.var())
        
        if variance < min_variance:
            return False, f"Low variance ({variance:.1f}) - likely idle/blank"
        return True, f"OK (variance: {variance:.1f})"
    except Exception as e:
        return False, f"Error: {e}"


def validate_directory(dir_path: str) -> dict[str, tuple[bool, str]]:
    """Validate all screenshots in a directory.
    
    Args:
        dir_path: Path to directory containing screenshots
        
    Returns:
        Dict mapping filename to (is_valid, reason) tuple
    """
    results = {}
    path = Path(dir_path)
    
    for ext in ['*.png', '*.jpg', '*.jpeg']:
        for f in path.glob(ext):
            results[f.name] = validate_screenshot(str(f))
    
    return results


def summarize_results(results: dict[str, tuple[bool, str]]) -> dict:
    """Summarize validation results.
    
    Returns:
        Dict with total, valid, invalid counts and list of invalid files
    """
    valid = [k for k, (v, _) in results.items() if v]
    invalid = [k for k, (v, _) in results.items() if not v]
    
    return {
        'total': len(results),
        'valid': len(valid),
        'invalid': len(invalid),
        'invalid_files': invalid,
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python validate_screenshots.py <directory>")
        sys.exit(1)
    
    results = validate_directory(sys.argv[1])
    summary = summarize_results(results)
    
    print(f"Validated {summary['total']} screenshots:")
    print(f"  Valid: {summary['valid']}")
    print(f"  Invalid: {summary['invalid']}")
    
    if summary['invalid_files']:
        print("\nInvalid files:")
        for f in summary['invalid_files']:
            print(f"  - {f}: {results[f][1]}")
