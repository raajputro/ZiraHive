# Local AI

ZiraHive can use free AI models that run **on your own PC**. Nothing is sent to any company: the
models download once, then everything stays on your PC. It's optional; everything else works
without it.

| Feature | Where | Model |
|---|---|---|
| Search photos by what's in them ("beach at sunset", "লাল গাড়ি") | Photos, search box | CLIP ViT-B/32 |
| People: photos grouped by face, with names you give them | Photos > People | YuNet + SFace (OpenCV) |
| Subtitles for films that have none | Player > Make subtitles with AI (admins) | Whisper small |
| Ask your files ("When does my passport expire?") | Files > Ask | Qwen2.5 3B and BGE-M3 (Ollama) |

**Clean up** (Photos > Clean up: duplicates and blurry photos) needs no AI and always works.

## Turn it on

```powershell
docker compose --profile ai up -d --build
```

This starts two more containers: `ai` (pictures, faces, speech) and `ollama` (questions). ZiraHive
notices them by itself: **Settings > Server > Local AI** shows what's running and how far it has
got.

- **Downloads, once:** about 700 MB for pictures, faces and speech (into
  `ZIRAHIVE_DATA_PATH\cache\ai-models`, which offsite backup skips), and 2 to 3 GB for the question
  models (in the `ollama` volume). They download the first time each feature is used.
- **Your existing photos and documents** are looked at in the background, newest first, a batch each
  night. To start straight away, press **Catch up now** in Settings. The first time can take hours
  for a big library; new photos are done within a minute of uploading.
- **Memory:** about 2 GB for `ai` and 4 GB for `ollama` while busy. With 8 GB of RAM in the PC, pick
  a smaller question model (below).

To turn it off again: `docker compose --profile ai stop ai ollama`. Search, People and Ask then
say that the local AI isn't running; nothing else changes.

## Settings (`.env`)

| Setting | Default | What it does |
|---|---|---|
| `ZIRAHIVE_LLM_MODEL` | `qwen2.5:3b` | Answers questions. `qwen2.5:1.5b` for PCs with little memory, `qwen2.5:7b` or `llama3.1:8b` for better answers with a GPU |
| `ZIRAHIVE_EMBED_MODEL` | `bge-m3` | Finds the right passages; understands Bangla and English |
| `ZIRAHIVE_WHISPER_MODEL` | `small` | `base` is faster, `medium` is better at Bangla and Hindi but slow on a CPU |
| `ZIRAHIVE_AI_URL`, `ZIRAHIVE_OLLAMA_URL` | the containers | Point at another computer that runs them, if you like |

After changing the question models, run `docker compose --profile ai up -d`; they download on the
next question.

## NVIDIA graphics card

Uncomment the `deploy` blocks under `ai` and `ollama` in `docker-compose.yml`, and set
`ZIRAHIVE_AI_GPU=1` for `ai`. Subtitles are then about ten times faster, and questions are answered
in seconds.

## Good to know

- **Search** understands English best; Bangla searches are translated into English first when
  Ollama is running. The photos searched are your own, not other people's.
- **People** are found per account: nobody else sees your people. A person shows up once their
  face is in two photos. Wrong photo? Open the person, **Remove wrong photos**. The same person
  twice? **Same person as**. Faces too small to recognise (under 40 pixels) are skipped.
- **Subtitles** take about as long as the film on a CPU. They appear as "Bangla (AI)" or
  "English (AI)" in the subtitle menu, also on Chromecast and smart TVs. The language is detected
  from the speech.
- **Ask** reads only the documents of the person asking: PDFs, Word and text files, and scanned
  papers. It answers from them and shows where it found each fact; if they don't say, it tells you
  so instead of guessing.
