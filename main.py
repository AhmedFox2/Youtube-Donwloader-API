from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import yt_dlp
import tempfile, os, uuid, threading

app = FastAPI()
progress_dict = {}

@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>YouTube Downloader</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    </head>
    <body class="container mt-5">
        <h1 class="mb-3">YouTube Video Downloader</h1>
        <input id="url" type="text" class="form-control mb-2" placeholder="ضع رابط الفيديو هنا">
        <button class="btn btn-info" onclick="fetchFormats()">تحليل الرابط</button>

        <div id="format-area" class="mt-3" style="display:none;">
            <label>اختر الجودة:</label>
            <select id="format" class="form-select mb-2"></select>
            <button class="btn btn-primary" onclick="startDownload()">تحميل الفيديو</button>
        </div>

        <div class="progress mt-4">
            <div id="progress-bar" class="progress-bar" style="width: 0%;">0%</div>
        </div>

        <div id="download-link" class="mt-3"></div>

<script>
    let currentURL = "";
    let taskId = "";

    // عند تحميل الصفحة
    window.onload = () => {
        const params = new URLSearchParams(window.location.search);
        let input = document.getElementById('url');

        if (params.has('url')) {
            let raw = params.get('url');
            raw = decodeURIComponent(raw);
            if (raw.startsWith("watch?v=")) {
                raw = "https://www.youtube.com/" + raw;
            } else if (!raw.startsWith("http")) {
                raw = "https://www.youtube.com/watch?" + raw;
            }

            input.value = raw;
            fetchFormats(raw);
        }
    };

    async function fetchFormats(link = null) {
        let input = document.getElementById('url');
        let url = link || input.value.trim();

        if (!url.includes("youtube")) return;
        currentURL = url;

        let res = await fetch(`/formats?url=${encodeURIComponent(url)}`);
        let formats = await res.json();
        let select = document.getElementById('format');
        select.innerHTML = "";

        formats.forEach(f => {
            if (!f.filesize) return; // تجاهل الجودات غير المعروفة
            let size = (f.filesize / 1024 / 1024).toFixed(2) + ' MB';
            let opt = document.createElement("option");
            opt.value = f.format_id;
            opt.text = `${f.resolution} (${f.ext}) - ${size}`;
            select.appendChild(opt);
        });

        document.getElementById('format-area').style.display = 'block';
    }

    async function startDownload() {
        let format_id = document.getElementById('format').value;
        let res = await fetch(`/start_download?url=${encodeURIComponent(currentURL)}&format_id=${format_id}`);
        let data = await res.json();
        taskId = data.task_id;

        let interval = setInterval(async () => {
            let r = await fetch(`/progress?task_id=${taskId}`);
            let p = await r.json();
            let bar = document.getElementById("progress-bar");
            bar.style.width = p.progress + "%";
            bar.innerText = p.progress + "%";

            if (p.progress >= 100) {
                clearInterval(interval);
                document.getElementById("download-link").innerHTML = `<a href="/file?task_id=${taskId}" class="btn btn-success mt-3">تحميل الملف</a>`;
            }
        }, 1000);
    }

    // تحليل تلقائي عند الكتابة
    let typingTimer;
    const doneTypingInterval = 1000;
    document.getElementById('url').addEventListener('input', function () {
        clearTimeout(typingTimer);
        typingTimer = setTimeout(() => fetchFormats(), doneTypingInterval);
    });
</script>


    </body>
    </html>
    """

def fetch_formats(url):
    ydl_opts = {'quiet': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = [
            {
                "format_id": f["format_id"],
                "resolution": f.get("format_note") or (f"{f['height']}p" if f.get('height') else "unknown"),
                "ext": f["ext"],
                "filesize": f.get("filesize", 0)
            }
            for f in info.get('formats', [])
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get("filesize")
        ]

        # إضافة خيار Auto
        formats.insert(0, {
            "format_id": "best",
            "resolution": "Auto",
            "ext": "auto",
            "filesize": 0
        })

        return formats

def download_video(url, format_id, task_id):
    temp_dir = tempfile.mkdtemp()

    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded / total * 100)
            progress_dict[task_id] = percent
        elif d['status'] == 'finished':
            progress_dict[task_id] = 100
            progress_dict[f"{task_id}_path"] = d['filename']

    ydl_opts = {
        'format': format_id,
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [hook],
        'merge_output_format': 'mp4'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

@app.get("/", response_class=HTMLResponse)
def index():
    return open("templates/index.html", encoding="utf-8").read()

@app.get("/formats")
def get_formats(url: str):
    formats = fetch_formats(url)
    return formats

@app.get("/start_download")
def start_download(url: str = Query(...), format_id: str = Query("best")):
    task_id = str(uuid.uuid4())
    threading.Thread(target=download_video, args=(url, format_id, task_id)).start()
    return {"task_id": task_id}

@app.get("/progress")
def progress(task_id: str):
    return {"progress": progress_dict.get(task_id, 0)}

@app.get("/file")
def serve_file(task_id: str):
    file_path = progress_dict.get(f"{task_id}_path")
    if file_path and os.path.exists(file_path):
        return FileResponse(file_path, filename=os.path.basename(file_path))
    return JSONResponse(content={"error": "File not found!"}, status_code=404)

if __name__ == "__main__":
    pass