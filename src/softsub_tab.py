# src/softsub_tab.py
import tkinter as tk
from tkinter import ttk

def create_softsub_tab(parent, gui_instance):
    """
    Tạo và điền nội dung cho tab Softsub.
    - parent: ttk.Notebook widget.
    - gui_instance: Tham chiếu đến instance của class SubtitlePreviewer chính.
    """
    softsub_frame = ttk.Frame(parent, padding=10)
    
    # Process Frame
    control_frame = ttk.LabelFrame(softsub_frame, text="Softsub Process", padding=10)
    control_frame.pack(fill=tk.X, expand=True, pady=(0, 10))

    # Nút chọn nguồn (video/xml/html)
    btn_select_source = ttk.Button(
        control_frame, 
        text="1. Select Source (Video/XML/HTML)", 
        command=gui_instance.select_source_file
    )
    btn_select_source.pack(fill=tk.X, pady=2)
    gui_instance.btn_select_source = btn_select_source # Gán lại để quản lý state

    # Nút tải phiên làm việc
    btn_load_session = ttk.Button(
        control_frame, 
        text="Load Session...", 
        command=gui_instance.load_session
    )
    btn_load_session.pack(fill=tk.X, pady=2)
    gui_instance.btn_load_session = btn_load_session

    return softsub_frame
