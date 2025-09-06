import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, font
from tkextrafont import Font
from tkinterdnd2 import DND_FILES, TkinterDnD
import threading
from PIL import Image, ImageTk, ImageFile
import logging
import time

from src.app_context import AppContext
from src.ui_components import SubtitleSelectionDialog, SessionSelectionDialog, create_ocr_controls, create_advanced_settings
from src.utils import check_tools_availability, is_cuda_available
from src.settings import TEMP_DIR_NAME, APP_TEMP_PATH, DEFAULT_NUM_THREADS
from src.softsub_tab import create_softsub_tab
from src.hardsub_tab import create_hardsub_tab

ImageFile.LOAD_TRUNCATED_IMAGES = True

class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)
        self.text_widget.after(0, append)

class SubtitlePreviewer(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Easy AI Subtitle OCR")
        self.geometry("1100x900")
        self.minsize(1100, 900)
        self._center_window(1200, 1000)
        
        self.app_context = AppContext()
        self._init_vars()
        self._configure_styles()
        self._create_menu()
        self._create_widgets()
        self._setup_logging()
        
        self.after(10, self.toggle_hardsub_settings)
        self.after(100, self.auto_load_models_on_startup)
        self.after(200, self.check_required_tools)
        self.after(300, self.check_cuda_support)
        self.after(400, lambda: self._set_controls_state(tk.NORMAL))
        
        try:
            self.font = Font(file="assets/fonts/NotoSans-Regular.ttf", family="Noto Sans")
        except Exception as e:
            logging.error(f"Failed to load font: {e}")

        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.handle_drop)

    def _init_vars(self):
        self.api_key_var = tk.StringVar(value=self.app_context.api_key_1)
        self.api_key_2_var = tk.StringVar(value=self.app_context.api_key_2)
        self.api_key_3_var = tk.StringVar(value=self.app_context.api_key_3)
        self.model_var = tk.StringVar(value=self.app_context.model_name)
        self.batch_size_var = tk.IntVar(value=self.app_context.batch_size)
        config = self.app_context.generation_config
        self.temp_var = tk.DoubleVar(value=round(config.get("temperature", 0.5), 2))
        self.temp_display_var = tk.StringVar(value=f"{self.temp_var.get():.2f}")
        self.ocr_lang_var = tk.StringVar(value=self.app_context.ocr_language)
        self.cancellation_event = threading.Event()
        self.ocr_completed = False
        
        self.hardsub_process_var = tk.StringVar(value="vsf_only")
        
        common_settings = self.app_context.settings.get("common_hardsub_settings", {})
        self.hardsub_scan_top_var = tk.BooleanVar(value=common_settings.get("scan_top", True))
        self.hardsub_scan_bottom_var = tk.BooleanVar(value=common_settings.get("scan_bottom", True))
        self.hardsub_scan_area_height_var = tk.IntVar(value=common_settings.get("scan_area_height", 30))
        self.hardsub_scan_area_height_display_var = tk.StringVar(value=f"{self.hardsub_scan_area_height_var.get()}%")

        east_settings = self.app_context.settings.get("east_settings", {})
        self.east_use_gpu_var = tk.BooleanVar(value=east_settings.get("use_gpu", True))
        self.east_confidence_var = tk.DoubleVar(value=round(east_settings.get("confidence", 0.5), 2))
        self.east_confidence_display_var = tk.StringVar(value=f"{self.east_confidence_var.get():.2f}")
        self.east_quality_var = tk.StringVar(value=east_settings.get("quality", '320px'))

        vsf_adv_settings = self.app_context.settings.get("vsf_adv_settings", {})
        self.vsf_moderate_threshold_var = tk.DoubleVar(value=round(vsf_adv_settings.get("moderate_threshold", 0.25), 2))
        self.vsf_moderate_threshold_display_var = tk.StringVar(value=f"{self.vsf_moderate_threshold_var.get():.2f}")
        self.vsf_moderate_threshold_scaled_var = tk.DoubleVar(value=round(vsf_adv_settings.get("moderate_threshold_scaled", 0.25), 2))
        self.vsf_moderate_threshold_scaled_display_var = tk.StringVar(value=f"{self.vsf_moderate_threshold_scaled_var.get():.2f}")
        self.vsf_image_scale_var = tk.IntVar(value=vsf_adv_settings.get("image_scale", 4))
        self.vsf_image_scale_display_var = tk.StringVar(value=f"{self.vsf_image_scale_var.get()}")
        self.vsf_vedges_points_line_error_var = tk.DoubleVar(value=round(vsf_adv_settings.get("vedges_points_line_error", 0.2), 2))
        self.vsf_vedges_points_line_error_display_var = tk.StringVar(value=f"{self.vsf_vedges_points_line_error_var.get():.2f}")
        self.vsf_min_sum_color_diff_var = tk.IntVar(value=vsf_adv_settings.get("min_sum_color_diff", 200))
        self.vsf_min_sum_color_diff_display_var = tk.StringVar(value=f"{self.vsf_min_sum_color_diff_var.get()}")

    def _configure_styles(self):
        style = ttk.Style(self)
        selected_bg = "#e0e8f0"
        style.configure("Highlighted.TNotebook.Tab", background=selected_bg, font=('Arial', 10, 'bold'), padding=[10, 5])
        style.map("Highlighted.TNotebook.Tab", background=[("selected", selected_bg)])
        style.configure("TNotebook", tabposition='n')
        style.configure("Save.TButton", font=('Arial', 11, 'bold'), padding=[0, 5], background="#cce0ff")
        style.configure("HardsubAIO.TButton", font=('Arial', 11, 'bold'), padding=[0, 5], background="#d4edda")
        style.configure("SoftsubAIO.TButton", font=('Arial', 11, 'bold'), padding=[0, 5], background="#d1ecf1")
        
        style.configure("Accent.TButton", font=('Arial', 11, 'bold'), padding=[0, 5], background="#d4edda") # Green
        style.configure("Primary.TButton", font=('Arial', 11, 'bold'), padding=[0, 5], background="#d1ecf1") # Blue

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1, minsize=380)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        left_frame = self._create_left_panel()
        left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        right_frame = self._create_right_panel()
        right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    def _create_left_panel(self):
        left_container = ttk.Frame(self)
        left_container.grid_rowconfigure(1, weight=1)
        left_container.grid_columnconfigure(0, weight=1)

        api_frame = self._create_api_config_frame(left_container)
        api_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        self.notebook = ttk.Notebook(left_container, style="Highlighted.TNotebook")
        self.notebook.grid(row=1, column=0, sticky="nsew")
        
        softsub_tab_frame = create_softsub_tab(self.notebook, self)
        self.notebook.add(softsub_tab_frame, text="Softsub")
        
        hardsub_tab_frame = create_hardsub_tab(self.notebook, self)
        self.notebook.add(hardsub_tab_frame, text="Hardsub")
        
        return left_container

    def _create_right_panel(self):
        right_container = ttk.Frame(self)
        right_container.grid_columnconfigure(0, weight=1)
        right_container.grid_rowconfigure(1, weight=20, minsize=160) # Preview
        right_container.grid_rowconfigure(2, weight=5, minsize=120) # Nav/OCR
        right_container.grid_rowconfigure(3, weight=1) # Log

        top_controls_frame = ttk.Frame(right_container)
        top_controls_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        top_controls_frame.grid_columnconfigure(0, weight=1)
        top_controls_frame.grid_columnconfigure(1, minsize=300)
        
        adv_ocr_frame = ttk.LabelFrame(top_controls_frame, text="Advanced OCR", padding=10)
        adv_ocr_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        adv_settings_frame = create_advanced_settings(adv_ocr_frame, self)
        adv_settings_frame.pack(fill="x", expand=True)
        ocr_controls_frame = create_ocr_controls(adv_ocr_frame, self)
        ocr_controls_frame.pack(fill="x", expand=True, pady=(5,0))

        save_aio_frame = self._create_save_aio_frame(top_controls_frame)
        save_aio_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        image_container = ttk.LabelFrame(right_container, text="Frame Preview", padding=10)
        image_container.grid(row=1, column=0, sticky="nsew", pady=(0, 5))
        image_container.grid_propagate(False)
        image_container.grid_rowconfigure(0, weight=1)
        image_container.grid_columnconfigure(0, weight=1)
        self.image_canvas = tk.Canvas(image_container, bg="gray", highlightthickness=0)
        self.image_canvas.grid(row=0, column=0, sticky="nsew")
        self.image_canvas.bind("<Configure>", self.on_canvas_resize)

        nav_ocr_frame = ttk.Frame(right_container)
        nav_ocr_frame.grid(row=2, column=0, sticky="nsew", pady=5)
        nav_ocr_frame.grid_columnconfigure(1, weight=1)

        nav_frame = self._create_nav_frame(nav_ocr_frame)
        nav_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        ocr_result_frame = ttk.LabelFrame(nav_ocr_frame, text="OCR Result", padding=10)
        ocr_result_frame.grid(row=0, column=1, sticky="nsew")
        ocr_result_frame.grid_rowconfigure(0, weight=1)
        ocr_result_frame.grid_columnconfigure(0, weight=1)
        try:
            self.text_font = font.Font(family="Noto Sans", size=14)
        except tk.TclError:
            self.text_font = font.Font(family="Arial", size=14)
        self.text_editor = scrolledtext.ScrolledText(ocr_result_frame, wrap=tk.WORD, font=self.text_font, height=4)
        self.text_editor.grid(row=0, column=0, sticky="nsew")

        log_frame = ttk.LabelFrame(right_container, text="Log", padding=5)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(5, 0))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state="disabled", font=("Courier New", 10)) # Increased font size to 10
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        return right_container

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Clear Temp Folder...", command=self.clear_temp_folder)

    def _create_api_config_frame(self, parent):
        api_frame = ttk.LabelFrame(parent, text="API Key / Models", padding=10)
        api_frame.columnconfigure(1, weight=1)
        ttk.Label(api_frame, text="Google API Key:").grid(row=0, column=0, sticky="w", pady=2)
        self.api_key_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(5,0))
        
        ttk.Label(api_frame, text="Backup Key 2:").grid(row=1, column=0, sticky="w", pady=2)
        self.api_key_2_entry = ttk.Entry(api_frame, textvariable=self.api_key_2_var, show="*")
        self.api_key_2_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(5,0))

        ttk.Label(api_frame, text="Backup Key 3:").grid(row=2, column=0, sticky="w", pady=2)
        self.api_key_3_entry = ttk.Entry(api_frame, textvariable=self.api_key_3_var, show="*")
        self.api_key_3_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(5,0))

        ttk.Label(api_frame, text="Model:").grid(row=3, column=0, sticky="w", pady=2)
        self.model_combobox = ttk.Combobox(api_frame, textvariable=self.model_var, state="readonly")
        self.model_combobox.grid(row=3, column=1, sticky="w", padx=(5,5), pady=(5,0))
        self.load_models_button = ttk.Button(api_frame, text="Load/Update", command=self.load_models)
        self.load_models_button.grid(row=3, column=2, sticky="e", pady=(5,0))
        self.model_combobox.bind('<<ComboboxSelected>>', self.on_model_change)
        return api_frame

    def _create_save_aio_frame(self, parent):
        save_frame = ttk.LabelFrame(parent, text="Save / AIO", padding=10)
        save_frame.columnconfigure(0, weight=1)
        self.btn_save = ttk.Button(save_frame, text="Save to .SRT file", command=self.save_srt, style="Save.TButton")
        self.btn_save.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.btn_softsub_aio = ttk.Button(save_frame, text="Softsub AIO", command=self.start_softsub_aio_thread, style="SoftsubAIO.TButton")
        self.btn_softsub_aio.grid(row=1, column=0, sticky="ew", pady=(2, 2))
        self.btn_hardsub_aio = ttk.Button(save_frame, text="Hardsub AIO", command=self.start_all_in_one_process_thread, style="HardsubAIO.TButton")
        self.btn_hardsub_aio.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        return save_frame

    def _create_nav_frame(self, parent):
        nav_frame = ttk.LabelFrame(parent, text="Navigation", padding=10)
        nav_frame.columnconfigure(0, weight=1)
        nav_frame.columnconfigure(1, weight=1)
        nav_frame.columnconfigure(2, weight=1)
        self.btn_prev = ttk.Button(nav_frame, text="<< Previous", command=self.prev_sub)
        self.btn_prev.grid(row=0, column=0, sticky="ew", pady=2, padx=(0, 5))
        self.nav_label = ttk.Label(nav_frame, text="Sub 0 / 0", anchor="center")
        self.nav_label.grid(row=0, column=1, sticky="ew", pady=5)
        self.btn_next = ttk.Button(nav_frame, text="Next >>", command=self.next_sub)
        self.btn_next.grid(row=0, column=2, sticky="ew", pady=2, padx=(5, 0))
        self.time_label = ttk.Label(nav_frame, text="00:00:00,000 --> 00:00:00,000", anchor="center")
        self.time_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=5)
        return nav_frame

    def _center_window(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x, y = (screen_width // 2) - (width // 2), (screen_height // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

    def _setup_logging(self):
        text_handler = TextHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        logging.getLogger().addHandler(text_handler)
        logging.getLogger().setLevel(logging.INFO)

    def check_required_tools(self):
        missing = check_tools_availability()
        if missing: messagebox.showwarning("Missing Tools", f"The following tools were not found:\n\n{', '.join(missing)}")

    # --- HÀM check_cuda_support ĐÃ SỬA ---
    def check_cuda_support(self):
        # Hàm này bây giờ chỉ ghi log, không tự ý thay đổi giao diện nữa.
        # Việc thay đổi giao diện sẽ do toggle_hardsub_settings quyết định.
        if not is_cuda_available():
            logging.warning("CUDA not available. GPU acceleration will be disabled for EAST.")
        else:
            logging.info("CUDA is available. GPU acceleration can be enabled for EAST.")

    def clear_temp_folder(self):
        if messagebox.askyesno("Confirm", "Are you sure you want to delete all temporary files?\nThis action cannot be undone."):
            try:
                if os.path.exists(APP_TEMP_PATH):
                    shutil.rmtree(APP_TEMP_PATH)
                    logging.info(f"Temporary folder '{APP_TEMP_PATH}' has been deleted.")
                os.makedirs(APP_TEMP_PATH, exist_ok=True)
                logging.info(f"Temporary folder '{APP_TEMP_PATH}' has been recreated.")
                messagebox.showinfo("Success", "Temporary folder has been cleared successfully.")
            except Exception as e:
                logging.error(f"Failed to clear temporary folder: {e}")
                messagebox.showerror("Error", f"An error occurred while clearing the temp folder:\n{e}")

    def retry_failed_batches(self):
        failed_indices = self.app_context.settings.get('last_failed_batches', [])
        if not failed_indices:
            messagebox.showinfo("Info", "No failed batches to retry.")
            return
        if messagebox.askyesno("Retry", f"Retry {len(failed_indices)} failed batches?"):
            self.start_ocr_thread(indices_to_process=failed_indices)

    def on_common_settings_change(self, event=None):
        self.hardsub_scan_area_height_display_var.set(f"{self.hardsub_scan_area_height_var.get()}%")

    def on_east_settings_change(self, event=None):
        self.east_confidence_display_var.set(f"{self.east_confidence_var.get():.2f}")

    def save_common_settings(self):
        common_settings = {
            "scan_top": self.hardsub_scan_top_var.get(),
            "scan_bottom": self.hardsub_scan_bottom_var.get(),
            "scan_area_height": self.hardsub_scan_area_height_var.get()
        }
        self.app_context.update_settings("common_hardsub_settings", common_settings)
        logging.info(f"Common hardsub settings saved: Scan Top={common_settings['scan_top']}, Scan Bottom={common_settings['scan_bottom']}, Scan Area Height={common_settings['scan_area_height']}%")

    def log_common_settings(self, event=None): self.after(50, self.save_common_settings)

    def save_east_settings(self):
        east_settings = {
            "confidence": round(self.east_confidence_var.get(), 2),
            "quality": self.east_quality_var.get(),
            "use_gpu": self.east_use_gpu_var.get()
        }
        self.app_context.update_settings("east_settings", east_settings)
        logging.info(f"EAST settings saved: Confidence={east_settings['confidence']:.2f}, Quality={east_settings['quality']}, Use GPU={east_settings['use_gpu']}")

    def log_east_settings(self, event=None): self.after(50, self.save_east_settings)

    def save_vsf_settings(self):
        vsf_adv_settings = {
            "moderate_threshold": round(self.vsf_moderate_threshold_var.get(), 2),
            "moderate_threshold_scaled": round(self.vsf_moderate_threshold_scaled_var.get(), 2),
            "image_scale": self.vsf_image_scale_var.get(),
            "vedges_points_line_error": round(self.vsf_vedges_points_line_error_var.get(), 2),
            "min_sum_color_diff": self.vsf_min_sum_color_diff_var.get()
        }
        self.app_context.update_settings("vsf_adv_settings", vsf_adv_settings)
        logging.info(f"VSF advanced settings saved: Moderate Threshold={vsf_adv_settings['moderate_threshold']:.2f}, Scaled Threshold={vsf_adv_settings['moderate_threshold_scaled']:.2f}, Image Scale={vsf_adv_settings['image_scale']}, VEdges Line Error={vsf_adv_settings['vedges_points_line_error']:.2f}, Min Sum Color Diff={vsf_adv_settings['min_sum_color_diff']}")

    def log_vsf_settings(self, event=None): self.after(50, self.save_vsf_settings)

    def _set_widget_state(self, frame, state):
        for widget in frame.winfo_children():
            try:
                # Không thay đổi trạng thái của Checkbutton ở đây
                if not isinstance(widget, ttk.Checkbutton):
                    widget.configure(state=state)
            except tk.TclError:
                pass
            if isinstance(widget, ttk.Frame) or isinstance(widget, ttk.LabelFrame):
                self._set_widget_state(widget, state)

    # --- HÀM toggle_hardsub_settings ĐÃ SỬA ---
    def toggle_hardsub_settings(self):
        selected_method = self.hardsub_process_var.get()
        display_method = "EAST + VSF" if selected_method == "east_vsf" else "VSF Only"
        logging.info(f"Hardsub processing method set to: {display_method}")
        
        # Luôn kiểm tra xem widget đã tồn tại chưa
        if not hasattr(self, 'east_gpu_check'):
            return

        if selected_method == "vsf_only":
            self._set_widget_state(self.vsf_adv_settings_frame, tk.NORMAL)
            self._set_widget_state(self.east_settings_frame, tk.DISABLED)
            # Tắt checkbox GPU một cách tường minh
            self.east_gpu_check.config(state=tk.DISABLED)
        else: # east_vsf
            self._set_widget_state(self.vsf_adv_settings_frame, tk.DISABLED)
            self._set_widget_state(self.east_settings_frame, tk.NORMAL)
            # Chỉ bật checkbox GPU nếu có CUDA
            self.east_gpu_check.config(state=tk.NORMAL if is_cuda_available() else tk.DISABLED)
        
        self.update_idletasks()

    def on_scale_change(self, event=None):
        value = self.temp_var.get()
        stepped_value = round(value / 0.05) * 0.05
        self.temp_var.set(stepped_value)
        self.temp_display_var.set(f"{stepped_value:.2f}")

    def save_advanced_settings(self, event=None):
        self.app_context.update_settings("batch_size", self.batch_size_var.get())
        self.app_context.update_settings("ocr_language", self.ocr_lang_var.get().strip())
        self.app_context.update_settings("generation_config", {"temperature": round(self.temp_var.get(), 2)})
        logging.info(f"Advanced settings updated: Batch Size={self.batch_size_var.get()}, OCR Lang={self.ocr_lang_var.get()}, Temp={self.temp_var.get():.2f}")

    def start_ocr_thread(self, indices_to_process=None):
        if not all([self.app_context.api_key_1, self.app_context.model_name, self.app_context.image_folder]):
            messagebox.showwarning("Missing Info", "API Key, Model, and a loaded session are required.")
            return
        self._set_controls_state(tk.DISABLED, ocr_running=True)
        self.status_label.config(text="Retrying failed OCR..." if indices_to_process else "Processing OCR...")
        self.cancellation_event.clear()
        threading.Thread(target=self.run_ocr_and_update_gui, args=(indices_to_process,), daemon=True).start()

    def cancel_ocr(self):
        self.cancellation_event.set()
        self.status_label.config(text="Operation cancelled.")
        self._set_controls_state(tk.NORMAL)

    def update_ocr_progress(self, message, percentage):
        logging.debug(f"Progress: {message} ({percentage}%)")
        self.status_label.config(text=message)
        self.update_idletasks()

    def run_ocr_and_update_gui(self, indices_to_process=None):
        subtitles, message = self.app_context.run_ocr_pipeline(self.cancellation_event, self.update_ocr_progress, indices_to_process)
        def update_ui():
            if subtitles:
                self.ocr_completed = True
                self.status_label.config(text=f"OCR Complete! {len(self.app_context.subtitles)} subtitles.")
                logging.info(f"OCR Complete! Processed {len(self.app_context.subtitles)} subtitles.")
                self.navigate_to(0)
            else:
                self.status_label.config(text=f"Error: {message}")
                if not self.cancellation_event.is_set(): messagebox.showerror("OCR Error", message)
            self._set_controls_state(tk.NORMAL)
        self.after(0, update_ui)

    def navigate_to(self, index, target_width=None, target_height=None):
        if not self.app_context.subtitles or not (0 <= index < len(self.app_context.subtitles)):
            self.nav_label.config(text="Sub 0 / 0")
            self.time_label.config(text="00:00:00,000 --> 00:00:00,000")
            self.image_canvas.delete("all") # Clear canvas
            self.text_editor.delete('1.0', tk.END)
            return
        self.app_context.current_index = index
        sub = self.app_context.subtitles[index]
        try:
            img_path = os.path.join(self.app_context.image_folder, sub['image_file'])
            pil_img = Image.open(img_path)
            
            self.update_idletasks() # Force update of layout to get accurate dimensions
            
            # Use provided target dimensions if available, otherwise fallback to canvas dimensions
            canvas_w = target_width if target_width is not None else self.image_canvas.winfo_width()
            canvas_h = target_height if target_height is not None else self.image_canvas.winfo_height()

            if canvas_w < 50 or canvas_h < 50: 
                canvas_w, canvas_h = 800, 500 # Fallback for initial size
            
            # Prioritize fitting height
            scale = canvas_h / pil_img.height
            
            # If scaling by height makes it too wide, scale down further to fit width
            if (pil_img.width * scale) > canvas_w:
                scale = canvas_w / pil_img.width
            
            scale = min(scale, 1.0) # Ensure we never scale up

            new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
            
            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                resample_filter = Image.LANCZOS

            pil_img = pil_img.resize(new_size, resample_filter)
            tk_img = ImageTk.PhotoImage(pil_img)
            
            self.image_canvas.delete("all") # Clear previous image
            # Center the image on the canvas
            x_offset = (canvas_w - new_size[0]) / 2
            y_offset = (canvas_h - new_size[1]) / 2
            self.image_canvas.create_image(x_offset, y_offset, anchor=tk.NW, image=tk_img)
            self.image_canvas.image = tk_img # Keep a reference!
        except Exception as e:
            self.image_canvas.delete("all")
            self.image_canvas.create_text(canvas_w / 2, canvas_h / 2, text=f"Error loading image:\n{sub['image_file']}", fill="red", anchor="center")
            logging.error(f"Error loading image {sub['image_file']}: {e}")
        self.text_editor.delete('1.0', tk.END)
        self.text_editor.insert(tk.END, sub.get('text', ''))
        self.nav_label.config(text=f"Sub {index + 1} / {len(self.app_context.subtitles)}")
        self.time_label.config(text=f"{sub['start_srt']} --> {sub['end_srt']}")

    def on_canvas_resize(self, event):
        # Re-render the current subtitle image when the canvas size changes
        if self.app_context.subtitles and 0 <= self.app_context.current_index < len(self.app_context.subtitles):
            self.navigate_to(self.app_context.current_index, target_width=event.width, target_height=event.height)

    def sync_text_from_widget(self):
        if self.app_context.subtitles and 0 <= self.app_context.current_index < len(self.app_context.subtitles):
            self.app_context.subtitles[self.app_context.current_index]['text'] = self.text_editor.get('1.0', tk.END).strip()

    def prev_sub(self):
        self.sync_text_from_widget()
        if self.app_context.current_index > 0:
            current_w = self.image_canvas.winfo_width()
            current_h = self.image_canvas.winfo_height()
            self.navigate_to(self.app_context.current_index - 1, target_width=current_w, target_height=current_h)

    def next_sub(self):
        self.sync_text_from_widget()
        if self.app_context.current_index < len(self.app_context.subtitles) - 1:
            current_w = self.image_canvas.winfo_width()
            current_h = self.image_canvas.winfo_height()
            self.navigate_to(self.app_context.current_index + 1, target_width=current_w, target_height=current_h)

    def save_srt(self):
        self.sync_text_from_widget()
        if not self.app_context.source_file_path:
            messagebox.showerror("Error", "Source file path not available.")
            return
        source_path = self.app_context.source_file_path
        base_name = os.path.splitext(os.path.basename(source_path))[0]
        initial_dir = self.app_context.settings.get("last_save_dir", os.path.expanduser("~"))
        ocr_lang = self.ocr_lang_var.get().strip()
        lang_map = {'Vietnamese': 'vi', 'English': 'en', 'Japanese': 'ja', 'Chinese': 'zh','Korean': 'ko', 'French': 'fr', 'German': 'de', 'Spanish': 'es','Italian': 'it', 'Russian': 'ru', 'Portuguese': 'pt', 'Dutch': 'nl','Polish': 'pl', 'Turkish': 'tr', 'Arabic': 'ar', 'Hindi': 'hi','Thai': 'th', 'Indonesian': 'id', 'Malay': 'ms', 'Filipino': 'fil'}
        lang_code = lang_map.get(ocr_lang)
        file_name = f"{base_name}.{lang_code}.srt" if lang_code else f"{base_name}.srt"
        srt_path = filedialog.asksaveasfilename(initialdir=initial_dir, initialfile=file_name, defaultextension=".srt", filetypes=[("SRT files", "*.srt")])
        if not srt_path: return
        try:
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, sub in enumerate(self.app_context.subtitles):
                    f.write(f"{i + 1}\n{sub['start_srt']} --> {sub['end_srt']}\n{sub.get('text', '').strip()}\n\n")
            if self.app_context.source_file_is_from_ytdlp:
                video_source_path = self.app_context.source_file_path
                video_dest_path = os.path.join(os.path.dirname(srt_path), os.path.basename(video_source_path))
                shutil.copy(video_source_path, video_dest_path)
                logging.info(f"Copied video file to: {video_dest_path}")
                messagebox.showinfo("Complete", f"SRT file and video saved to:\n{os.opath.dirname(srt_path)}")
            else:
                messagebox.showinfo("Complete", f"SRT file saved to:\n{srt_path}")
            self.app_context.update_settings("last_save_dir", os.path.dirname(srt_path))
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file(s): {e}")

    def auto_load_models_on_startup(self):
        if self.api_key_var.get(): self.load_models()
        
    def load_models(self):
        api_key = self.api_key_var.get().strip()
        if not api_key: messagebox.showerror("API Key Error", "Please enter an API Key."); return
        
        self.app_context.update_settings("api_key_1", self.api_key_var.get().strip())
        self.app_context.update_settings("api_key_2", self.api_key_2_var.get().strip())
        self.app_context.update_settings("api_key_3", self.api_key_3_var.get().strip())

        self.status_label.config(text="Loading model...")
        threading.Thread(target=self._load_models_worker, args=(api_key,), daemon=True).start()
        
    def _load_models_worker(self, api_key):
        models, error = self.app_context.get_available_models()
        if error: messagebox.showerror("Error", error); self.status_label.config(text="Error!"); return
        self.model_combobox['values'] = models
        last_model = self.app_context.settings.get("last_model")
        if last_model in models: self.model_var.set(last_model)
        elif models: self.model_combobox.current(0)
        self.app_context.update_settings("last_model", self.model_var.get())
        logging.info(f"Model set to: {self.model_var.get()}")
        self.status_label.config(text="Ready.")
        self._set_controls_state(tk.NORMAL)

    def load_session(self):
        sessions = self.app_context.get_session_list()
        if not sessions: messagebox.showinfo("Info", "No saved sessions found."); return
        dialog = SessionSelectionDialog(self, sessions)
        self.wait_window(dialog)
        if dialog.selected_session:
            self.ocr_completed = False 
            session_path = os.path.join(TEMP_DIR_NAME, dialog.selected_session)
            self.status_label.config(text=f"Loading session: {dialog.selected_session}...")
            subtitles, message = self.app_context.load_session_from_folder(session_path)
            if subtitles:
                if any("batch_" in f for f in os.listdir(os.path.join(session_path, "logs"))): self.ocr_completed = True
                self.status_label.config(text=message)
                self.navigate_to(0)
            else:
                messagebox.showerror("Error", message)
            self._set_controls_state(tk.NORMAL)

    def on_model_change(self, event=None):
        self.app_context.update_settings("last_model", self.model_var.get())
        logging.info(f"Model changed to: {self.model_var.get()}")

    def select_source_file(self):
        self.app_context.cleanup_current_session_temp()
        self.app_context.source_file_is_from_ytdlp = False
        self.ocr_completed = False
        video_formats = "*.mkv *.mp4 *.ts *.wmv *.mov *.webm *.avi *.flv"
        filetypes = [
            ("All Supported", f"{video_formats} *.sup *.pgs *.xml *.html"),
            ("Video Files", video_formats),
            ("Subtitle Files", "*.sup *.pgs"),
            ("Timing Files", "*.xml *.html")
        ]
        source_path = filedialog.askopenfilename(title="Select Source File", filetypes=filetypes)
        if not source_path:
            return
        self.app_context.source_file_path = source_path
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        
        ext = os.path.splitext(source_path)[1].lower()
        
        if ext in ['.mkv', '.mp4', '.ts', '.wmv', '.mov', '.webm', '.avi', '.flv']:
            threading.Thread(target=self.handle_video_file, args=(source_path,), daemon=True).start()
        elif ext in ['.sup', '.pgs']:
            threading.Thread(target=self.handle_standalone_subtitle_file, args=(source_path,), daemon=True).start()
        elif ext in ['.xml', '.html']:
            threading.Thread(target=self.handle_timing_file, args=(source_path,), daemon=True).start()
        else:
            messagebox.showerror("Error", "Unsupported file format.")
            self._set_controls_state(tk.NORMAL)
    
    def select_hardsub_video(self):
        self.app_context.cleanup_current_session_temp()
        self.app_context.source_file_is_from_ytdlp = False
        self.ocr_completed = False
        video_formats = "*.mkv *.mp4 *.ts *.wmv *.mov *.webm *.avi *.flv"
        source_path = filedialog.askopenfilename(title="Select Video for Hardsub OCR", filetypes=[("Video Files", video_formats)])
        if not source_path: return
        self.app_context.hardsub_video_path = source_path
        self.app_context.source_file_path = source_path
        logging.info(f"Selected hardsub video: {source_path}")
        self._set_controls_state(tk.NORMAL)

    def start_hardsub_detection_thread(self):
        if not self.app_context.hardsub_video_path:
            messagebox.showwarning("Input Missing", "Please select a video file first.")
            return
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        process_method = self.hardsub_process_var.get()
        video_path = self.app_context.hardsub_video_path
        common_options = {"scan_top": self.hardsub_scan_top_var.get(), "scan_bottom": self.hardsub_scan_bottom_var.get(), "scan_area_height": self.hardsub_scan_area_height_var.get()}
        if process_method == "east_vsf":
            east_options = {"use_gpu": self.east_use_gpu_var.get(), "confidence": self.east_confidence_var.get(), "quality": int(self.east_quality_var.get().replace('px', ''))}
            options = {**common_options, **east_options}
            threading.Thread(target=self.handle_hardsub_video_east, args=(video_path, options), daemon=True).start()
        else:
            vsf_adv_options = {
                "moderate_threshold": self.vsf_moderate_threshold_var.get(),
                "moderate_threshold_scaled": self.vsf_moderate_threshold_scaled_var.get(),
                "image_scale": self.vsf_image_scale_var.get(),
                "vedges_points_line_error": self.vsf_vedges_points_line_error_var.get(),
                "min_sum_color_diff": self.vsf_min_sum_color_diff_var.get()
            }
            options = {**common_options, **vsf_adv_options}
            threading.Thread(target=self.handle_hardsub_video_vsf_only, args=(video_path, options), daemon=True).start()

    def handle_hardsub_video_east(self, video_path, options):
        subtitles, error, flag_file, run_id = self.app_context.process_hardsub_video_east(video_path, options, self.update_ocr_progress, self.cancellation_event)
        def update_ui_after_east():
            if error:
                messagebox.showerror("Hardsub Error", error)
                self.status_label.config(text="Hardsub analysis failed.")
                self._set_controls_state(tk.NORMAL)
                return
            if subtitles:
                self.status_label.config(text=f"Found {len(subtitles)} potential subtitles. Refining with VSF in background...")
                self.navigate_to(0)
            if flag_file:
                self.monitor_vsf_process(flag_file, "EAST+VSF", run_id)
            else:
                self.status_label.config(text=f"Process complete! Found {len(subtitles) or 0} subtitles.")
                self._set_controls_state(tk.NORMAL)
        self.after(0, update_ui_after_east)

    def handle_hardsub_video_vsf_only(self, video_path, options):
        _, error, flag_file, run_id = self.app_context.process_hardsub_video_vsf_only(video_path, options, self.update_ocr_progress, self.cancellation_event)
        def update_ui_after_vsf_start():
            if error:
                messagebox.showerror("VSF Error", error)
                self.status_label.config(text="VSF process failed to start.")
                self._set_controls_state(tk.NORMAL)
                return
            if flag_file:
                self.monitor_vsf_process(flag_file, "VSF-Only", run_id)
            else:
                self.status_label.config(text="VSF process finished unexpectedly.")
                self._set_controls_state(tk.NORMAL)
        self.after(0, update_ui_after_vsf_start)

    def monitor_vsf_process(self, flag_file, method_name, run_id):
        if os.path.exists(flag_file):
            self.status_label.config(text=f"{method_name} is running... This may take a while.")
            self.after(2000, self.monitor_vsf_process, flag_file, method_name, run_id)
        else:
            self.status_label.config(text=f"{method_name} refinement complete. Merging results...")
            logging.info(f"{method_name} process finished. Merging results.")
            self.update_idletasks()
            refined_subtitles = self.app_context.merge_vsf_results(run_id)
            if refined_subtitles:
                self.status_label.config(text=f"Merge complete! Found {len(refined_subtitles)} refined subtitles.")
                self.navigate_to(0)
            else:
                self.status_label.config(text=f"{method_name} ran, but no subtitles were found.")
            self._set_controls_state(tk.NORMAL)

    def handle_video_file(self, video_path):
        self.status_label.config(text=f"Scanning: {os.path.basename(video_path)}...")
        streams, error = self.app_context.inspect_video_subtitles(video_path)
        if error or not streams:
            messagebox.showerror("Error", error or "No image subtitle streams found.")
            self._set_controls_state(tk.NORMAL); return
        dialog = SubtitleSelectionDialog(self, streams)
        self.wait_window(dialog)
        if dialog.selected_stream_index is not None:
            stream_index = streams[dialog.selected_stream_index]['index']
            self.status_label.config(text="Extracting subtitles...")
            _, _, error = self.app_context.extract_subtitles_from_video(video_path, stream_index, self.update_extraction_progress, self.cancellation_event)
            if error:
                if "cancelled" not in error: messagebox.showerror("Error", error)
            else:
                self.status_label.config(text=f"Extraction complete! {len(self.app_context.subtitles)} subtitles.")
                if self.app_context.subtitles: self.navigate_to(0)
        self._set_controls_state(tk.NORMAL)
            
    def handle_timing_file(self, timing_path):
        self.status_label.config(text="Processing timing file...")
        subtitles, error = self.app_context.load_timing_file(timing_path)
        if error: messagebox.showerror("Error", error)
        else:
            self.status_label.config(text=f"Loaded {len(subtitles)} subtitles!")
            if subtitles: self.navigate_to(0)
        self._set_controls_state(tk.NORMAL)
        
    def update_extraction_progress(self, percentage):
        # self.progress_bar['value'] = percentage
        pass
        
    def _set_controls_state(self, state, ocr_running=False, extraction_running=False):
        is_disabled = state == tk.DISABLED or ocr_running or extraction_running
        effective_state = tk.DISABLED if is_disabled else tk.NORMAL
        for widget_name in ['btn_select_source', 'btn_load_session', 'btn_select_hardsub_video', 'load_models_button', 'btn_detect_hardsub', 'btn_hardsub_aio', 'btn_softsub_aio']:
            if hasattr(self, widget_name):
                widget = getattr(self, widget_name)
                if widget_name == 'btn_detect_hardsub':
                    widget.config(state=tk.NORMAL if self.app_context.hardsub_video_path and not is_disabled else tk.DISABLED)
                else:
                    widget.config(state=effective_state)
        self.btn_cancel_ocr.config(state=tk.NORMAL if ocr_running or extraction_running else tk.DISABLED)
        subtitles_loaded = bool(self.app_context.subtitles) and not is_disabled
        self.btn_start_ocr.config(state=tk.NORMAL if subtitles_loaded else tk.DISABLED)
        has_failed = bool(self.app_context.settings.get('last_failed_batches'))
        self.btn_retry_failed.config(state=tk.NORMAL if subtitles_loaded and has_failed else tk.DISABLED)
        self.btn_prev.config(state=tk.NORMAL if subtitles_loaded else tk.DISABLED)
        self.btn_next.config(state=tk.NORMAL if subtitles_loaded else tk.DISABLED)
        self.btn_save.config(state=tk.NORMAL if self.ocr_completed and not is_disabled else tk.DISABLED)
        hardsub_video_loaded = bool(self.app_context.hardsub_video_path) and not is_disabled
        self.btn_hardsub_aio.config(state=tk.NORMAL if hardsub_video_loaded else tk.DISABLED)
        softsub_ready = bool(self.app_context.source_file_path) and not self.app_context.hardsub_video_path and not is_disabled
        self.btn_softsub_aio.config(state=tk.NORMAL if softsub_ready else tk.DISABLED)

    def handle_drop(self, event):
        filepath = event.data.strip('{}')
        if not os.path.exists(filepath):
            logging.error(f"Dropped file path does not exist: {filepath}")
            return
        selected_tab_index = self.notebook.index(self.notebook.select())
        if selected_tab_index == 0:
            self.handle_softsub_file_drop(filepath)
        elif selected_tab_index == 1:
            self.handle_hardsub_file_drop(filepath)

    def handle_softsub_file_drop(self, source_path):
        self.app_context.cleanup_current_session_temp()
        self.app_context.source_file_is_from_ytdlp = False
        self.ocr_completed = False
        self.app_context.source_file_path = source_path
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        ext = os.path.splitext(source_path)[1].lower()
        if ext in ['.mkv', '.mp4', '.ts', '.wmv', '.mov', '.webm', '.avi', '.flv']:
            threading.Thread(target=self.handle_video_file, args=(source_path,), daemon=True).start()
        elif ext in ['.sup', '.pgs']:
            threading.Thread(target=self.handle_standalone_subtitle_file, args=(source_path,), daemon=True).start()
        elif ext in ['.xml', '.html']:
            threading.Thread(target=self.handle_timing_file, args=(source_path,), daemon=True).start()
        else:
            messagebox.showerror("Error", "Unsupported file format for Softsub OCR.")
            self._set_controls_state(tk.NORMAL)

    def handle_standalone_subtitle_file(self, subtitle_path: str):
        """Handles the processing of a standalone .sup or .pgs file."""
        self.status_label.config(text=f"Processing subtitle file: {os.path.basename(subtitle_path)}...")
        subtitles, error = self.app_context.process_standalone_subtitle_file(subtitle_path)
        if error:
            messagebox.showerror("Error", error)
        else:
            self.status_label.config(text=f"Processing complete! {len(subtitles)} subtitles found.")
            if subtitles:
                self.navigate_to(0)
        self._set_controls_state(tk.NORMAL)

    def handle_hardsub_file_drop(self, source_path):
        self.app_context.cleanup_current_session_temp()
        self.app_context.source_file_is_from_ytdlp = False
        self.ocr_completed = False
        ext = os.path.splitext(source_path)[1].lower()
        if ext not in ['.mkv', '.mp4', '.ts', '.wmv', '.mov', '.webm', '.avi', '.flv']:
            messagebox.showerror("Error", "Unsupported file format for Hardsub OCR. Please drop a video file.")
            return
        self.app_context.hardsub_video_path = source_path
        self.app_context.source_file_path = source_path
        logging.info(f"Selected hardsub video via drop: {source_path}")
        self._set_controls_state(tk.NORMAL)

    def start_video_download_thread(self):
        video_url = self.video_url_var.get()
        if not video_url:
            messagebox.showwarning("Warning", "Please enter a video URL.")
            return
        self.app_context.cleanup_current_session_temp()
        self.ocr_completed = False
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        threading.Thread(target=self.handle_video_download, args=(video_url,), daemon=True).start()

    def handle_video_download(self, video_url):
        downloaded_path, error = self.app_context.download_video_from_url(video_url, self.update_ocr_progress)
        def update_ui():
            if error:
                messagebox.showerror("Download Error", error)
                self.status_label.config(text="Download failed.")
            else:
                self.status_label.config(text="Video downloaded successfully.")
                self.app_context.hardsub_video_path = downloaded_path
                self.app_context.source_file_path = downloaded_path
                self.btn_detect_hardsub.config(state=tk.NORMAL)
                logging.info(f"Video downloaded and selected: {downloaded_path}")
            self._set_controls_state(tk.NORMAL)
        self.after(0, update_ui)

    def save_srt_auto(self):
        self.sync_text_from_widget()
        if not self.app_context.subtitles:
            logging.error("Auto-save failed: No subtitles available.")
            return None
        source_path = self.app_context.source_file_path
        if not source_path:
            logging.error("Auto-save failed: Source file path not available.")
            return None
        base_name = os.path.splitext(os.path.basename(source_path))[0]
        ocr_lang = self.ocr_lang_var.get().strip()
        lang_map = {'Vietnamese': 'vi', 'English': 'en', 'Japanese': 'ja', 'Chinese': 'zh','Korean': 'ko', 'French': 'fr', 'German': 'de', 'Spanish': 'es','Italian': 'it', 'Russian': 'ru', 'Portuguese': 'pt', 'Dutch': 'nl','Polish': 'pl', 'Turkish': 'tr', 'Arabic': 'ar', 'Hindi': 'hi','Thai': 'th', 'Indonesian': 'id', 'Malay': 'ms', 'Filipino': 'fil'}
        lang_code = lang_map.get(ocr_lang)
        file_name = f"{base_name}.{lang_code}.srt" if lang_code else f"{base_name}.srt"
        if self.app_context.source_file_is_from_ytdlp:
            save_dir = self.app_context.current_session_dir
        else:
            save_dir = os.path.dirname(source_path)
        srt_path = os.path.join(save_dir, file_name)
        try:
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, sub in enumerate(self.app_context.subtitles):
                    f.write(f"{i + 1}\n{sub['start_srt']} --> {sub['end_srt']}\n{sub.get('text', '').strip()}\n\n")
            logging.info(f"SRT file automatically saved to: {srt_path}")
            return srt_path
        except Exception as e:
            logging.error(f"Could not auto-save file to {srt_path}: {e}")
            return None

    def start_all_in_one_process_thread(self):
        if not self.app_context.hardsub_video_path:
            messagebox.showwarning("Warning", "Please select a video for hardsub OCR first.")
            return
        if not all([self.app_context.api_key_1, self.app_context.model_name]):
            messagebox.showwarning("Missing Info", "API Key and Model are required.")
            return
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        threading.Thread(target=self.run_all_in_one_process, daemon=True).start()

    def run_all_in_one_process(self):
        try:
            video_path = self.app_context.hardsub_video_path
            process_method = self.hardsub_process_var.get()
            self.after(0, lambda: self.status_label.config(text=f"[1/4] Starting subtitle detection ({process_method})..."))
            common_options = {"scan_top": self.hardsub_scan_top_var.get(), "scan_bottom": self.hardsub_scan_bottom_var.get(), "scan_area_height": self.hardsub_scan_area_height_var.get()}
            subtitles, error, flag_file, run_id = None, None, None, None
            if process_method == "east_vsf":
                east_options = {"use_gpu": self.east_use_gpu_var.get(), "confidence": self.east_confidence_var.get(), "quality": int(self.east_quality_var.get().replace('px', ''))}
                options = {**common_options, **east_options}
                subtitles, error, flag_file, run_id = self.app_context.process_hardsub_video_east(video_path, options, self.update_ocr_progress, self.cancellation_event)
            else:
                vsf_adv_options = {
                    "moderate_threshold": self.vsf_moderate_threshold_var.get(),
                    "moderate_threshold_scaled": self.vsf_moderate_threshold_scaled_var.get(),
                    "image_scale": self.vsf_image_scale_var.get(),
                    "vedges_points_line_error": self.vsf_vedges_points_line_error_var.get(),
                    "min_sum_color_diff": self.vsf_min_sum_color_diff_var.get()
                }
                options = {**common_options, **vsf_adv_options}
                _, error, flag_file, run_id = self.app_context.process_hardsub_video_vsf_only(video_path, options, self.update_ocr_progress, self.cancellation_event)
            if self.cancellation_event.is_set(): return
            if error:
                self.after(0, lambda: messagebox.showerror("All-in-One Error", f"Subtitle detection failed: {error}"))
                return
            if subtitles:
                self.after(0, lambda: self.navigate_to(0))
            if flag_file:
                self.after(0, lambda: self.status_label.config(text="[2/4] VSF is running... This may take a while."))
                while os.path.exists(flag_file):
                    if self.cancellation_event.is_set(): return
                    time.sleep(2)
                
                def stop_vsf_progress():
                    self.status_label.config(text="VSF complete. Merging results...")
                    pass
                self.after(0, stop_vsf_progress)

                self.app_context.merge_vsf_results(run_id)
                self.after(0, lambda: self.navigate_to(0))
            if not self.app_context.subtitles:
                self.after(0, lambda: messagebox.showwarning("All-in-One Info", "No subtitles found after detection phase."))
                return
            self.after(0, lambda: self.status_label.config(text="[3/4] Starting OCR process..."))
            ocr_subtitles, ocr_message = self.app_context.run_ocr_pipeline(self.cancellation_event, self.update_ocr_progress)
            if self.cancellation_event.is_set(): return
            if not ocr_subtitles:
                self.after(0, lambda: messagebox.showerror("All-in-One Error", f"OCR process failed: {ocr_message}"))
                return
            self.ocr_completed = True
            self.after(0, lambda: self.status_label.config(text="OCR Complete!"))
            self.after(0, lambda: self.navigate_to(0))
            self.after(0, lambda: self.status_label.config(text="[4/4] Saving SRT file..."))
            saved_path = self.save_srt_auto()
            
            def final_aio_update():
                if saved_path:
                    messagebox.showinfo("All-in-One Complete", f"Process finished successfully.\nSRT file saved to:\n{saved_path}")
                else:
                    messagebox.showerror("All-in-One Error", "Failed to save the SRT file.")
                
                self.status_label.config(text="Ready.")

            self.after(0, final_aio_update)

        except Exception as e:
            logging.error(f"An error occurred during the all-in-one process: {e}", exc_info=True)
            self.after(0, lambda e=e: messagebox.showerror("All-in-One Error", f"An unexpected error occurred: {e}"))
        finally:
            if self.cancellation_event.is_set():
                self.after(0, lambda: self.status_label.config(text="Operation cancelled."))
            self.after(0, lambda: self._set_controls_state(tk.NORMAL))

    def start_softsub_aio_thread(self):
        if not self.app_context.source_file_path:
            messagebox.showwarning("Warning", "Please select a source video file first.")
            return
        if not all([self.app_context.api_key_1, self.app_context.model_name]):
            messagebox.showwarning("Missing Info", "API Key and Model are required.")
            return
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        threading.Thread(target=self.run_softsub_aio_process, daemon=True).start()

    def run_softsub_aio_process(self):
        try:
            source_path = self.app_context.source_file_path
            ext = os.path.splitext(source_path)[1].lower()

            # --- GIAI ĐOẠN 1 & 2: CHỈ TRÍCH XUẤT NẾU LÀ VIDEO ---
            if ext in ['.mkv', '.mp4', '.ts', '.wmv', '.mov', '.webm', '.avi', '.flv']:
                self.after(0, lambda: self.status_label.config(text="[1/4] Scanning for subtitle streams..."))
                streams, error = self.app_context.inspect_video_subtitles(source_path)
                if self.cancellation_event.is_set(): return
                if error or not streams:
                    self.after(0, lambda: messagebox.showerror("Softsub AIO Error", error or "No image subtitle streams found."))
                    return

                # Tự động chọn stream đầu tiên
                stream_index = streams[0]['index']
                stream_title = streams[0].get('tags', {}).get('title', 'Untitled')
                self.after(0, lambda: self.status_label.config(text=f"Found stream: {stream_title}. Extracting..."))
                
                self.after(0, lambda: self.status_label.config(text="[2/4] Extracting subtitles..."))
                _, _, error = self.app_context.extract_subtitles_from_video(source_path, stream_index, self.update_extraction_progress, self.cancellation_event)
                if self.cancellation_event.is_set(): return
                if error:
                    self.after(0, lambda: messagebox.showerror("Softsub AIO Error", f"Subtitle extraction failed: {error}"))
                    return
                self.after(0, lambda: self.navigate_to(0))
            elif self.app_context.subtitles:
                 logging.info("Source is a subtitle/timing file, skipping extraction.")
                 self.after(0, lambda: self.status_label.config(text="[1-2/4] Subtitle file loaded, skipping extraction."))
            else:
                self.after(0, lambda: messagebox.showerror("Softsub AIO Error", "No subtitles loaded to process."))
                return

            # --- GIAI ĐOẠN 3: OCR ---
            self.after(0, lambda: self.status_label.config(text="[3/4] Starting OCR process..."))
            ocr_subtitles, ocr_message = self.app_context.run_ocr_pipeline(self.cancellation_event, self.update_ocr_progress)
            if self.cancellation_event.is_set(): return
            if not ocr_subtitles:
                self.after(0, lambda: messagebox.showerror("Softsub AIO Error", f"OCR process failed: {ocr_message}"))
                return
            self.ocr_completed = True
            self.after(0, lambda: self.status_label.config(text="OCR Complete!"))
            self.after(0, lambda: self.navigate_to(0))
            self.after(0, lambda: self.status_label.config(text="[4/4] Saving SRT file..."))
            saved_path = self.save_srt_auto()
            if saved_path:
                self.after(0, lambda: messagebox.showinfo("Softsub AIO Complete", f"Process finished successfully.\nSRT file saved to:\n{saved_path}"))
            else:
                self.after(0, lambda: messagebox.showerror("Softsub AIO Error", "Failed to save the SRT file."))
        except Exception as e:
            logging.error(f"An error occurred during the softsub AIO process: {e}")
            self.after(0, lambda: messagebox.showerror("Softsub AIO Error", f"An unexpected error occurred: {e}"))
        finally:
            if self.cancellation_event.is_set():
                self.after(0, lambda: self.status_label.config(text="Operation cancelled."))
            self.after(0, lambda: self._set_controls_state(tk.NORMAL))
