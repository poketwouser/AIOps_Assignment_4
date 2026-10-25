"""CPU image captioning with Streamlit, instrumented for Prometheus.

Run:  streamlit run app.py        (UI on :8501, metrics on :18000/metrics)
"""
import io
import logging
import time
import zipfile

import streamlit as st
from PIL import Image
from streamlit.runtime.scriptrunner import get_script_run_ctx

import metrics as m
from captioner import MAX_NEW_TOKENS, MODEL_NAME, TORCH_THREADS, Captioner

APP_VERSION = "1.0.0"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
MAX_ZIP_IMAGES = 300                 # keeps one upload from holding the CPU for too long
MAX_ENTRY_BYTES = 30 * 1024 * 1024   # a single file inside the ZIP bigger than this is skipped

st.set_page_config(page_title="CPU Image Captioner", layout="wide")

# Setup the logging mechanism (same as DA3408/Monitoring/ai_app.py).
# Streamlit re-runs this file on every click, so only add the handler once.
log = logging.getLogger("caption_app")
if not log.handlers:
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    log.addHandler(ch)


# ------------------------------------------------------------- one-time setup
# st.cache_resource runs these once per process. Without it every rerun would try
# to bind port 18000 again ("Address already in use") and reload the model.
def _count_sessions():
    try:
        from streamlit.runtime import Runtime
        return Runtime.instance()._session_mgr.num_active_sessions()
    except Exception:
        return 0


@st.cache_resource
def start_metrics_server():
    port = m.start_metrics_server()
    m.ACTIVE_SESSIONS.set_function(_count_sessions)
    log.info(f"started the prometheus monitor at port {port}")
    return port


@st.cache_resource(show_spinner="Loading BLIP on the CPU (only on the first start)...")
def load_captioner():
    cap = Captioner()
    m.MODEL_LOAD_SECONDS.set(cap.load_seconds)
    m.MODEL_LOADED.set(1)
    log.info(f"loaded {MODEL_NAME} in {cap.load_seconds:.1f} s, torch threads = {TORCH_THREADS}")
    m.BUILD.info({"version": APP_VERSION, "model": MODEL_NAME,
                  "torch_threads": str(TORCH_THREADS), "max_new_tokens": str(MAX_NEW_TOKENS)})
    return cap


# ------------------------------------------------------------ client labels
def browser_family(user_agent):
    ua = user_agent.lower()
    # order matters: Edge's UA also says Chrome, Chrome's also says Safari
    for key, name in (("edg/", "edge"), ("firefox", "firefox"), ("chrome", "chrome"),
                      ("safari", "safari"), ("curl", "curl"), ("python", "python")):
        if key in ua:
            return name
    return "other"


def client_ip():
    # st.context.ip_address returns None for 127.0.0.1 and ::1. Fall back to the raw
    # websocket peer so local IPv4 and IPv6 clients still show up as different IPs.
    ip = st.context.ip_address
    if ip:
        return ip
    try:
        from streamlit.runtime.context import _get_client_context
        return _get_client_context().remote_ip or "unknown"
    except Exception:
        return "localhost"


def client_labels():
    ctx = get_script_run_ctx()
    return {
        "client_ip": client_ip(),
        "session_id": ctx.session_id[:8] if ctx else "unknown",   # first 8 chars are enough to tell sessions apart
        "browser": browser_family(st.context.headers.get("User-Agent", "")),
    }


# ----------------------------------------------------------------- captioning
def caption_one(cap, image, mode, labels):
    """Caption one PIL image and record the per-image metrics."""
    width, height = image.size
    m.IMAGE_MEGAPIXELS.labels(mode).observe(width * height / 1e6)
    with m.PREPROCESS_SECONDS.labels(mode).time():
        inputs = cap.preprocess(image)

    m.MODEL_QUEUE.inc()
    waited_from = time.perf_counter()
    with cap.lock:
        m.MODEL_QUEUE.dec()
        m.QUEUE_WAIT_SECONDS.labels(mode).observe(time.perf_counter() - waited_from)
        with m.INFERENCE_SECONDS.labels(mode).time():
            text = cap.generate(inputs)

    m.CAPTION_WORDS.labels(mode).observe(len(text.split()))
    m.IMAGES_PROCESSED.labels(mode=mode, status="ok", **labels).inc()
    return text


def record_failure(mode, labels, exc):
    m.ERRORS.labels(mode, type(exc).__name__).inc()
    m.IMAGES_PROCESSED.labels(mode=mode, status="error", **labels).inc()


@m.UNHANDLED_EXCEPTIONS.count_exceptions()
def run_single(cap, upload, labels):
    mode = "single"
    data = upload.getvalue()
    log.info(f"run_single: received {len(data)} bytes from client {labels['client_ip']} session {labels['session_id']}")
    m.REQUESTS.labels(mode=mode, **labels).inc()
    m.BYTES_RECEIVED.labels(mode).inc(len(data))
    m.IMAGE_BYTES.labels(mode).observe(len(data))
    with m.ACTIVE_REQUESTS.labels(mode).track_inprogress(), m.REQUEST_SECONDS.labels(mode).time():
        start = time.perf_counter()
        try:
            text = caption_one(cap, Image.open(io.BytesIO(data)), mode, labels)
            return {"caption": text, "seconds": time.perf_counter() - start, "error": None}
        except Exception as exc:          # a broken image should give a message, not a crash
            record_failure(mode, labels, exc)
            log.warning(f"run_single: could not caption the image: {exc}")
            return {"caption": None, "seconds": 0.0, "error": f"{type(exc).__name__}: {exc}"}


def pick_images(zf):
    """Names of the entries worth captioning. Everything else is counted by reason."""
    names = []
    for info in zf.infolist():
        name = info.filename
        base = name.rsplit("/", 1)[-1]
        if info.is_dir():
            continue
        if "__MACOSX/" in name or base.startswith("._"):
            reason = "macos_metadata"
        elif base.startswith("."):
            reason = "hidden_file"
        elif not name.lower().endswith(IMAGE_EXTS):
            reason = "not_an_image"
        elif info.file_size > MAX_ENTRY_BYTES:
            reason = "too_large"
        elif len(names) >= MAX_ZIP_IMAGES:
            reason = "over_limit"
        else:
            names.append(name)
            continue
        m.ZIP_ENTRIES_SKIPPED.labels(reason).inc()
    return names


@m.UNHANDLED_EXCEPTIONS.count_exceptions()
def run_bulk(cap, upload, labels, progress, live_table):
    mode = "bulk"
    data = upload.getvalue()
    log.info(f"run_bulk: received a {len(data)} byte ZIP from client {labels['client_ip']} session {labels['session_id']}")
    m.REQUESTS.labels(mode=mode, **labels).inc()
    m.BYTES_RECEIVED.labels(mode).inc(len(data))
    m.ZIP_BYTES.observe(len(data))
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        m.ERRORS.labels(mode, type(exc).__name__).inc()
        log.warning("run_bulk: upload is not a valid ZIP")
        return {"error": "That file is not a valid ZIP archive."}

    names = pick_images(zf)
    m.ZIP_IMAGES.observe(len(names))
    if not names:
        return {"error": "No images found in the ZIP (looked for " + ", ".join(IMAGE_EXTS) + ")."}

    rows, done = [], 0
    start = time.perf_counter()
    m.BULK_IMAGES_REMAINING.inc(len(names))
    try:
        with m.ACTIVE_REQUESTS.labels(mode).track_inprogress(), m.REQUEST_SECONDS.labels(mode).time():
            for name in names:
                t0 = time.perf_counter()
                try:
                    raw = zf.read(name)
                    m.IMAGE_BYTES.labels(mode).observe(len(raw))
                    text = caption_one(cap, Image.open(io.BytesIO(raw)), mode, labels)
                    rows.append({"file": name, "caption": text, "status": "ok"})
                except Exception as exc:      # one bad file must not stop the batch
                    record_failure(mode, labels, exc)
                    log.warning(f"run_bulk: {name} failed: {type(exc).__name__}")
                    rows.append({"file": name, "caption": "", "status": f"error: {type(exc).__name__}"})
                rows[-1]["seconds"] = round(time.perf_counter() - t0, 2)
                done += 1
                m.BULK_IMAGES_REMAINING.dec()
                progress.progress(done / len(names), text=f"{done} / {len(names)} images")
                live_table.dataframe(rows[-8:], hide_index=True, width="stretch")
    finally:
        # if the user leaves mid-batch, take the unprocessed images off the gauge
        m.BULK_IMAGES_REMAINING.dec(len(names) - done)

    elapsed = time.perf_counter() - start
    m.BULK_BATCH_SECONDS.observe(elapsed)
    m.LAST_BATCH_SIZE.set(len(names))
    m.LAST_BATCH_DURATION.set(elapsed)
    m.LAST_BATCH_THROUGHPUT.set(len(names) / elapsed)
    log.info(f"run_bulk: {len(names)} images in {elapsed:.1f} s ({len(names) / elapsed:.2f} img/s)")
    return {"rows": rows, "seconds": elapsed, "error": None}


# ------------------------------------------------------------------------- UI
metrics_port = start_metrics_server()
cap = load_captioner()
labels = client_labels()

if "session_counted" not in st.session_state:
    st.session_state.session_counted = True
    m.SESSIONS_STARTED.labels(labels["client_ip"], labels["browser"]).inc()
    m.init_client_label_sets(**labels)

with st.sidebar:
    st.header("About")
    st.write(f"Model: `{MODEL_NAME}`  \nRunning on CPU with {TORCH_THREADS} torch threads.  \n"
             f"Model load time: {cap.load_seconds:.1f} s")
    st.write(f"Prometheus metrics: http://localhost:{metrics_port}/metrics")
    st.subheader("Your labels")
    st.caption("These are attached to the metrics for your requests.")
    st.json(labels)

st.title("CPU Image Captioner")
st.caption("BLIP base on the CPU. Upload one image, or a ZIP of images for a batch.")

tab_single, tab_bulk = st.tabs(["Single image", "Bulk (ZIP)"])

with tab_single:
    upload = st.file_uploader("Image", type=[e[1:] for e in IMAGE_EXTS], key="single_upload")
    if upload is not None:
        col_img, col_out = st.columns([3, 2])
        col_img.image(upload, width="stretch")
        with col_out:
            if st.button("Generate caption", type="primary"):
                with st.spinner("Captioning..."):
                    st.session_state.single_result = (upload.file_id, run_single(cap, upload, labels))
            saved = st.session_state.get("single_result")
            if saved and saved[0] == upload.file_id:
                result = saved[1]
                if result["error"]:
                    st.error(f"Could not caption this image. {result['error']}")
                else:
                    st.subheader(result["caption"])
                    st.caption(f"{result['seconds']:.2f} s on the CPU")

with tab_bulk:
    upload = st.file_uploader("ZIP of images", type=["zip"], key="bulk_upload")
    st.caption(f"Up to {MAX_ZIP_IMAGES} images per ZIP. Non-image files and macOS metadata are skipped.")
    if upload is not None and st.button("Caption all images", type="primary"):
        progress = st.progress(0.0, text="Starting...")
        live_table = st.empty()
        result = run_bulk(cap, upload, labels, progress, live_table)
        live_table.empty()
        if result["error"]:
            progress.empty()
        st.session_state.bulk_result = (upload.file_id, result)

    saved = st.session_state.get("bulk_result")
    if upload is not None and saved and saved[0] == upload.file_id:
        result = saved[1]
        if result["error"]:
            st.error(result["error"])
        else:
            rows = result["rows"]
            ok = sum(r["status"] == "ok" for r in rows)
            c1, c2, c3 = st.columns(3)
            c1.metric("Captioned", f"{ok} / {len(rows)}")
            c2.metric("Total time", f"{result['seconds']:.1f} s")
            c3.metric("Throughput", f"{len(rows) / result['seconds']:.2f} img/s")
            st.dataframe(rows, hide_index=True, width="stretch")
            csv = "file,caption,status,seconds\n" + "\n".join(
                f"\"{r['file']}\",\"{r['caption']}\",{r['status']},{r['seconds']}" for r in rows)
            st.download_button("Download captions (CSV)", csv, file_name="captions.csv", mime="text/csv")
