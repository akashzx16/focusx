"""Copy this file's contents into PythonAnywhere's WSGI configuration file.

Replace PROJECT_PATH with the path displayed in your PythonAnywhere Files tab,
then replace the placeholder secret with a long, private random value.
"""

import os
import sys

PROJECT_PATH = "/home/YOUR_USERNAME/focusx"

if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

os.environ["FOCUSX_SECRET_KEY"] = "REPLACE_WITH_A_LONG_RANDOM_SECRET"
os.environ["FOCUSX_DB_PATH"] = os.path.join(PROJECT_PATH, "focusx.db")

from app import app as application
