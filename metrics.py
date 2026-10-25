"""Prometheus metrics for the captioning app.

All metrics live here and not in app.py. Streamlit re-runs app.py from the top on
every click, so defining them there registers them again and prometheus_client
fails with "Duplicated timeseries in CollectorRegistry". A module is imported
only once per process, so this file runs once.

Naming: everything app-specific starts with caption_, units go in the name
(_seconds, _bytes), counters end in _total (Prometheus best practice).
"""
import os

import psutil
from prometheus_client import (Counter, Gauge, Histogram, Info, Summary,
                               disable_created_metrics, start_http_server)

# Same as the lecture demo: drop the extra *_created series.
disable_created_metrics()

METRICS_PORT = int(os.environ.get("METRICS_PORT", "18000"))   # 18000 like DA3408/Monitoring/ai_app.py
METRICS_ADDR = os.environ.get("METRICS_ADDR", "127.0.0.1")

# ---------------------------------------------------------------- counters
# Only go up. Use rate()/increase() on them in PromQL.
IMAGES_PROCESSED = Counter(
    "caption_images_processed_total", "Images sent through the model",
    ["mode", "status", "client_ip", "session_id", "browser"])
REQUESTS = Counter(
    "caption_requests_total", "Caption requests (one single image or one ZIP = one request)",
    ["mode", "client_ip", "session_id", "browser"])
ERRORS = Counter(
    "caption_errors_total", "Images or uploads that failed, by exception type",
    ["mode", "error_type"])
ZIP_ENTRIES_SKIPPED = Counter(
    "caption_zip_entries_skipped_total", "ZIP entries that were not captioned",
    ["reason"])
BYTES_RECEIVED = Counter(
    "caption_bytes_received_total", "Bytes uploaded by users", ["mode"])
SESSIONS_STARTED = Counter(
    "caption_sessions_started_total", "New browser sessions opened",
    ["client_ip", "browser"])
UNHANDLED_EXCEPTIONS = Counter(
    "caption_unhandled_exceptions_total",
    "Exceptions that escaped a request handler (should stay 0)")

# ------------------------------------------------------------------ gauges
# Can go up and down. Read them as they are.
ACTIVE_REQUESTS = Gauge(
    "caption_active_requests", "Requests being processed right now", ["mode"])
MODEL_QUEUE = Gauge(
    "caption_model_queue_length", "Images waiting for the model lock")
BULK_IMAGES_REMAINING = Gauge(
    "caption_bulk_images_remaining", "Images left in the bulk batches that are running")
MODEL_LOADED = Gauge(
    "caption_model_loaded", "1 once the model is in memory")
MODEL_LOAD_SECONDS = Gauge(
    "caption_model_load_seconds", "How long the model took to load")
LAST_BATCH_SIZE = Gauge(
    "caption_last_batch_size", "Number of images in the last finished ZIP")
LAST_BATCH_DURATION = Gauge(
    "caption_last_batch_duration_seconds", "Wall-clock time of the last finished ZIP")
LAST_BATCH_THROUGHPUT = Gauge(
    "caption_last_batch_images_per_second", "Images per second of the last finished ZIP")
ACTIVE_SESSIONS = Gauge(
    "caption_active_sessions", "Browser sessions Streamlit currently has open")

_proc = psutil.Process()
APP_RSS = Gauge("caption_app_memory_rss_bytes", "Resident memory of the app process (model included)")
APP_RSS.set_function(lambda: _proc.memory_info().rss)
APP_THREADS = Gauge("caption_app_threads", "OS threads in the app process")
APP_THREADS.set_function(lambda: _proc.num_threads())

# -------------------------------------------------------------- histograms
# Buckets picked after a few test runs: BLIP base takes ~0.3-1.5 s per image here.
INFERENCE_SECONDS = Histogram(
    "caption_inference_seconds", "model.generate() time per image", ["mode"],
    buckets=(0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 13))
PREPROCESS_SECONDS = Histogram(
    "caption_preprocess_seconds", "Decode + resize + normalise time per image", ["mode"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1))
QUEUE_WAIT_SECONDS = Histogram(
    "caption_queue_wait_seconds", "Time an image waited for the model lock", ["mode"],
    buckets=(0.001, 0.01, 0.1, 0.5, 1, 2, 5, 10, 30))
IMAGE_MEGAPIXELS = Histogram(
    "caption_image_megapixels", "Resolution of uploaded images", ["mode"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16))
CAPTION_WORDS = Histogram(
    "caption_caption_words", "Words in the generated caption", ["mode"],
    buckets=(2, 4, 6, 8, 10, 12, 15, 20))
BULK_BATCH_SECONDS = Histogram(
    "caption_bulk_batch_seconds", "Wall-clock time of a whole ZIP",
    buckets=(5, 10, 20, 30, 60, 90, 120, 180, 300, 600))

# --------------------------------------------------------------- summaries
# prometheus_client summaries export <name>_count and <name>_sum (no quantiles
# in the Python client). _sum / _count gives the mean.
IMAGE_BYTES = Summary("caption_image_bytes", "Size of each image", ["mode"])
REQUEST_SECONDS = Summary(
    "caption_request_seconds", "End-to-end request time (upload read to last caption)", ["mode"])
ZIP_BYTES = Summary("caption_zip_bytes", "Size of uploaded ZIP files")
ZIP_IMAGES = Summary("caption_zip_images", "Captionable images found per ZIP")

# -------------------------------------------------------------------- info
BUILD = Info("caption_app_build", "Version and model of the captioning app")


MODES = ("single", "bulk")
KNOWN_ERRORS = ("UnidentifiedImageError", "OSError", "BadZipFile", "DecompressionBombError", "ValueError")
SKIP_REASONS = ("macos_metadata", "hidden_file", "not_an_image", "too_large", "over_limit")


def init_label_sets():
    """Create the label combinations we already know about, at 0.

    A labelled series only appears after its first .inc(). increase()/rate() need
    two samples, so the first event of a new series is invisible to them (found
    this when the error ratio showed 0% after the dirty ZIP). Starting at 0 fixes it.
    """
    for mode in MODES:
        ACTIVE_REQUESTS.labels(mode)
        for metric in (INFERENCE_SECONDS, PREPROCESS_SECONDS, QUEUE_WAIT_SECONDS,
                       IMAGE_MEGAPIXELS, CAPTION_WORDS, IMAGE_BYTES, REQUEST_SECONDS):
            metric.labels(mode)
        BYTES_RECEIVED.labels(mode)
        for err in KNOWN_ERRORS:
            ERRORS.labels(mode, err)
    for reason in SKIP_REASONS:
        ZIP_ENTRIES_SKIPPED.labels(reason)


def init_client_label_sets(client_ip, session_id, browser):
    """Same idea per browser session: called once when a session opens."""
    for mode in MODES:
        REQUESTS.labels(mode=mode, client_ip=client_ip, session_id=session_id, browser=browser)
        for status in ("ok", "error"):
            IMAGES_PROCESSED.labels(mode=mode, status=status, client_ip=client_ip,
                                    session_id=session_id, browser=browser)


def start_metrics_server():
    """Expose /metrics on its own port, separate from the Streamlit port."""
    init_label_sets()
    start_http_server(METRICS_PORT, addr=METRICS_ADDR)
    return METRICS_PORT
