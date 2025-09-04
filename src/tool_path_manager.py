# src/tool_path_manager.py
import os
import sys
import shutil

def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_tool_path(tool_name: str) -> str:
    tool_map = {
        "ffmpeg": "ffmpeg.exe",
        "ffprobe": "ffprobe.exe",
        "mkvextract": "mkvextract.exe",
        "java": os.path.join("java", "bin", "java.exe")
    }

    executable_name = tool_map.get(tool_name.lower())
    if not executable_name:
        return tool_name

    local_tool_path = resource_path(os.path.join("assets", "tools", executable_name))
    if os.path.exists(local_tool_path):
        return local_tool_path
    
    system_tool_path = shutil.which(tool_name)
    if system_tool_path:
        return system_tool_path
        
    return local_tool_path
