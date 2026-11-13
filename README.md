# BlackCanvasAI

An AI-powered art assistant and creative-business workspace for generating artwork, shaping collections, planning content, and running the business behind the canvas.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Schedule posts through Buffer

Connect your social accounts in [Buffer](https://publish.buffer.com/), then create a personal API key in Buffer under **Settings → API**. Set the key in the environment of your local Black Canvas AI server before starting it. In PowerShell:

```powershell
$env:BUFFER_API_KEY = "<your Buffer API key>"
python -m uvicorn app:app --reload
```

In **Marketing**, approve a week and open **Schedule with Buffer**. Choose the accounts, times, and public HTTPS media links for the posts you want to schedule. Facebook and Pinterest use images, while Instagram Reels and TikTok use videos. Select a board for Pinterest. Buffer needs direct media URLs that it can open without a sign-in.

The key stays on the server. Keep this workspace on loopback or behind authenticated access. If a submission can't be confirmed, check the Buffer queue for that account and time before creating another copy. Manage any changes to submitted posts in Buffer.

## Verify changes

```powershell
python -m unittest discover -v
python -m py_compile app.py storage.py
```

Pull requests and updates to `main` also run these Python checks plus JavaScript syntax validation automatically in GitHub Actions.
