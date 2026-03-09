# Docker Usage Guide

Running `make_m4b` inside a container is useful for:
- Reproducible builds with a pinned `ffmpeg` version.
- Batch-processing audiobooks in CI or on a server without a GUI.
- Distributing the tool without requiring users to install ffmpeg locally.

---

## System Requirements

| Dependency | Version |
|---|---|
| ffmpeg | >= 6.0 |
| ffprobe | >= 6.0 (bundled with ffmpeg) |
| Python | >= 3.11 |

---

## Sample Dockerfile

```dockerfile
FROM python:3.12-slim

# Install ffmpeg (includes ffprobe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY m4bmaker/ m4bmaker/
COPY make_m4b.py .

ENTRYPOINT ["python", "make_m4b.py"]
```

Build the image:

```bash
docker build -t m4bmaker .
```

---

## Running the Container

Mount the directory containing your audio files at `/books` inside the container.
The output `.m4b` file is written into the same mounted directory.

### Interactive (prompts for missing metadata)

```bash
docker run --rm -it \
  -v /path/to/audiobook/Dune:/books \
  m4bmaker /books
```

### Fully non-interactive

```bash
docker run --rm \
  -v /path/to/audiobook/Dune:/books \
  m4bmaker /books \
    --title "Dune" \
    --author "Frank Herbert" \
    --narrator "Scott Brick" \
    --no-prompt
```

### Custom output path

Mount a separate output directory to keep the source files clean:

```bash
docker run --rm \
  -v /path/to/audiobook/Dune:/books:ro \
  -v /path/to/output:/out \
  m4bmaker /books \
    --title "Dune" \
    --author "Frank Herbert" \
    --narrator "Scott Brick" \
    --output /out/Dune.m4b \
    --no-prompt
```

---

## Batch Processing

Process multiple audiobooks with a shell loop:

```bash
for book_dir in /audiobooks/*/; do
  title=$(basename "$book_dir")
  docker run --rm \
    -v "$book_dir":/books \
    m4bmaker /books \
      --title "$title" \
      --no-prompt
done
```

---

## Notes

- The container runs as `root` by default. Use `--user $(id -u):$(id -g)` if
  the output directory has restricted permissions.
- Temporary files (`ffmetadata.txt`, `concat.txt`) are written to the system
  temp directory inside the container and cleaned up automatically.
- Pillow is **not** required for Docker usage. Cover auto-detection falls back
  to alphabetical filename ordering when Pillow is absent.
