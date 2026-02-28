import os
import webbrowser
import threading
import time
import sys

BASE_DIR = os.path.dirname(sys.executable)

def start_server():
    os.chdir(BASE_DIR)
    os.system(f'"{sys.executable}" manage.py runserver 127.0.0.1:8000')

threading.Thread(target=start_server).start()

time.sleep(6)

webbrowser.open("http://127.0.0.1:8000")
