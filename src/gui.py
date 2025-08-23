# src/gui.py

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, font
from tkextrafont import Font
import threading
from PIL import Image, ImageTk
import logging

from src.app_context import AppContext
from src.ui_components import SubtitleSelectionDialog, SessionSelectionDialog, create_ocr_controls, create_advanced_settings
from src.utils import check_tools_availability, is_cuda_available
from src.settings import TEMP_DIR_NAME
from src.softsub_tab import create_softsub_tab
from src.hardsub_tab import create_hardsub_tab

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

class SubtitlePreviewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Easy AI Subtitle OCR")
        self.geometry("1100x900")
        self.minsize(1000, 1000)
        self._center_window(1200, 1000)
        
        self.app_context = AppContext()
        self._init_vars()
        self._configure_styles()
        self._create_menu()
        self._create_widgets()
        self._setup_logging()
        
        self.after(100, self.auto_load_models_on_startup)
        self.after(200, self.check_required_tools)
        self.after(300, self.check_cuda_support)
        self.after(400, lambda: self._set_controls_state(tk.NORMAL))
        
        try:
            self.font = Font(file="assets/fonts/NotoSans-Regular.ttf", family="Noto Sans")
        except Exception as e:
            logging.error(f"Failed to load font: {e}")
            messagebox.showerror("Font Error", f"Could not load the Noto Sans font.\n{e}")

    def _init_vars(self):
        self.api_key_var = tk.StringVar(value=self.app_context.api_key)
        self.model_var = tk.StringVar(value=self.app_context.model_name)
        self.batch_size_var = tk.IntVar(value=self.app_context.batch_size)
        config = self.app_context.generation_config
        self.temp_var = tk.DoubleVar(value=config.get("temperature", 0.5))
        self.temp_display_var = tk.StringVar(value=f"{self.temp_var.get():.2f}")
        self.ocr_lang_var = tk.StringVar(value=self.app_context.ocr_language)
        self.cancellation_event = threading.Event()
        self.ocr_completed = False
        # Hardsub settings
        self.hardsub_scan_top_var = tk.BooleanVar(value=True)
        self.hardsub_scan_bottom_var = tk.BooleanVar(value=True)
        self.hardsub_scan_area_height_var = tk.IntVar(value=30)
        self.hardsub_scan_area_height_display_var = tk.StringVar(value="30%")
        self.hardsub_use_gpu_var = tk.BooleanVar(value=True)
        self.hardsub_confidence_var = tk.DoubleVar(value=0.5)
        self.hardsub_confidence_display_var = tk.StringVar(value="0.50")
        self.hardsub_quality_var = tk.StringVar(value='Fast (320px)')


    def _configure_styles(self):
        style = ttk.Style(self)
        selected_bg = "#e0e8f0"
        style.configure("Highlighted.TNotebook.Tab", 
                        background=selected_bg,
                        font=('Arial', 10, 'bold'),
                        padding=[10, 5])
        style.map("Highlighted.TNotebook.Tab",
                  background=[("selected", selected_bg)])
        style.configure("TNotebook", tabposition='n')

    def _create_widgets(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        left_frame = self._create_left_panel()
        left_frame.grid(row=0, column=0, sticky="ns", padx=5, pady=5)
        right_frame = self._create_right_panel()
        right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    def _create_left_panel(self):
        left_container = ttk.Frame(self, width=420)
        left_container.grid_propagate(False)
        left_container.grid_rowconfigure(0, weight=1)
        left_container.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(left_container, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        content_frame = ttk.Frame(canvas, padding=5)
        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        content_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        content_frame.grid_columnconfigure(0, weight=1)
        api_frame = self._create_api_config_frame(content_frame)
        api_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        notebook = ttk.Notebook(content_frame, style="Highlighted.TNotebook")
        notebook.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        softsub_tab_frame = create_softsub_tab(notebook, self)
        notebook.add(softsub_tab_frame, text="Softsub OCR")
        hardsub_tab_frame = create_hardsub_tab(notebook, self)
        notebook.add(hardsub_tab_frame, text="Hardsub OCR")
        ocr_controls_frame = create_ocr_controls(content_frame, self)
        ocr_controls_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        adv_settings_frame = create_advanced_settings(content_frame, self)
        adv_settings_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        nav_frame = self._create_nav_save_frame(content_frame)
        nav_frame.grid(row=4, column=0, sticky="ew")
        return left_container

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Manage Cache...", command=self.manage_cache)

    def _create_api_config_frame(self, parent):
        api_frame = ttk.LabelFrame(parent, text="API Configuration", padding=10)
        api_frame.columnconfigure(1, weight=1)
        ttk.Label(api_frame, text="Google API Key:").grid(row=0, column=0, sticky="w", pady=2)
        self.api_key_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=0, column=1, columnspan=2, sticky="ew")
        self.load_models_button = ttk.Button(api_frame, text="Load/Update Model", command=self.load_models)
        self.load_models_button.grid(row=1, column=1, sticky="e", pady=(5,0))
        ttk.Label(api_frame, text="Model:").grid(row=2, column=0, sticky="w", pady=2)
        self.model_combobox = ttk.Combobox(api_frame, textvariable=self.model_var, state="readonly")
        self.model_combobox.grid(row=2, column=1, columnspan=2, sticky="ew")
        self.model_combobox.bind("<<ComboboxSelected>>", self.on_model_change)
        return api_frame

    def _create_nav_save_frame(self, parent):
        nav_frame = ttk.LabelFrame(parent, text="Navigation & Save", padding=10)
        nav_frame.columnconfigure(0, weight=1)
        self.btn_prev = ttk.Button(nav_frame, text="<< Previous", command=self.prev_sub)
        self.btn_prev.grid(row=0, column=0, sticky="ew", pady=2)
        self.nav_label = ttk.Label(nav_frame, text="Sub 0 / 0", anchor="center")
        self.nav_label.grid(row=1, column=0, sticky="ew", pady=5)
        self.time_label = ttk.Label(nav_frame, text="00:00:00,000 --> 00:00:00,000", anchor="center")
        self.time_label.grid(row=2, column=0, sticky="ew", pady=5)
        self.btn_next = ttk.Button(nav_frame, text="Next >>", command=self.next_sub)
        self.btn_next.grid(row=3, column=0, sticky="ew", pady=2)
        self.btn_save = ttk.Button(nav_frame, text="Save to .SRT file", command=self.save_srt)
        self.btn_save.grid(row=4, column=0, sticky="ew", pady=(5, 2))
        return nav_frame

    def _create_right_panel(self):
        right_frame = ttk.Frame(self)
        right_frame.grid_rowconfigure(0, weight=4)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_rowconfigure(2, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)
        try:
            self.text_font = font.Font(family="Noto Sans", size=20, weight="bold")
        except tk.TclError:
            self.text_font = font.Font(family="Arial", size=20, weight="bold")
        image_container = ttk.Frame(right_frame)
        image_container.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        image_container.grid_propagate(False)
        image_container.grid_rowconfigure(0, weight=1)
        image_container.grid_columnconfigure(0, weight=1)
        self.image_label = ttk.Label(image_container, text="Subtitle Image Will Appear Here", anchor="center", background="gray")
        self.image_label.grid(row=0, column=0, sticky="nsew")
        self.text_editor = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, font=self.text_font, height=4)
        self.text_editor.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        log_frame = ttk.LabelFrame(right_frame, text="Log", padding=5)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state="disabled", font=("Courier New", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        return right_frame

    def _center_window(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

    def _setup_logging(self):
        text_handler = TextHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        text_handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(text_handler)

    def check_required_tools(self):
        missing = check_tools_availability()
        if missing:
            msg = "The following tools were not found or are not executable:\n\n{tools}\n\nPlease ensure they are in assets/tools/ and have the necessary permissions.".format(tools="\n".join(missing))
            messagebox.showwarning("Missing Tools", msg)

    def check_cuda_support(self):
        if not is_cuda_available():
            self.hardsub_use_gpu_var.set(False)
            if hasattr(self, 'gpu_check'):
                self.gpu_check.config(state=tk.DISABLED)
            logging.warning("CUDA not available. GPU acceleration has been disabled.")
        else:
            if hasattr(self, 'gpu_check'):
                self.gpu_check.config(state=tk.NORMAL)
            logging.info("CUDA is available. GPU acceleration is enabled.")

    def manage_cache(self):
        messagebox.showinfo("Info", "Cache management feature will be developed in the future.")

    def retry_failed_batches(self):
        failed_indices = self.app_context.settings.get('last_failed_batches', [])
        if not failed_indices:
            messagebox.showinfo("Info", "No failed batches to retry.")
            return
        msg = f"Found {len(failed_indices)} failed batches. Do you want to retry processing them?"
        if messagebox.askyesno("Retry Failed Batches", msg):
            self.start_ocr_thread(indices_to_process=failed_indices)

    def on_hardsub_settings_change(self, event=None):
        self.hardsub_scan_area_height_display_var.set(f"{self.hardsub_scan_area_height_var.get()}%")
        self.hardsub_confidence_display_var.set(f"{self.hardsub_confidence_var.get():.2f}")

    def on_scale_change(self, event=None):
        self.temp_display_var.set(f"{self.temp_var.get():.2f}")
        self.save_advanced_settings()

    def save_advanced_settings(self, event=None):
        self.app_context.update_settings("batch_size", self.batch_size_var.get())
        self.app_context.update_settings("ocr_language", self.ocr_lang_var.get().strip())
        generation_config = {"temperature": self.temp_var.get()}
        self.app_context.update_settings("generation_config", generation_config)
        logging.info("Advanced settings saved.")

    def start_ocr_thread(self, indices_to_process=None):
        if not all([self.app_context.api_key, self.app_context.model_name, self.app_context.image_folder]):
            messagebox.showwarning("Missing Info", "API Key, Model, and a loaded session are required.")
            return
        self._set_controls_state(tk.DISABLED, ocr_running=True)
        status_text = "Retrying failed OCR batches..." if indices_to_process else "Processing OCR..."
        self.status_label.config(text=status_text)
        self.progress_bar.config(mode='determinate', value=0)
        self.cancellation_event.clear()
        threading.Thread(target=self.run_ocr_and_update_gui, args=(indices_to_process,), daemon=True).start()

    def cancel_ocr(self):
        self.cancellation_event.set()
        self.status_label.config(text="Operation cancelled by user.")
        logging.info("Operation cancelled by user.")
        self.progress_bar['value'] = 0
        self._set_controls_state(tk.NORMAL)

    def update_ocr_progress(self, message, percentage):
        self.status_label.config(text=message)
        self.progress_bar['value'] = percentage
        self.update_idletasks()

    def run_ocr_and_update_gui(self, indices_to_process=None):
        subtitles, message = self.app_context.run_ocr_pipeline(self.cancellation_event, self.update_ocr_progress, indices_to_process)
        self.progress_bar['value'] = 0
        if subtitles:
            self.ocr_completed = True
            self.status_label.config(text=f"OCR Complete! {len(self.app_context.subtitles)} subtitles.")
            logging.info(f"OCR Complete! Processed {len(self.app_context.subtitles)} subtitles.")
            if self.app_context.subtitles:
                self.navigate_to(self.app_context.current_index if self.app_context.current_index != -1 else 0)
        else:
            self.status_label.config(text=f"Error: {message}")
            if not self.cancellation_event.is_set():
                messagebox.showerror("OCR Error", message)
        self._set_controls_state(tk.NORMAL)

    def navigate_to(self, index):
        if not self.app_context.subtitles or not (0 <= index < len(self.app_context.subtitles)): return
        self.app_context.current_index = index
        sub = self.app_context.subtitles[index]
        try:
            img_path = os.path.join(self.app_context.image_folder, sub['image_file'])
            pil_img = Image.open(img_path)
            container = self.image_label.master
            container_w, container_h = container.winfo_width(), container.winfo_height()
            if container_w < 50 or container_h < 50: container_w, container_h = 800, 500
            scale = min(container_w / pil_img.width, container_h / pil_img.height)
            new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
            pil_img = pil_img.resize(new_size, Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            self.image_label.config(image=tk_img, text="")
            self.image_label.image = tk_img
        except Exception as e:
            self.image_label.config(text=f"Error loading image:\n{sub['image_file']}", image='')
        self.text_editor.delete('1.0', tk.END)
        self.text_editor.insert(tk.END, sub.get('text', ''))
        self.nav_label.config(text=f"Sub {index + 1} / {len(self.app_context.subtitles)}")
        self.time_label.config(text=f"{sub['start_srt']} --> {sub['end_srt']}")

    def sync_text_from_widget(self):
        if self.app_context.subtitles and 0 <= self.app_context.current_index < len(self.app_context.subtitles):
            self.app_context.subtitles[self.app_context.current_index]['text'] = self.text_editor.get('1.0', tk.END).strip()

    def prev_sub(self):
        self.sync_text_from_widget()
        if self.app_context.current_index > 0: self.navigate_to(self.app_context.current_index - 1)

    def next_sub(self):
        self.sync_text_from_widget()
        if self.app_context.current_index < len(self.app_context.subtitles) - 1: self.navigate_to(self.app_context.current_index + 1)

    def save_srt(self):
        self.sync_text_from_widget()
        srt_path = filedialog.asksaveasfilename(defaultextension=".srt", filetypes=[("Timing Files", "*.srt")], title="Save to .SRT file")
        if not srt_path: return
        try:
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, sub in enumerate(self.app_context.subtitles):
                    f.write(f"{i + 1}\n{sub['start_srt']} --> {sub['end_srt']}\n{sub.get('text', '').strip()}\n\n")
            messagebox.showinfo("Complete", f"SRT file saved successfully to:\n{srt_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save SRT file: {e}")

    def auto_load_models_on_startup(self):
        if self.api_key_var.get(): self.load_models()
        
    def load_models(self):
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("API Key Error", "Please enter an API Key.")
            return
        self.status_label.config(text="Loading model...")
        self.update_idletasks()
        threading.Thread(target=self._load_models_worker, args=(api_key,), daemon=True).start()
        
    def _load_models_worker(self, api_key):
        self.app_context.update_settings("api_key", api_key)
        models, error = self.app_context.get_available_models()
        if error:
            messagebox.showerror("Error", error)
            self.status_label.config(text="Error!")
            return
        self.model_combobox['values'] = models
        self.model_combobox.config(state="readonly")
        last_model = self.app_context.settings.get("last_model")
        if last_model in models: self.model_var.set(last_model)
        elif models: self.model_combobox.current(0)
        self.app_context.update_settings("last_model", self.model_var.get())
        self.status_label.config(text="Ready to select source.")
        self._set_controls_state(tk.NORMAL)

    def load_session(self):
        sessions = self.app_context.get_session_list()
        if not sessions:
            messagebox.showinfo("Info", "No saved sessions found.")
            return
        dialog = SessionSelectionDialog(self, sessions)
        self.wait_window(dialog)
        if dialog.selected_session:
            self.ocr_completed = False 
            session_path = os.path.join(TEMP_DIR_NAME, dialog.selected_session)
            self.status_label.config(text=f"Loading session: {dialog.selected_session}...")
            self.update_idletasks()
            subtitles, message = self.app_context.load_session_from_folder(session_path)
            if subtitles:
                if any("batch_" in f for f in os.listdir(os.path.join(session_path, "logs"))): self.ocr_completed = True
                self.status_label.config(text=message)
                self.navigate_to(0)
            else:
                messagebox.showerror("Error Loading Session", message)
            self._set_controls_state(tk.NORMAL)

    def on_model_change(self, event=None):
        selected_model = self.model_var.get()
        self.app_context.update_settings("last_model", selected_model)
        logging.info(f"Model changed to: {selected_model}")
        
    def select_source_file(self):
        self.app_context.cleanup_current_session_temp()
        self.ocr_completed = False
        source_path = filedialog.askopenfilename(title="Select Source: Video, XML, or HTML", filetypes=[("All Supported Files", "*.mkv *.mp4 *.ts *.xml *.html"), ("Video Files", "*.mkv *.mp4 *.ts"), ("Timing Files", "*.xml *.html")])
        if not source_path: return
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        ext = os.path.splitext(source_path)[1].lower()
        if ext in ['.mkv', '.mp4', '.ts']:
            threading.Thread(target=self.handle_video_file, args=(source_path,), daemon=True).start()
        elif ext in ['.xml', '.html']:
            threading.Thread(target=self.handle_timing_file, args=(source_path,), daemon=True).start()
        else:
            messagebox.showerror("Error", "Unsupported file format.")
            self._set_controls_state(tk.NORMAL)
    
    def select_hardsub_video(self):
        self.app_context.cleanup_current_session_temp()
        self.ocr_completed = False
        source_path = filedialog.askopenfilename(
            title="Select Video for Hardsub OCR",
            filetypes=[("Video Files", "*.mkv *.mp4 *.ts")]
        )
        if not source_path: return
            
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        
        quality_map = {
            'Fast (320px)': 320,
            'Balanced (480px)': 480,
            'Accurate (640px)': 640
        }
        options = {
            "scan_top": self.hardsub_scan_top_var.get(),
            "scan_bottom": self.hardsub_scan_bottom_var.get(),
            "scan_area_height": self.hardsub_scan_area_height_var.get(),
            "use_gpu": self.hardsub_use_gpu_var.get(),
            "confidence": self.hardsub_confidence_var.get(),
            "quality": quality_map.get(self.hardsub_quality_var.get(), 320)
        }
        threading.Thread(target=self.handle_hardsub_video, args=(source_path, options), daemon=True).start()
    
    def handle_hardsub_video(self, video_path, options):
        self.status_label.config(text="Analyzing video for hardsubs...")
        self.progress_bar.config(mode='determinate', value=0)
        subtitles, error = self.app_context.process_hardsub_video(video_path, options, self.update_ocr_progress, self.cancellation_event)
        self.progress_bar['value'] = 0
        if error:
            messagebox.showerror("Hardsub Error", error)
            self.status_label.config(text="Hardsub analysis failed.")
        else:
            status_message = f"Found {len(subtitles)} potential subtitles. Ready for OCR."
            self.status_label.config(text=status_message)
            logging.info(status_message)
            if subtitles: self.navigate_to(0)
        self._set_controls_state(tk.NORMAL)

    def handle_video_file(self, video_path):
        self.status_label.config(text=f"Scanning: {os.path.basename(video_path)}...")
        streams, error = self.app_context.inspect_video_subtitles(video_path)
        if error or not streams:
            messagebox.showerror("Error", error or "No image subtitle streams (PGS, VobSub) found in this video.")
            self.status_label.config(text="Video scan failed.")
            self._set_controls_state(tk.NORMAL)
            return
        dialog = SubtitleSelectionDialog(self, streams)
        self.wait_window(dialog)
        if dialog.selected_stream_index is not None:
            stream_index = streams[dialog.selected_stream_index]['index']
            self.status_label.config(text="Extracting subtitles...")
            self.progress_bar.config(mode='determinate', value=0)
            _, _, error = self.app_context.extract_subtitles_from_video(video_path, stream_index, self.update_extraction_progress, self.cancellation_event)
            self.progress_bar['value'] = 0
            if error:
                if error != "Extraction cancelled by user.": messagebox.showerror("Error", error)
                self.status_label.config(text="Subtitle extraction failed.")
            else:
                self.status_label.config(text=f"Extraction complete! {len(self.app_context.subtitles)} subtitles. Ready for OCR.")
                if self.app_context.subtitles: self.navigate_to(0)
        else:
            self.status_label.config(text="Subtitle stream selection cancelled.")
        self._set_controls_state(tk.NORMAL)
            
    def handle_timing_file(self, timing_path):
        self.status_label.config(text="Processing timing file and images...")
        subtitles, error = self.app_context.load_timing_file(timing_path)
        if error:
            messagebox.showerror("Error", error)
            self.status_label.config(text="Timing file processing failed.")
        else:
            self.status_label.config(text=f"Loaded {len(subtitles)} subtitles! Ready for OCR.")
            if subtitles: self.navigate_to(0)
        self._set_controls_state(tk.NORMAL)
        
    def update_extraction_progress(self, percentage):
        self.progress_bar['value'] = percentage
        self.update_idletasks()
        
    def _set_controls_state(self, state, ocr_running=False, extraction_running=False):
        is_disabled = state == tk.DISABLED or ocr_running or extraction_running
        effective_state = tk.DISABLED if is_disabled else tk.NORMAL
        
        for widget_name in ['btn_select_source', 'btn_load_session', 'btn_select_hardsub_video', 'load_models_button']:
            if hasattr(self, widget_name):
                widget = getattr(self, widget_name)
                if widget: widget.config(state=effective_state)

        self.btn_cancel_ocr.config(state=tk.NORMAL if ocr_running or extraction_running else tk.DISABLED)
        subtitles_loaded = bool(self.app_context.subtitles) and not is_disabled
        self.btn_start_ocr.config(state=tk.NORMAL if subtitles_loaded else tk.DISABLED)
        has_failed_batches = bool(self.app_context.settings.get('last_failed_batches'))
        self.btn_retry_failed.config(state=tk.NORMAL if subtitles_loaded and has_failed_batches else tk.DISABLED)
        nav_state = tk.NORMAL if subtitles_loaded else tk.DISABLED
        for widget in [self.btn_prev, self.btn_next]: widget.config(state=nav_state)
        save_state = tk.NORMAL if self.ocr_completed and not is_disabled else tk.DISABLED
        self.btn_save.config(state=save_state)
