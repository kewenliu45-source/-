import os
import pandas as pd
from app.config import UPLOAD_DIR


async def save_upload_file(file):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    content = await file.read()

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path


def read_excel(file_path):
    return pd.read_excel(file_path)