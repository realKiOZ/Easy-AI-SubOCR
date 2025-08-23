import os
import sys
import shutil

def resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_tool_path(tool_name: str) -> str:
    """
    Gets the absolute path to a tool.
    It first checks for the tool in the 'assets/tools' directory.
    If not found, it returns the tool_name for the system to find in PATH.
    """
    # Mapping of tool names to their potential executable names
    tool_map = {
        "ffmpeg": "ffmpeg.exe",
        "ffprobe": "ffprobe.exe",
        "mkvextract": "mkvextract.exe",
        "java": os.path.join("java", "bin", "java.exe")
    }

    executable_name = tool_map.get(tool_name.lower())
    
    if not executable_name:
        # If the tool is not in our map, assume it's a command on PATH
        return tool_name

    # Check for the tool within the bundled assets/tools directory
    local_tool_path = resource_path(os.path.join("assets", "tools", executable_name))
    
    if os.path.exists(local_tool_path):
        return local_tool_path
    
    # Fallback: check if the tool is available in the system's PATH
    if shutil.which(tool_name):
        return tool_name
        
    # If the tool is not found anywhere, return the path to the local asset anyway,
    # so the error message will show the expected location.
    return local_tool_path
