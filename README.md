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

The default is **My own direction**. Users can describe any subject, visual
approach, colors, mood, things to avoid, and additional materials. No collection,
palette, subject identity, or mood is assigned when these are left unspecified.
AfroNova, Quiet Nova, and GraffitiX are optional presets. Think Tank reference
prompts use the chosen materials/surface and the user's brief, including for
landscapes, still life, and abstract work. Chat also defaults to user direction;
describing a calm or urban scene does not silently select a collection.

New prompt libraries start empty. Existing library content is preserved. Artwork
collections can be named freely and Image Studio filters reflect saved artwork.

**Save to Prompt Library** stores the complete plan and optional image reference
prompt through the existing prompt API. Saved ideas use the same library, search,
editing, duplicate protection, and backups as other prompts. **Remix this idea**
replaces only its card and keeps the other two ideas, including their save status.
The batch remix changes all three compositions, even after individual remixes.

**Develop this idea** lets you edit a card's direction, palette, mood, and studio
notes while keeping its composition, materials, surface, and collection. Apply
updates only that card; Save adds the revised plan as a new library entry, leaving
earlier saves intact. Individual and batch remixes keep each card's refinements.
Unfinished refinement edits are also remembered in the browser workspace.

Your unfinished direction and current ideas are restored when you return in the
same browser on the same device and address. This browser draft is not a Prompt
Library save or a cross-device backup. Save ideas you want to keep in the library.
Creating a new set replaces the current three ideas. Browser storage restrictions
are reported on the page; generation and library saving still work without it.

## Verify changes

```powershell
python -m unittest discover -v
python -m py_compile app.py storage.py think_tank.py
node --test test_think_tank_state.mjs
```

Pull requests and updates to `main` also run these Python checks plus JavaScript syntax validation automatically in GitHub Actions.
