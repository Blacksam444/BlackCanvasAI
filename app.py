from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

@app.get("/")
def home():
    return FileResponse(BASE_DIR / "templates" / "templates" / "dashboard.html")

@app.get("/dashboard")
def dashboard():
    return FileResponse(BASE_DIR / "templates" / "templates" / "dashboard.html")