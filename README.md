# BlackCanvasAI

An AI-powered art assistant and creative-business workspace for generating artwork, shaping collections, planning content, and running the business behind the canvas.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Verify changes

```powershell
python -m unittest discover -v
python -m py_compile app.py storage.py
```

Pull requests and updates to `main` also run these Python checks plus JavaScript syntax validation automatically in GitHub Actions.
