# BlackCanvasAI

An AI-powered art assistant and creative-business workspace for generating artwork, shaping collections, planning content, and running the business behind the canvas.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Art Think Tank

Open **Home → Art Think Tank → Physical Art**, select materials and a working
surface, then enter a direction and choose a collection. Create three physical-art
plans using the existing local prompt engine and saved Style Bible rules. Remix
keeps the generated brief and rotates through six composition variations. This
version does not call an external AI service or require an API key.

**Save to Prompt Library** stores the complete plan and optional image reference
prompt through the existing prompt API. Saved ideas use the same library, search,
editing, duplicate protection, and backups as other prompts. Ideas stay unsaved
until you choose Save; remixing or leaving the page replaces unsaved results.

## Verify changes

```powershell
python -m unittest discover -v
python -m py_compile app.py storage.py think_tank.py
```

Pull requests and updates to `main` also run these Python checks plus JavaScript syntax validation automatically in GitHub Actions.
