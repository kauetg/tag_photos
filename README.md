# Media tagger

Adds searchable keywords and a place to a large underwater photo and video archive, with a human reviewing what
the computer is unsure about. Photos get hierarchical XMP keywords that Lightroom and Bridge read; videos are
indexed so you can search them and send the right ones to Premiere.

**Safety first.** Scanning, tagging, indexing and exporting only *read* your files. The one command that writes is
`write`, and it is a simulation unless you confirm. It writes `.xmp` sidecar files next to the photos, never inside
RAW files, and **never touches a video**.

## How it works

```
scan  ->  tag  ->  triage  ->  review  ->  write            (photos)
scan  ->  video  ->  Library  ->  premiere                   (videos)
```

| Stage | What it does |
|---|---|
| `scan` | Lists the files and gives each a place, from the folder name first and the date as a fallback. |
| `tag` | Looks at each photo: which scene it is (underwater, drone, land) and what is in it. Generic CLIP for scene and groups, BioCLIP only for species inside a group it found. |
| `triage` | Photos the model is sure about are approved automatically; the uncertain ones wait for you. Runs at the end of `tag`. |
| `review` | The app. **Review tags** is where you fix a photo's place, scene and tags, including tags of your own. |
| `write` | Puts the approved tags and the place into the photos' XMP. Preview first; removes only what it wrote earlier. |
| `video` | Takes a frame every few seconds of each video, classifies them and remembers *when* things appear. |
| `premiere` | Exports the videos you pick as an XML for Premiere Pro, with a marker at each match. |

## Install

Needs Python 3.11 or newer (built and tested on 3.13) and Windows or macOS or Linux.

**1. Environment**

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
```

**2. PyTorch, chosen for the machine.** Install this before anything else.

- No NVIDIA graphics card (or just trying it out): `pip install torch torchvision`
- NVIDIA graphics card: open <https://pytorch.org/get-started/locally/>, pick *Pip* and the CUDA version it
  offers, and run the command it prints. It is much faster than the processor.

**3. The rest**

```bash
pip install -r requirements.txt
```

The model weights (about 1.2 GB: BioCLIP and a generic CLIP) download from Hugging Face the first time you run
`tag`, so that machine needs internet once. After that they are cached and it works offline. The
"unauthenticated requests" warning is harmless.

**4. Tools**

| Tool | For | Where to put it |
|---|---|---|
| **exiftool** (required) | reading previews and writing XMP | Download the Windows zip from <https://exiftool.org>, then put `exiftool(-k).exe` renamed to `exiftool.exe` and the `exiftool_files` folder in `tools/exiftool/`. |
| **ffmpeg + ffprobe** (for videos) | sampling frames from videos | `tools/ffmpeg/bin/ffmpeg.exe` and `ffprobe.exe` (a release "essentials" build is enough). |
| **Adobe DNG Converter** (for GoPro `.GPR`) | GPR has no preview; the converter makes a temporary DNG to read | Install it normally. It is found in `C:\Program Files\Adobe\Adobe DNG Converter`. |
| **VLC** (optional) | clicking a video card opens VLC at that moment | Install it normally. |

Anything can also be on the `PATH`, or pointed to in the next step.

**5. Settings for this machine**

Copy `config/config.local.example.toml` to `config/config.local.toml` (it is not committed) and set where the media
is:

```toml
media_root = "D:\\"
# exiftool = "C:\\path\\to\\exiftool.exe"
# ffmpeg = "C:\\path\\to\\ffmpeg.exe"
# vlc = "C:\\path\\to\\vlc.exe"
```

You can also pass `--media-root "path"` to any command instead.

**6. Your drives**

Every disk is a *drive* with a name ("Splash IV"). The index remembers which drive each file is on, so you can search
all of them and only plug a disk in to open, edit or tag its files. A disk is recognised by its serial number, never by
its letter.

```bash
python tagger.py drives import SHEET.tsv       # your old sheet: HD, Descrição, Letra, Tamanho, Localização ...
python tagger.py drives                        # list them: files indexed, plugged in or not
python tagger.py drives pair "Splash IV" --letter E:   # once, with the disk plugged in
python tagger.py drives scan "Splash IV"       # index it and make the previews
python tagger.py drives import-state "Splash IV"       # move an old data/state.json under a drive
```

The **Drives** page does the same: it lists the disks, notices a plugged-in disk it does not know, and scans in the
background. `tag`, `video`, `write` and `scan` take `--drive NAME`. Plug-in detection is only implemented on Windows.

**6. Check everything**

```bash
python tagger.py doctor
```

It prints the device (`cuda` on an NVIDIA machine, otherwise `cpu`), where each tool was found and how many
location rules are loaded. Fix anything that says `NOT FOUND` before going on.

## First run: a small folder

Try everything on one folder before pointing it at the whole archive. These stages are read-only, so they are
safe on the real drive; add `--limit 20` to any of them to stay small.

```bash
python tagger.py scan --folder "20260125 Dia 2 Siqui Mergulho Vibrations"
python tagger.py tag --limit 20          # first run downloads the models
python tagger.py video --limit 5
python tagger.py review                  # opens the app in the browser
```

`tag` and `video` print the time per file when they finish (for example "20 photos in 31 s (1.6 s each)"). Multiply
that by the size of the archive to know how long a full run takes; model loading is not counted, it only happens
once per command. On a graphics card it is much faster than on the processor.

For the first **write**, use a *copy* of a folder (copy it somewhere else and point `--media-root` at the copy).

## Everyday use

```bash
python tagger.py scan                    # new and changed files only; can be repeated
python tagger.py tag                     # only photos not tagged yet
python tagger.py video                   # only videos not indexed yet
python tagger.py review                  # the app
python tagger.py write                   # PREVIEW of what would change in the files
python tagger.py write --apply           # really write (or use the Write page in the app)
python tagger.py premiere "turtle"       # XML of the videos matching a word
```

Other useful ones: `triage --auto 0.8` (change how sure the model must be), `relocate` (re-apply
`locations.csv` after editing it), `export` (all suggestions as a CSV), `show FILE` (print the tags in a file),
`video --strips-only` (rebuild the hover previews). Every command takes `--dry-run`, `--folder` and `--limit`.

### The app

`python tagger.py review` opens five pages:

- **Library**: search photos and videos by word, scene, place, date and dive folder; grid or list; move the mouse
  over a video to browse it, click to play in VLC from that moment; build the list of videos for Premiere.
- **Review tags**: go through the photos the model was unsure about (arrows move between them without deciding).
  Fix the place and scene, untick wrong tags, add your own from the list, or create a new one.
- **Write**: preview and write the approved tags into the photos.
- **Vocabulary**: edit what the model looks for and the tags only you apply.
- **Locations**: edit which folder words and which dates mean which place.

## Lightroom: the order matters

Lightroom keeps its own copy of the metadata and does **not** notice changes made outside it. To avoid losing edits
for photos that are already in its catalog:

1. In Lightroom: select the photos, **Metadata → Save Metadata to File**.
2. Here: **Write** (the page or `write --apply`).
3. In Lightroom: select the same photos, **Metadata → Read Metadata from File**.

Lightroom reads sidecars for RAW files (ARW, GPR). For **JPG and DNG** it stores metadata inside the file and may
not read a sidecar, so by default those get sidecars too (the safest) and might not show up. If that happens, set
`embedded = [".jpg", ".jpeg", ".dng"]` in the `[write]` section of `config/config.toml` (or choose *Inside the file*
on the Write page). The file is then rewritten and exiftool keeps a copy named `*_original`.

## Premiere

Select videos in the Library (tick *Add to export list*), then download the XML and use **File → Import** in
Premiere. Whole files are the default, with a marker where each match falls, and the clips are grouped in bins by
category. Choose *Trimmed around moments* to cut each video around the matches instead. The XML only points at the
video files.

## Where things are

| Path | What |
|---|---|
| `config/vocabulary.csv` | everything the model looks for, plus your own tags (edit in the app) |
| `config/locations.csv`, `config/date_ranges.csv` | folder words and dates that mean a place (edit in the app) |
| `config/config.toml` | shared settings; `config.local.toml` holds this machine's paths and is not committed |
| `data/index.db` | SQLite: your drives and everything the tool knows about each file, including your review decisions |
| `data/thumbs/` | cached previews (safe to delete; `tagger thumbs --drive NAME` makes them again while the drive is plugged in) |
| `data/write_log.jsonl` | a line for every file written |
| `tools/` | exiftool and ffmpeg (not committed) |

File keys in the index are `<drive name>/<path on the drive>`, so you can copy `data/index.db` to another machine
(together with the `config/` files, which are in git) and search it without the disks.
Edits to `config/*.csv` made in the app leave a `.bak` copy of the previous version.

## Troubleshooting

- **`exiftool not found`**: see step 4; run `doctor` to check.
- **GPR files are skipped with a "VC-5" message**: install Adobe DNG Converter.
- **A DJI DNG will not write ("minor" maker notes error)**: set `ignore_minor_errors = true` in `config/config.toml`.
  Check one file first; exiftool refuses these writes for a reason.
- **The app shows old behaviour after you edit the code**: stop it (Ctrl+C) and start it again.
- **Folder names with accents on Windows**: put the path in quotes, and prefer `--media-root "..."` over typing it in
  a one-line `python -c`.
- **Nothing happens when you click a video**: set `vlc = "..."` in `config/config.local.toml`; without VLC the video
  opens in the default player, from the start.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Not built yet

Face recognition (photos only) and GPS-based place checks are planned, not implemented. Videos are only indexed
and searched, never written to.
