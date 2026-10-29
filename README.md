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

## Projects

Choose **Start project** on a Think Tank idea, or **Open as project** when viewing
a saved Prompt Library item. The idea is saved in the existing library first;
the project links to it instead of keeping a second prompt store. Repeating the
action opens the same project. Think Tank studio steps, materials, surface, and
notes become editable project fields; other prompts start with a blank checklist.

Use Projects to edit the plan, add or remove steps, track checklist progress, and
mark the project as planned, in progress, paused, or completed. **Save project**
stores progress on the app server for other connected devices. Unsaved drafts are
remembered in the current browser when storage is available. Revision checks
prevent a stale device from silently overwriting newer saves; older drafts can
be reviewed explicitly before replacement. Source ideas in Trash do not remove
the project or its checklist.

**Project photos** lets you upload images from your phone or computer, or link
images already in Image Studio. Label each as a reference, work in progress, or a
finished piece, then filter the project gallery by that label. Uploads are saved
once in the existing artwork catalog and linked to the project; adding a finished
photo leaves the project status up to you. Photo additions save immediately and
keep unsaved plan edits in place. **Refresh photos** brings in photos added from
another device without reloading your plan. Save project separately to keep plan edits.

Open a project photo in Image Studio to edit its title, collection, and notes, or
follow the link back to its project. **Unlink** removes only the project link and
keeps the catalog image. Removing an image from Image Studio removes all its
project links too; the catalog asks for confirmation when the image is linked.
JPEG, PNG, WebP, and GIF uploads up to 10 MB are supported.

Backup format 8 includes projects and photo links. Google Drive restore remaps
source prompt IDs and artwork IDs and adds missing projects without overwriting
existing project progress or photo links. Photo links restore for newly added
projects; repeating an older restore preserves later unlinks. Older backups with
no projects or photo links remain supported. The JSON manifest references image
files; Google Drive folder backups include the actual images.

## Verify changes

```powershell
python -m unittest discover -v
python -m py_compile app.py storage.py think_tank.py projects.py
node --test test_think_tank_state.mjs
```

Pull requests and updates to `main` also run these Python checks plus JavaScript syntax validation automatically in GitHub Actions.
