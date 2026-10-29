# BlackCanvasAI

An AI-powered art assistant and creative-business workspace for generating artwork, shaping collections, planning content, and running the business behind the canvas.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Home

Home shows saved project, in-progress, completed, and creative kit counts. Resume
one of the three most recently saved unfinished projects with its checklist
progress and an available progress/finished photo. The project counts open the
matching status filter; Creative kits opens the optional kit panel in Think Tank.
Empty studios get starting links, and completed projects remain in Projects.

Newest prompts and artwork are grouped by library and link directly to their
saved records. The featured saved idea supports exact copying, with selection
and manual-copy fallbacks when clipboard access is unavailable. Version-testing
controls appear when there are migrated copies or outdated prompts to review.
Refresh studio pulls in other-device saves without clearing an unfinished Chat
question. Failed refreshes preserve the last loaded view and show its status;
an initial connection failure keeps counts unknown until a successful retry.
Dashboard data comes from one database read snapshot and does not save changes.

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

**Your saved creative kits** keeps reusable materials, surface, optional preset,
style, colors, mood, and exclusions in the studio database. Name and save the
preferences currently in the form, then review and apply a kit when you want to
use it. Applying preserves your current subject and existing idea cards; Undo
last apply restores the previous form preferences until you edit them manually.
Kits never apply automatically or store your subject or generated idea text.
They are available to connected devices using the same studio, including when
browser draft storage is blocked. Refresh kits to see other-device changes.
Update selected kit from form replaces its preferences explicitly; revision
checks prevent stale updates/removals. Removing a kit keeps ideas and projects.

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

**Print / download plan** opens a project sheet made from the fields currently
shown on your device, including unsaved edits. Choose whether to include notes,
the full source idea, and up to 12 linked photos (20 MB combined). Preview the copy,
print or save a PDF through your browser, or download HTML/text. HTML embeds the
selected images and works offline; text keeps the plan and photo captions. Making
a sheet does not save or replace project changes. If another device saved a newer
plan, the sheet identifies that it uses your device's older fields. Refresh photos
before reopening the sheet to include photos added from another device.

Backup format 9 includes creative kits, projects, and photo links. Kit restore
adds missing kits and preserves existing kits by ID or name. Google Drive restore remaps
source prompt IDs and artwork IDs and adds missing projects without overwriting
existing project progress or photo links. Photo links restore for newly added
projects; repeating an older restore preserves later unlinks. Older backups with
no projects or photo links remain supported. The JSON manifest references image
files; Google Drive folder backups include the actual images.

## Verify changes

```powershell
python -m unittest discover -v
python -m py_compile app.py storage.py think_tank.py projects.py project_sheets.py creative_kits.py
node --test test_think_tank_state.mjs
```

Pull requests and updates to `main` also run these Python checks plus JavaScript syntax validation automatically in GitHub Actions.
