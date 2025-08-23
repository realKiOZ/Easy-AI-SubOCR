# src/tool_path_manager.py
import os
import sys
import shutil

def resource_path(relative_path: str) -> str:
    """ Lấy đường dẫn tuyệt đối đến tài nguyên, hoạt động cho cả môi trường dev và PyInstaller. """
    try:
        # PyInstaller tạo một thư mục tạm và lưu đường dẫn trong _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_tool_path(tool_name: str) -> str:
    """
    Lấy đường dẫn tuyệt đối đến một công cụ.
    Ưu tiên tìm trong thư mục đóng gói 'assets/tools'.
    Nếu không tìm thấy, sẽ tìm trong PATH của hệ thống làm phương án dự phòng.
    """
    tool_map = {
        "ffmpeg": "ffmpeg.exe",
        "ffprobe": "ffprobe.exe",
        "mkvextract": "mkvextract.exe",
        "java": os.path.join("java", "bin", "java.exe") # Đường dẫn tương đối bên trong assets/tools
    }

    executable_name = tool_map.get(tool_name.lower())
    if not executable_name:
        # Nếu công cụ không có trong map, giả sử nó là một lệnh có sẵn trên PATH
        return tool_name

    # 1. Ưu tiên kiểm tra trong thư mục tools đóng gói
    local_tool_path = resource_path(os.path.join("assets", "tools", executable_name))
    if os.path.exists(local_tool_path):
        return local_tool_path
    
    # 2. Phương án dự phòng: kiểm tra trong PATH hệ thống
    system_tool_path = shutil.which(tool_name)
    if system_tool_path:
        return system_tool_path
        
    # 3. Nếu không tìm thấy ở đâu cả, trả về đường dẫn mong muốn để thông báo lỗi được rõ ràng
    return local_tool_path