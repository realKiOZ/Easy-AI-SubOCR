# src/hardsub_tab.py
import tkinter as tk
from tkinter import ttk
from src.vsf_settings_component import create_vsf_advanced_settings_frame

def create_hardsub_tab(parent, gui_instance):
    hardsub_frame = ttk.Frame(parent, padding=10)
    
    # --- Input Frame ---
    input_frame = ttk.LabelFrame(hardsub_frame, text="Input", padding=10, style="Custom.TLabelframe")
    input_frame.pack(fill=tk.X, expand=False, pady=(0, 10))

    # Create a sub-frame for the buttons to sit side-by-side
    button_sub_frame = ttk.Frame(input_frame)
    button_sub_frame.pack(fill=tk.X, expand=True)
    button_sub_frame.columnconfigure(0, weight=1)
    button_sub_frame.columnconfigure(1, weight=1)
    
    btn_select_hardsub_video = ttk.Button(button_sub_frame, text="1. Select Video File", command=gui_instance.select_hardsub_video)
    btn_select_hardsub_video.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=2)
    gui_instance.btn_select_hardsub_video = btn_select_hardsub_video

    btn_load_session_hardsub = ttk.Button(button_sub_frame, text="Load Previous Session...", command=lambda: gui_instance.load_session(session_type='hardsub'))
    btn_load_session_hardsub.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=2)
    gui_instance.btn_load_session_hardsub = btn_load_session_hardsub

    ytdlp_frame = ttk.LabelFrame(input_frame, text="or Download from URL", padding=10, style="Custom.TLabelframe")
    ytdlp_frame.pack(fill=tk.X, expand=False, pady=(5, 0))
    ytdlp_frame.columnconfigure(0, weight=1)

    gui_instance.video_url_var = tk.StringVar()
    url_entry = ttk.Entry(ytdlp_frame, textvariable=gui_instance.video_url_var)
    url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

    btn_download_video = ttk.Button(ytdlp_frame, text="Download", command=gui_instance.start_video_download_thread)
    btn_download_video.grid(row=0, column=1, sticky="ew")
    gui_instance.btn_download_video = btn_download_video

    # --- Process Selection ---
    process_frame = ttk.LabelFrame(hardsub_frame, text="Process Method", padding=10, style="Custom.TLabelframe")
    process_frame.pack(fill=tk.X, pady=(0, 10))
    
    # Biến `hardsub_process_var` bây giờ được tạo trong gui.py
    # Chúng ta chỉ sử dụng nó ở đây
    rb_vsf_only = ttk.Radiobutton(process_frame, text="VSF Only (CPU, but fast)", variable=gui_instance.hardsub_process_var, value="vsf_only", command=gui_instance.toggle_hardsub_settings)
    rb_vsf_only.pack(anchor='w')
    
    rb_east_vsf = ttk.Radiobutton(process_frame, text="EAST + VSF Refine (GPU)", variable=gui_instance.hardsub_process_var, value="east_vsf", command=gui_instance.toggle_hardsub_settings)
    rb_east_vsf.pack(anchor='w')

    # --- Common Settings ---
    gui_instance.common_settings_frame = ttk.LabelFrame(hardsub_frame, text="Common Settings", padding=10, style="Custom.TLabelframe")
    gui_instance.common_settings_frame.pack(fill=tk.X, pady=(0, 10))
    gui_instance.common_settings_frame.columnconfigure(1, weight=1)

    top_check = ttk.Checkbutton(gui_instance.common_settings_frame, text="Scan Top Area", variable=gui_instance.hardsub_scan_top_var, command=gui_instance.log_common_settings)
    top_check.grid(row=0, column=0, sticky='w', pady=2)
    bottom_check = ttk.Checkbutton(gui_instance.common_settings_frame, text="Scan Bottom Area", variable=gui_instance.hardsub_scan_bottom_var, command=gui_instance.log_common_settings)
    bottom_check.grid(row=0, column=1, sticky='w', pady=2)

    ttk.Label(gui_instance.common_settings_frame, text="Scan Area Height:").grid(row=1, column=0, sticky="w")
    scan_area_scale = ttk.Scale(gui_instance.common_settings_frame, from_=10, to=50, variable=gui_instance.hardsub_scan_area_height_var, command=gui_instance.on_common_settings_change)
    scan_area_scale.grid(row=1, column=1, sticky="ew", padx=5)
    scan_area_scale.bind("<ButtonRelease-1>", gui_instance.log_common_settings)
    ttk.Label(gui_instance.common_settings_frame, textvariable=gui_instance.hardsub_scan_area_height_display_var).grid(row=1, column=2)

    # --- Process-Specific Settings Container ---
    settings_container = ttk.Frame(hardsub_frame)
    settings_container.pack(fill=tk.X, expand=False)

    gui_instance.vsf_adv_settings_frame = create_vsf_advanced_settings_frame(settings_container, gui_instance)
    gui_instance.vsf_adv_settings_frame.pack(fill=tk.X, pady=(0, 10))

    gui_instance.east_settings_frame = ttk.LabelFrame(settings_container, text="EAST Settings", padding=10, style="Custom.TLabelframe")
    gui_instance.east_settings_frame.pack(fill=tk.X, pady=(0, 10))
    gui_instance.east_settings_frame.columnconfigure(1, weight=1)

    ttk.Label(gui_instance.east_settings_frame, text="Detection Confidence:").grid(row=0, column=0, sticky="w")
    confidence_scale = ttk.Scale(gui_instance.east_settings_frame, from_=0.1, to=0.9, variable=gui_instance.east_confidence_var, command=gui_instance.on_east_settings_change)
    confidence_scale.grid(row=0, column=1, sticky="ew", padx=5)
    confidence_scale.bind("<ButtonRelease-1>", gui_instance.log_east_settings)
    ttk.Label(gui_instance.east_settings_frame, textvariable=gui_instance.east_confidence_display_var).grid(row=0, column=2)

    ttk.Label(gui_instance.east_settings_frame, text="Detection Quality:").grid(row=1, column=0, sticky="w", pady=2)
    quality_combobox = ttk.Combobox(gui_instance.east_settings_frame, textvariable=gui_instance.east_quality_var, state="readonly", width=10)
    quality_combobox['values'] = ['320px', '480px']
    quality_combobox.grid(row=1, column=1, columnspan=2, sticky="w", padx=5)
    quality_combobox.bind("<<ComboboxSelected>>", gui_instance.log_east_settings)

    gui_instance.east_gpu_check = ttk.Checkbutton(gui_instance.east_settings_frame, text="Use GPU Acceleration (NVIDIA CUDA)", variable=gui_instance.east_use_gpu_var, command=gui_instance.log_east_settings)
    gui_instance.east_gpu_check.grid(row=2, column=0, columnspan=3, sticky='w', pady=5)

    # --- Action Button ---
    action_frame = ttk.Frame(hardsub_frame)
    action_frame.pack(fill=tk.X, expand=False, pady=(10, 0))

    btn_detect_hardsub = ttk.Button(action_frame, text="2. Detect Subtitles", command=gui_instance.start_hardsub_detection_thread, style="Accent.TButton")
    btn_detect_hardsub.pack(fill=tk.X, pady=5)
    gui_instance.btn_detect_hardsub = btn_detect_hardsub

    return hardsub_frame
