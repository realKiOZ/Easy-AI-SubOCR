# src/gui.py

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, font
from tkextrafont import Font
import threading
from PIL import Image, ImageTk
import logging
import shutil

from src.app_context import AppContext
from src.ui_components import SubtitleSelectionDialog, SessionSelectionDialog
from src.utils import check_tools_availability
from src.settings import TEMP_DIR_NAME
from src.localization import EN_TRANSLATIONS

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
        self.title(EN_TRANSLATIONS["app_title"])
        self.geometry("1100x900")
        self.minsize(1100, 900)
        self._center_window(1100, 900)
        
        self.app_context = AppContext()
        self._init_vars()
        self._create_menu()
        self._create_widgets()
        self._setup_logging()
        
        self.after(100, self.auto_load_models_on_startup)
        self.after(200, self.check_required_tools)
        
        try:
            self.font = Font(file="assets/fonts/NotoSans-Regular.ttf", family="Noto Sans")
        except Exception as e:
            logging.error(f"Failed to load font: {e}")
            messagebox.showerror("Font Error", f"Could not load the Noto Sans font. Please make sure the font file exists at assets/fonts/NotoSans-Regular.ttf.\n\n{e}")


    def _init_vars(self):
        self.api_key_var = tk.StringVar(value=self.app_context.api_key)
        self.model_var = tk.StringVar(value=self.app_context.model_name)
        self.batch_size_var = tk.IntVar(value=self.app_context.batch_size)
        config = self.app_context.generation_config
        self.temp_var = tk.DoubleVar(value=config.get("temperature", 0.5))
        self.topp_var = tk.DoubleVar(value=config.get("top_p", 1.0))
        self.topk_var = tk.IntVar(value=config.get("top_k", 40))
        self.temp_display_var = tk.StringVar(value=f"{self.temp_var.get():.2f}")
        self.topp_display_var = tk.StringVar(value=f"{self.topp_var.get():.2f}")
        self.ocr_lang_var = tk.StringVar(value=self.app_context.ocr_language)
        self.cancellation_event = threading.Event()
        self.ocr_completed = False

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=EN_TRANSLATIONS["menu_tools"], menu=tools_menu)
        tools_menu.add_command(label=EN_TRANSLATIONS["menu_manage_cache"], command=self.manage_cache)
        
    def _create_widgets(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left_frame = self._create_left_panel()
        left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        right_frame = self._create_right_panel()
        right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    def _create_left_panel(self):
        left_container = ttk.Frame(self)
        left_container.grid_rowconfigure(0, weight=1)
        left_container.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(left_container, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        content_frame = ttk.Frame(canvas, padding=10)
        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        content_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        row_idx = 0
        api_frame = ttk.LabelFrame(content_frame, text=EN_TRANSLATIONS["api_config_frame_text"], padding=10)
        api_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 10)); row_idx += 1
        api_frame.columnconfigure(1, weight=1)
        ttk.Label(api_frame, text=EN_TRANSLATIONS["google_api_key_label"]).grid(row=0, column=0, sticky="w", pady=2)
        self.api_key_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=0, column=1, columnspan=2, sticky="ew")
        self.load_models_button = ttk.Button(api_frame, text=EN_TRANSLATIONS["load_update_model_button"], command=self.load_models)
        self.load_models_button.grid(row=1, column=1, sticky="e", pady=(5,0))
        ttk.Label(api_frame, text=EN_TRANSLATIONS["model_label"]).grid(row=2, column=0, sticky="w", pady=2)
        self.model_combobox = ttk.Combobox(api_frame, textvariable=self.model_var, state="disabled")
        self.model_combobox.grid(row=2, column=1, columnspan=2, sticky="ew")
        self.model_combobox.bind("<<ComboboxSelected>>", self.on_model_change)

        control_frame = ttk.LabelFrame(content_frame, text=EN_TRANSLATIONS["process_frame_text"], padding=10)
        control_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 10)); row_idx += 1
        self.btn_select_source = ttk.Button(control_frame, text=EN_TRANSLATIONS["select_source_button"], command=self.select_source_file, state=tk.DISABLED)
        self.btn_select_source.pack(fill=tk.X, pady=2)
        self.btn_load_session = ttk.Button(control_frame, text=EN_TRANSLATIONS["load_session_button"], command=self.load_session, state=tk.DISABLED)
        self.btn_load_session.pack(fill=tk.X, pady=2)
        self.btn_start_ocr = ttk.Button(control_frame, text=EN_TRANSLATIONS["start_ocr_button"], command=self.start_ocr_thread, state=tk.DISABLED)
        self.btn_start_ocr.pack(fill=tk.X, pady=2)
        self.btn_cancel_ocr = ttk.Button(control_frame, text=EN_TRANSLATIONS["cancel_button"], command=self.cancel_ocr, state=tk.DISABLED)
        self.btn_cancel_ocr.pack(fill=tk.X, pady=2)
        self.btn_retry_failed = ttk.Button(control_frame, text=EN_TRANSLATIONS["retry_failed_batches_button"], command=self.retry_failed_batches, state=tk.DISABLED)
        self.btn_retry_failed.pack(fill=tk.X, pady=2)
        
        status_frame = ttk.Frame(control_frame, height=40)
        status_frame.pack(fill=tk.X, pady=5)
        status_frame.pack_propagate(False)
        self.status_label = ttk.Label(status_frame, text=EN_TRANSLATIONS["status_label_initial"], wraplength=300, justify=tk.LEFT)
        self.status_label.pack(fill=tk.BOTH, expand=True)

        self.progress_bar = ttk.Progressbar(control_frame, mode='indeterminate')
        self.progress_bar.pack(fill=tk.X)

        adv_frame = ttk.LabelFrame(content_frame, text=EN_TRANSLATIONS["advanced_settings_frame_text"], padding=10)
        adv_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 10)); row_idx += 1
        adv_frame.columnconfigure(1, weight=1)
        ttk.Label(adv_frame, text=EN_TRANSLATIONS["batch_size_label"]).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Spinbox(adv_frame, from_=1, to=500, textvariable=self.batch_size_var, command=self.save_advanced_settings, wrap=True, width=5).grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=(5,0))
        ttk.Label(adv_frame, text=EN_TRANSLATIONS["temperature_label"]).grid(row=1, column=0, sticky="w")
        ttk.Scale(adv_frame, from_=0.0, to=1.0, variable=self.temp_var, command=self.on_scale_change).grid(row=1, column=1, sticky="ew", padx=5)
        ttk.Label(adv_frame, textvariable=self.temp_display_var, width=4).grid(row=1, column=2)
        ttk.Label(adv_frame, text=EN_TRANSLATIONS["top_p_label"]).grid(row=2, column=0, sticky="w")
        ttk.Scale(adv_frame, from_=0.0, to=1.0, variable=self.topp_var, command=self.on_scale_change).grid(row=2, column=1, sticky="ew", padx=5)
        ttk.Label(adv_frame, textvariable=self.topp_display_var, width=4).grid(row=2, column=2)
        ttk.Label(adv_frame, text=EN_TRANSLATIONS["top_k_label"]).grid(row=3, column=0, sticky="w", pady=(5,0))
        ttk.Spinbox(adv_frame, from_=1, to=100, textvariable=self.topk_var, command=self.save_advanced_settings, wrap=True, width=5).grid(row=3, column=1, columnspan=2, sticky="ew", padx=5, pady=(5,0))
        ttk.Label(adv_frame, text=EN_TRANSLATIONS["ocr_language_label"]).grid(row=4, column=0, sticky="w", pady=(5,0))
        self.ocr_lang_combobox = ttk.Combobox(adv_frame, textvariable=self.ocr_lang_var)
        self.ocr_lang_combobox['values'] = ['Auto', 'Vietnamese', 'English', 'Japanese', 'Chinese', 'Korean', 'French', 'German', 'Spanish', 'Italian', 'Russian', 'Portuguese', 'Dutch', 'Polish', 'Turkish', 'Arabic', 'Hindi', 'Thai', 'Indonesian', 'Malay', 'Filipino']
        self.ocr_lang_combobox.grid(row=4, column=1, columnspan=2, sticky="ew", padx=5, pady=(5,0))
        self.ocr_lang_combobox.bind("<<ComboboxSelected>>", self.save_advanced_settings)
        self.ocr_lang_combobox.bind("<FocusOut>", self.save_advanced_settings)

        nav_frame = ttk.LabelFrame(content_frame, text=EN_TRANSLATIONS["navigation_save_frame_text"], padding=10)
        nav_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 10)); row_idx += 1
        nav_frame.columnconfigure(0, weight=1)
        self.btn_prev = ttk.Button(nav_frame, text=EN_TRANSLATIONS["prev_button"], command=self.prev_sub, state=tk.DISABLED)
        self.btn_prev.grid(row=0, column=0, sticky="ew", pady=2)
        self.nav_label = ttk.Label(nav_frame, text=EN_TRANSLATIONS["nav_label_initial"], anchor="center")
        self.nav_label.grid(row=1, column=0, sticky="ew", pady=5)
        self.time_label = ttk.Label(nav_frame, text="00:00:00,000 --> 00:00:00,000", anchor="center")
        self.time_label.grid(row=2, column=0, sticky="ew", pady=5)
        self.btn_next = ttk.Button(nav_frame, text=EN_TRANSLATIONS["next_button"], command=self.next_sub, state=tk.DISABLED)
        self.btn_next.grid(row=3, column=0, sticky="ew", pady=2)
        self.btn_save = ttk.Button(nav_frame, text=EN_TRANSLATIONS["save_srt_button"], command=self.save_srt, state=tk.DISABLED)
        self.btn_save.grid(row=4, column=0, sticky="ew", pady=(5, 2))
        
        return left_container

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

        self.image_label = ttk.Label(image_container, text=EN_TRANSLATIONS["image_label_initial"], anchor="center", background="gray")
        self.image_label.grid(row=0, column=0, sticky="nsew")
        
        self.text_editor = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, font=self.text_font, height=4)
        self.text_editor.grid(row=1, column=0, sticky="nsew", pady=(5, 0))

        log_frame = ttk.LabelFrame(right_frame, text=EN_TRANSLATIONS["log_frame_text"], padding=5)
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
            msg = EN_TRANSLATIONS["warning_missing_tools_message"].format(tools="\n".join(missing))
            messagebox.showwarning(EN_TRANSLATIONS["warning_missing_tools_title"], msg)

    def manage_cache(self):
        messagebox.showinfo(EN_TRANSLATIONS["info_complete_title"], EN_TRANSLATIONS["info_manage_cache_future"])

    def retry_failed_batches(self):
        messagebox.showinfo(EN_TRANSLATIONS["info_complete_title"], EN_TRANSLATIONS["info_retry_failed_future"])

    def on_scale_change(self, event=None):
        self.temp_display_var.set(f"{self.temp_var.get():.2f}")
        self.topp_display_var.set(f"{self.topp_var.get():.2f}")
        self.save_advanced_settings()

    def save_advanced_settings(self, event=None):
        self.app_context.update_settings("batch_size", self.batch_size_var.get())
        self.app_context.update_settings("ocr_language", self.ocr_lang_var.get().strip())
        generation_config = {"temperature": self.temp_var.get(), "top_p": self.topp_var.get(), "top_k": self.topk_var.get()}
        self.app_context.update_settings("generation_config", generation_config)
        logging.info(EN_TRANSLATIONS["info_advanced_settings_saved"])

    def start_ocr_thread(self):
        if not all([self.app_context.api_key, self.app_context.model_name, self.app_context.timing_file_path, self.app_context.image_folder]):
            messagebox.showwarning(EN_TRANSLATIONS["warning_missing_info"], EN_TRANSLATIONS["warning_missing_info"])
            return
        self._set_controls_state(tk.DISABLED)
        self.status_label.config(text=EN_TRANSLATIONS["status_processing_ocr"])
        self.progress_bar.start(10)
        self.cancellation_event.clear() # Reset the event for a new OCR run
        threading.Thread(target=self.run_ocr_and_update_gui, daemon=True).start()

    def cancel_ocr(self):
        self.cancellation_event.set() # Signal cancellation
        self.status_label.config(text=EN_TRANSLATIONS["status_ocr_cancelled"])
        logging.info(EN_TRANSLATIONS["status_ocr_cancelled"])
        self.progress_bar.stop()
        self._set_controls_state(tk.NORMAL, ocr_running=False, extraction_running=False)

    def update_ocr_progress(self, message):
        logging.info(message)

    def run_ocr_and_update_gui(self):
        subtitles, message = self.app_context.run_ocr_pipeline(self.cancellation_event, self.update_ocr_progress)
        self.progress_bar.stop()
        if subtitles:
            self.ocr_completed = True
            self.status_label.config(text=EN_TRANSLATIONS["status_ocr_complete"].format(count=len(self.app_context.subtitles)))
            logging.info(EN_TRANSLATIONS["log_ocr_complete"].format(count=len(self.app_context.subtitles)))
            if self.app_context.subtitles:
                self.navigate_to(0)
        else:
            self.status_label.config(text=EN_TRANSLATIONS["status_error"].format(message=message))
            logging.error(EN_TRANSLATIONS["log_ocr_error"].format(message=message))
            if not self.cancellation_event.is_set(): # Only show error if not cancelled by user
                messagebox.showerror(EN_TRANSLATIONS["error_ocr_title"], message)
        self._set_controls_state(tk.NORMAL, ocr_running=False)

    def navigate_to(self, index):
        if not self.app_context.subtitles or not (0 <= index < len(self.app_context.subtitles)): return
        logging.info(EN_TRANSLATIONS["log_navigating_to_subtitle"].format(index=index))
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
            self.image_label.config(text=EN_TRANSLATIONS["image_load_error_label"].format(file=sub['image_file']), image='')
            logging.error(EN_TRANSLATIONS["log_image_load_error"].format(file=sub['image_file'], error=e))
        self.text_editor.delete('1.0', tk.END)
        self.text_editor.insert(tk.END, sub.get('text', ''))
        self.nav_label.config(text=f"Sub {index + 1} / {len(self.app_context.subtitles)}")
        self.time_label.config(text=f"{sub['start_srt']} --> {sub['end_srt']}")

    def sync_text_from_widget(self):
        if 0 <= self.app_context.current_index < len(self.app_context.subtitles):
            self.app_context.subtitles[self.app_context.current_index]['text'] = self.text_editor.get('1.0', tk.END).strip()

    def prev_sub(self):
        self.sync_text_from_widget()
        if self.app_context.current_index > 0: self.navigate_to(self.app_context.current_index - 1)

    def next_sub(self):
        self.sync_text_from_widget()
        if self.app_context.current_index < len(self.app_context.subtitles) - 1: self.navigate_to(self.app_context.current_index + 1)
            
    def save_srt(self):
        self.sync_text_from_widget()
        srt_path = filedialog.asksaveasfilename(defaultextension=".srt", filetypes=[(EN_TRANSLATIONS["file_type_timing"], "*.srt")], title=EN_TRANSLATIONS["save_srt_button"])
        if not srt_path:
            logging.warning(EN_TRANSLATIONS["warning_srt_save_cancelled"])
            return
        try:
            logging.info(EN_TRANSLATIONS["log_saving_srt_to"].format(path=srt_path))
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, sub in enumerate(self.app_context.subtitles):
                    f.write(f"{i + 1}\n{sub['start_srt']} --> {sub['end_srt']}\n{sub.get('text', '').strip()}\n\n")
            logging.info(EN_TRANSLATIONS["log_srt_save_success"])
            messagebox.showinfo(EN_TRANSLATIONS["info_complete_title"], EN_TRANSLATIONS["info_srt_save_success"].format(path=srt_path))
        except Exception as e:
            logging.error(EN_TRANSLATIONS["log_srt_save_error"].format(error=e))
            messagebox.showerror(EN_TRANSLATIONS["error_title"], EN_TRANSLATIONS["error_srt_save_failed"].format(error=e))

    def auto_load_models_on_startup(self):
        if self.api_key_var.get(): self.load_models()
        
    def load_models(self):
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror(EN_TRANSLATIONS["error_api_key_title"], EN_TRANSLATIONS["error_api_key_missing"])
            return
        self.status_label.config(text=EN_TRANSLATIONS["status_loading_model"])
        self.update_idletasks()
        threading.Thread(target=self._load_models_worker, args=(api_key,), daemon=True).start()
        
    def _load_models_worker(self, api_key):
        self.app_context.update_settings("api_key", api_key)
        models, error = self.app_context.get_available_models()
        if error:
            messagebox.showerror(EN_TRANSLATIONS["error_title"], error)
            self.status_label.config(text=EN_TRANSLATIONS["status_error_generic"])
            return
        self.model_combobox['values'] = models
        self.model_combobox.config(state="readonly")
        last_model = self.app_context.settings.get("last_model")
        if last_model in models: self.model_var.set(last_model)
        elif models: self.model_combobox.current(0)
        self.app_context.update_settings("last_model", self.model_var.get())
        self.status_label.config(text=EN_TRANSLATIONS["status_ready_to_select_source"])
        self._set_controls_state(tk.NORMAL, ocr_running=False)

    def load_session(self):
        sessions = self.app_context.get_session_list()
        if not sessions:
            messagebox.showinfo(EN_TRANSLATIONS["info_complete_title"], EN_TRANSLATIONS["info_no_saved_sessions"])
            return
        dialog = SessionSelectionDialog(self, sessions)
        self.wait_window(dialog)
        if dialog.selected_session:
            self.ocr_completed = False # Reset on new session load
            session_path = os.path.join(TEMP_DIR_NAME, dialog.selected_session)
            self.status_label.config(text=EN_TRANSLATIONS["status_loading_session"].format(session=dialog.selected_session))
            self.update_idletasks()
            subtitles, message = self.app_context.load_session_from_folder(session_path)
            if subtitles:
                # Check if the loaded session had OCR results
                if "batches" in message or "log" in message:
                    self.ocr_completed = True
                self.status_label.config(text=message)
                self.navigate_to(0)
            else:
                messagebox.showerror(EN_TRANSLATIONS["error_load_session_title"], message)
                self.status_label.config(text=EN_TRANSLATIONS["status_session_load_failed"])
            self._set_controls_state(tk.NORMAL, ocr_running=False)

    def on_model_change(self, event=None):
        selected_model = self.model_var.get()
        self.app_context.update_settings("last_model", selected_model)
        logging.info(EN_TRANSLATIONS["log_model_changed"].format(model=selected_model))
        
    def select_source_file(self):
        self.app_context.cleanup_current_session_temp()
        self.ocr_completed = False # Reset on new file selection
        source_path = filedialog.askopenfilename(
            title=EN_TRANSLATIONS["file_dialog_select_source_title"],
            filetypes=[
                (EN_TRANSLATIONS["file_type_all_supported"], "*.mkv *.mp4 *.ts *.xml *.html"),
                (EN_TRANSLATIONS["file_type_video"], "*.mkv *.mp4 *.ts"),
                (EN_TRANSLATIONS["file_type_timing"], "*.xml *.html")
            ]
        )
        if not source_path: return
        self.cancellation_event.clear()
        self._set_controls_state(tk.DISABLED, extraction_running=True)
        ext = os.path.splitext(source_path)[1].lower()
        if ext in ['.mkv', '.mp4', '.ts']:
            threading.Thread(target=self.handle_video_file, args=(source_path,), daemon=True).start()
        elif ext in ['.xml', '.html']:
            threading.Thread(target=self.handle_timing_file, args=(source_path,), daemon=True).start()
        else:
            messagebox.showerror(EN_TRANSLATIONS["error_title"], EN_TRANSLATIONS["error_unsupported_file_format"])
            self._set_controls_state(tk.NORMAL, ocr_running=False)
        
    def update_extraction_progress(self, percentage):
        self.progress_bar['value'] = percentage
        self.update_idletasks()

    def handle_video_file(self, video_path):
        self.status_label.config(text=EN_TRANSLATIONS["status_scanning_video"].format(file=os.path.basename(video_path)))
        streams, error = self.app_context.inspect_video_subtitles(video_path)
        if error:
            messagebox.showerror(EN_TRANSLATIONS["error_title"], error)
            self.status_label.config(text=EN_TRANSLATIONS["status_video_scan_failed"])
            self._set_controls_state(tk.NORMAL, ocr_running=False)
            return
        dialog = SubtitleSelectionDialog(self, streams)
        self.wait_window(dialog)
        if dialog.selected_stream_index is not None:
            stream_index = streams[dialog.selected_stream_index]['index']
            self.status_label.config(text=EN_TRANSLATIONS["status_extracting_subtitles"])
            
            self.progress_bar.config(mode='determinate')
            self.progress_bar['value'] = 0

            _, _, error = self.app_context.extract_subtitles_from_video(video_path, stream_index, self.update_extraction_progress, self.cancellation_event)
            
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar.stop()

            if error:
                if error == EN_TRANSLATIONS["error_extraction_cancelled_by_user"]:
                    self.status_label.config(text=EN_TRANSLATIONS["status_ocr_cancelled"])
                else:
                    messagebox.showerror(EN_TRANSLATIONS["error_title"], error)
                    self.status_label.config(text=EN_TRANSLATIONS["status_extraction_complete"])
            else:
                sub_count = len(self.app_context.subtitles)
                status_message = EN_TRANSLATIONS["status_extraction_complete"].format(count=sub_count)
                self.status_label.config(text=status_message)
                logging.info(EN_TRANSLATIONS["log_extraction_complete"].format(count=sub_count))
        else:
            self.status_label.config(text=EN_TRANSLATIONS["status_subtitle_stream_selection_cancelled"])
        self._set_controls_state(tk.NORMAL, ocr_running=False, extraction_running=False)
            
    def handle_timing_file(self, timing_path):
        self.status_label.config(text=EN_TRANSLATIONS["status_processing_timing_images"])
        subtitles, error = self.app_context.load_timing_file(timing_path)
        if error:
            messagebox.showerror(EN_TRANSLATIONS["error_title"], error)
            self.status_label.config(text=EN_TRANSLATIONS["status_timing_file_processing_failed"])
        else:
            self.status_label.config(text=EN_TRANSLATIONS["status_timing_file_loaded"].format(count=len(subtitles)))
        self._set_controls_state(tk.NORMAL, ocr_running=False, extraction_running=False)
        
    def _set_controls_state(self, state, ocr_running=True, extraction_running=False):
        # General controls
        self.btn_select_source.config(state=state)
        self.btn_load_session.config(state=state)
        self.btn_cancel_ocr.config(state=tk.NORMAL if ocr_running or extraction_running else tk.DISABLED)

        # State based on whether subtitles are loaded (but not necessarily OCR'd)
        subtitles_loaded = self.app_context.subtitles and not ocr_running
        self.btn_start_ocr.config(state=tk.NORMAL if subtitles_loaded else tk.DISABLED)
        self.btn_retry_failed.config(state=tk.NORMAL if self.app_context.settings.get('last_failed_batches') and subtitles_loaded else tk.DISABLED)
        
        # Navigation controls are enabled when subtitles are loaded
        nav_state = tk.NORMAL if subtitles_loaded else tk.DISABLED
        self.btn_prev.config(state=nav_state)
        self.btn_next.config(state=nav_state)

        # Save button is only enabled after OCR is successfully completed
        save_state = tk.NORMAL if self.ocr_completed and not ocr_running else tk.DISABLED
        self.btn_save.config(state=save_state)
