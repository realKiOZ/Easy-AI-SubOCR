# main.py

import logging
from src.gui import SubtitlePreviewer

if __name__ == "__main__":
    # Cấu hình logging cơ bản để ghi ra file và console
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[
                            logging.FileHandler("app.log", encoding='utf-8'),
                            logging.StreamHandler()
                        ])
    
    logging.info("Khởi động ứng dụng.")
    app = SubtitlePreviewer()
    app.mainloop()
    logging.info("Ứng dụng đã đóng.")
