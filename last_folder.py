import os

LAST_PATH_FILE = '.last_folder.txt'

def get_last_folder():
    if os.path.exists(LAST_PATH_FILE):
        try:
            with open(LAST_PATH_FILE, 'r') as f:
                return f.read().strip()
        except Exception:
            pass
    return '.'

def save_last_folder(folder):
    try:
        with open(LAST_PATH_FILE, 'w') as f:
            f.write(folder)
    except Exception:
        pass

