# DA3408 Assignment 4: Application Monitoring with Prometheus & Grafana

Kiran Kumar P

Streamlit app that captions images on the CPU with BLIP base (`Salesforce/blip-image-captioning-base`).
You can upload one image, or a ZIP of images. The app exposes its metrics on a separate port (`:18000/metrics`).
Prometheus scrapes the app and node_exporter every second, Alertmanager sends alerts to a small local webhook,
and Grafana shows the app numbers next to the CPU / RAM / disk numbers of my laptop.

Short version of the results (16 logical CPUs, 14.4 GiB RAM):

- BLIP takes about 0.7 s per image (p50) on the CPU.
- A 100-image ZIP takes 73-76 s, around 1.3 images/s.
- During a ZIP the host CPU goes from ~5% to ~55%, and ~48% of it is the app process. So the bulk uploads
  explain the CPU load (see the "App vs host" row).
- App memory stays at ~1.6 GB the whole time, the model is loaded once and images are done one by one.

Files for the deliverables:

- Dashboard JSON: [`grafana/dashboard.json`](grafana/dashboard.json)
- Prometheus config: [`prometheus.yml`](prometheus.yml) and [`rules.yml`](rules.yml)
- Screenshots, one folder per section of the brief: [`screenshots/`](screenshots/)
- For the TAs: [`Instructions_for_TAs.md`](Instructions_for_TAs.md)

---

## Rubric map

| Rubric item (points) | Where |
|---|---|
| Python Instrumentation (25) | [`metrics.py`](metrics.py) (7 counters, 11 gauges, 6 histograms, 4 summaries, 1 info) used in [`app.py`](app.py). Labels: `mode`, `status`, `client_ip`, `session_id`, `browser`, `error_type`, `reason`. Screenshots in [`screenshots/2A_instrumentation`](screenshots/2A_instrumentation) |
| Node Exporting (5) | `node` job in [`prometheus.yml`](prometheus.yml), started by [`run_stack.sh`](run_stack.sh). Screenshots in [`screenshots/2B_node_exporter`](screenshots/2B_node_exporter) |
| Grafana Intuitiveness (20) | [`grafana/dashboard.json`](grafana/dashboard.json), 7 rows from health down to hardware. Screenshots in [`screenshots/2D_grafana_dashboard`](screenshots/2D_grafana_dashboard) |
| Application Logic (10) | [`app.py`](app.py) Single + Bulk tabs, bad files don't crash it. Screenshots in [`screenshots/1_application`](screenshots/1_application) |

| Deliverable | File |
|---|---|
| GitHub repo with Streamlit app and `prometheus.yml` | this repo |
| Grafana dashboard JSON | [`grafana/dashboard.json`](grafana/dashboard.json) |
| ~1 min video of the dashboard at 5 s refresh | link at the end |

---

## 1. The application

[`app.py`](app.py) is the UI, [`captioner.py`](captioner.py) loads the model, [`metrics.py`](metrics.py) has all the metrics.

**Single image:** upload a jpg/png/webp/bmp, click Generate caption, get the caption and how long it took.

**Bulk (ZIP):** upload a ZIP (max 300 images, 500 MB upload limit), click Caption all images. There is a progress
bar and a live table, and at the end a summary (captioned / total time / images per second) and a CSV download.

Things I did so it doesn't crash on the CPU:

- The model and the metrics server are created once per process with `st.cache_resource`. Without it every
  Streamlit rerun tried to open port 18000 again.
- `torch.set_num_threads(8)`, half of the 16 CPUs, so Streamlit, Prometheus and Grafana still have room.
- A lock around `model.generate()`. If two people upload at once they wait for each other instead of both slowing down.
- Images in a ZIP are opened and captioned one at a time, so memory does not grow with the ZIP size.
- A broken image becomes an error row and the batch continues. Non-images, `__MACOSX` files and hidden files
  are skipped and counted. A file that is not a ZIP gives a message.

Logging is set up the same way as `DA3408/Monitoring/ai_app.py` (named logger, `log.info(...)` per request),
see [`results/logs/streamlit.log`](results/logs/streamlit.log).

Screenshots: [`screenshots/1_application`](screenshots/1_application)

| | |
|---|---|
| 01, 02 | single image captions |
| 03, 04 | 50 and 100 image ZIPs running |
| 05 | a second browser session running at the same time |
| 06, 07 | ZIP with a corrupt and a truncated image: 10/12 captioned, 2 error rows |
| 08 | a text file renamed to .zip |

## 2A. Instrumentation ([`metrics.py`](metrics.py))

All metrics start with `caption_`. They are in their own file because Streamlit re-runs `app.py` on every click,
and defining them there gives "Duplicated timeseries in CollectorRegistry". `disable_created_metrics()` is on,
like in the lecture demo.

| Type | Metric | Labels | What it shows |
|---|---|---|---|
| Counter | `caption_images_processed_total` | mode, status, client_ip, session_id, browser | images through the model, ok or error, per client |
| Counter | `caption_requests_total` | mode, client_ip, session_id, browser | requests (1 image or 1 ZIP) per client |
| Counter | `caption_errors_total` | mode, error_type | failures by exception |
| Counter | `caption_zip_entries_skipped_total` | reason | ZIP entries not captioned and why |
| Counter | `caption_bytes_received_total` | mode | uploaded bytes |
| Counter | `caption_sessions_started_total` | client_ip, browser | new browser sessions |
| Counter | `caption_unhandled_exceptions_total` | | `count_exceptions()` on the handlers, should stay 0 |
| Gauge | `caption_active_requests` | mode | requests in progress (`track_inprogress()`) |
| Gauge | `caption_model_queue_length` | | images waiting for the model lock |
| Gauge | `caption_bulk_images_remaining` | | images left in running ZIPs |
| Gauge | `caption_model_loaded`, `caption_model_load_seconds` | | model state |
| Gauge | `caption_last_batch_size`, `_duration_seconds`, `_images_per_second` | | last finished ZIP |
| Gauge | `caption_active_sessions` | | open Streamlit sessions (`set_function`) |
| Gauge | `caption_app_memory_rss_bytes`, `caption_app_threads` | | app memory and threads (`set_function` + psutil) |
| Histogram | `caption_inference_seconds` | mode | `model.generate()` time per image |
| Histogram | `caption_preprocess_seconds` | mode | decode + resize per image |
| Histogram | `caption_queue_wait_seconds` | mode | time waiting for the model lock |
| Histogram | `caption_image_megapixels` | mode | image resolution |
| Histogram | `caption_caption_words` | mode | caption length |
| Histogram | `caption_bulk_batch_seconds` | | time for a whole ZIP |
| Summary | `caption_image_bytes` | mode | `_sum` / `_count` = average image size |
| Summary | `caption_request_seconds` | mode | `_sum` / `_count` = average request time |
| Summary | `caption_zip_bytes`, `caption_zip_images` | | average ZIP size and images per ZIP |
| Info | `caption_app_build_info` | version, model, torch_threads, max_new_tokens | build info |

The Python client's Summary only gives `_count` and `_sum` (no quantiles). The `_total` ones are the counters.
The default `process_*` metrics (CPU seconds, memory) are also scraped and used in the "App vs host" row.

**Client labels:** `client_ip` is the address of the browser connection. `st.context.ip_address` returns `None`
for localhost, so I take the raw peer address instead. `session_id` is the first 8 characters of Streamlit's
session id, `browser` comes from the User-Agent. I only tested from my own laptop, so `client_ip` is always
`127.0.0.1` and different users show up as different `session_id`s. From another machine the real IP would show.

Screenshots: [`screenshots/2A_instrumentation`](screenshots/2A_instrumentation) (the `/metrics` page and two Prometheus queries).

## 2B. node_exporter

node_exporter 1.12.1 (release binary from the course), scraped as job `node` every 1 s together with the app.
The CPU / memory / disk / network panels are in the "System (node_exporter)" row, and the "App vs host" row puts
them next to the app numbers.

I had to turn off two collectors: `--no-collector.hwmon --no-collector.powersupplyclass`. On my laptop they read
sensors and the battery over ACPI and sometimes took ~0.8 s each, so a node scrape went over the 1 s timeout and
the node target showed short DOWN gaps. I found it with `scrape_duration_seconds` and
`node_scrape_collector_duration_seconds`. Now a scrape takes ~30 ms.

Screenshots: [`screenshots/2B_node_exporter`](screenshots/2B_node_exporter)

## 2C. Alerting

The brief's objective mentions alerting, so I added it (based on the course samples):

- [`rules.yml`](rules.yml): the course's `cpu_util` recording rule plus `node:cpu_busy:percent`,
  `caption:images_per_second:rate1m`, `caption:inference_p95_seconds:1m`. Alerts: `CaptionAppDown`,
  `NodeExporterDown`, `HostCPUHigh` (> 40% for 20 s), `CaptionLatencyHigh` (p95 > 3 s for 30 s), `CaptionErrors`.
- [`alertmanager.yml`](alertmanager.yml): from `sample_alertmanager.yml`, but the webhook is
  [`alert_receiver.py`](alert_receiver.py) on 127.0.0.1:5001 instead of webhook.site. It writes every alert to
  [`results/logs/alerts.log`](results/logs/alerts.log).

What fired during my runs (from `alerts.log`):

| Alert | When |
|---|---|
| `CaptionAppDown` | every time I stopped Streamlit, e.g. stopped 22:27:17, firing 22:27:34, resolved 22:28:49 after the restart |
| `HostCPUHigh` | during the 100-image ZIPs, 22:12:08 (52%) and 22:21:29 (53%) |
| `CaptionErrors` | 22:25:31, after the dirty ZIP and the fake ZIP |

The lines from early morning are from when I first started the stack, before the app was running.

Screenshots: [`screenshots/2C_alerting`](screenshots/2C_alerting)

## 2D. Grafana dashboard ([`grafana/dashboard.json`](grafana/dashboard.json))

44 panels in 7 rows, top to bottom:

1. **Health:** UP/DOWN for the app, node_exporter and Prometheus, model loaded, uptime, alerts firing, up/down history
2. **Throughput and latency:** images/s, p50/p95 inference time, mean request time (from the Summary), requests in progress, latency heatmap
3. **Bulk jobs:** images remaining, last ZIP, average upload size, image resolution and caption length histograms
4. **Clients:** images per client (IP / session / browser), requests per session, sessions
5. **Errors:** failed images by error type, skipped ZIP entries, error ratio, unhandled exceptions
6. **System (node_exporter):** CPU by mode, load average, memory, disk I/O, network, disk / RAM / CPU stats
7. **App vs host:** throughput vs CPU (two y axes), app memory vs host memory, p95 latency vs CPU

The purple dashed lines on the time series are an annotation that marks when a ZIP was uploaded
(`increase(caption_requests_total{mode="bulk"}[5s]) > 0`), so you can see the CPU go up right after each one.

How I followed the 7 Commandments:

| Commandment | What I did |
|---|---|
| Colour-blind friendly palette | only Okabe-Ito colours (`#0072B2`, `#E69F00`, `#009E73`, `#D55E00`, `#CC79A7`, ...), Viridis for the heatmap. Single is always blue, bulk orange, host vermillion |
| Markers that work in print/PDF | point markers on every line, and different line styles (solid, dashed, dotted) so lines can be told apart in black and white |
| Named axes | every time series has an axis label, e.g. "Images per second (linear)" |
| Scale and units | the scale (linear / log2 / log10) is in the axis label and set in the axis options, units are set per panel (s, %, bytes, B/s, img/s) |
| Legend for more than one variable | table legend with mean / max / last |
| Title | short title on every panel, row names say what the row is about |
| Description of the story | each panel has a description (the (i) next to the title) saying which metric/query it uses |

Screenshots: [`screenshots/2D_grafana_dashboard`](screenshots/2D_grafana_dashboard)

## Results

From the runs on 23 Oct 2026, COCO val2017 images (mostly 640x480):

| | |
|---|---|
| Inference p50 / p95 (bulk) | 0.70 s / 0.97 s |
| 50-image ZIP | 38.0 s, 1.32 img/s |
| 100-image ZIP | 73.5 s (1.36 img/s), ~76 s (1.32 img/s) in the last run |
| Host CPU during a ZIP | ~53-56% of 16 CPUs (about the 8 torch threads) |
| App process CPU during a ZIP | ~48% of the host |
| App memory | 1.5-1.7 GB, flat |
| Dirty ZIP (15 entries) | 10 captioned, 2 errors (`UnidentifiedImageError`, `OSError`), 3 skipped |

## Problems I ran into

- **node_exporter gaps**, see 2B.
- **`increase()` missed the first error.** After the dirty ZIP the error ratio said 0%. A labelled series only
  appears after its first `.inc()`, and `increase()` / `rate()` need two samples, so the first event of a new label
  set is lost. I now create the known label sets at 0 when the app starts (`init_label_sets()`), and per session
  when it opens.
- **Stat panels showing old values.** With the app stopped, "Model loaded" still said LOADED and uptime kept its
  old value. Both are now instant queries with a fallback (`or on() vector(0)` / "app down").
- **`rate(...[1m])` and short batches.** A 38 s batch at 1.32 img/s only peaks at ~0.83 img/s on the throughput
  panel, because the 1 minute window also includes idle time. Batches longer than a minute show the real value.
  `caption_last_batch_images_per_second` has the exact number.
- **Streamlit file watcher.** It went through every lazily imported `transformers` module and logged ~300
  torchvision import errors. `fileWatcherType = "none"` in `.streamlit/config.toml` fixed it (it also stops
  `metrics.py` from being imported twice).

---

## How to run

Needs Linux, Python 3.12+ (I used 3.14), Docker and ~3 GB of disk for the model and images.
The Prometheus, node_exporter and Alertmanager release tarballs should be extracted in `~/Desktop/monitoring-tools/`
(or set `TOOLS=...`).

```bash
# 1. python env
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2. test images (COCO val2017, 5000 images, ~780 MB)
mkdir -p ~/Desktop/datasets/coco_val2017 && cd ~/Desktop/datasets/coco_val2017
curl -LO http://images.cocodataset.org/zips/val2017.zip && unzip -q val2017.zip && cd -
python make_test_zips.py ~/Desktop/datasets/coco_val2017/val2017     # makes test_data/

# 3. node_exporter, Prometheus, Alertmanager, alert receiver, Grafana (docker)
./run_stack.sh

# 4. the app (UI on 8501, metrics on 18000 - the metrics server starts when the page is first opened)
streamlit run app.py --server.address localhost

# 5. open
#    http://localhost:8501          app
#    http://127.0.0.1:9090/targets  Prometheus
#    http://127.0.0.1:9093          Alertmanager
#    http://127.0.0.1:3000          Grafana (dashboard is provisioned, no login)

./stop_stack.sh                    # stops everything except Streamlit (Ctrl+C that one)
```

The first start downloads BLIP from Hugging Face (~990 MB).

## Files

```
app.py                     Streamlit app (Single + Bulk), records the metrics
captioner.py               BLIP base on the CPU
metrics.py                 all Prometheus metrics + start_http_server(18000)
prometheus.yml             scrape config (app, node_exporter, prometheus) + Alertmanager
rules.yml                  recording rules + 5 alerts
alertmanager.yml           route + local webhook
alert_receiver.py          webhook that writes alerts to results/logs/alerts.log
grafana/dashboard.json     the dashboard
grafana/provisioning/      datasource + dashboard provisioning for the Grafana container
run_stack.sh, stop_stack.sh
make_test_zips.py          builds test_data/ from COCO val2017
.streamlit/config.toml     upload limit, file watcher off
results/                   alerts.log, service logs, a /metrics snapshot
screenshots/               1_application, 2A_instrumentation, 2B_node_exporter, 2C_alerting, 2D_grafana_dashboard
AI_DISCLOSURE.md           how AI was used (required by the course code of conduct)
```

## Ports

| Port | |
|---|---|
| 8501 | Streamlit |
| 18000 | app `/metrics` |
| 9100 | node_exporter |
| 9090 | Prometheus |
| 9093 | Alertmanager |
| 5001 | alert receiver |
| 3000 | Grafana |

## PromQL used

The brief asks to mark AI-generated PromQL with the prompt. The PromQL in `rules.yml` and the dashboard was
generated with Claude; the prompt is written at the top of `rules.yml`, and the dashboard prompt (JSON has no
comments) is in [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md). The main queries:

| Panel | Query | Meaning |
|---|---|---|
| Throughput | `sum by (mode) (rate(caption_images_processed_total{status="ok"}[1m]))` | how fast the counter grows per second, over the last minute |
| p95 latency | `histogram_quantile(0.95, sum by (le, mode) (rate(caption_inference_seconds_bucket[1m])))` | find the bucket with the 95th percentile and interpolate inside it |
| Mean request time | `rate(caption_request_seconds_sum[1m]) / rate(caption_request_seconds_count[1m])` | seconds added / requests added in the last minute |
| Host CPU % | `100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])))` | 1 - idle fraction, averaged over the 16 CPUs |
| App CPU % | `100 * rate(process_cpu_seconds_total{job="caption_app"}[1m]) / <number of CPUs>` | CPU seconds per second used by the app / number of CPUs |
| Error ratio | `sum(increase(...{status="error"}[15m])) / sum(increase(caption_images_processed_total[15m]))` | failed / all images in 15 min |

Rate, p95 and a Summary mean are worked out by hand from real numbers in
[`Instructions_for_TAs.md`](Instructions_for_TAs.md#4-checking-the-metric-logic-by-hand).

## Video

`dashboard_recording.mp4`, about 1 minute of the dashboard at 5 s refresh while a 100-image ZIP runs: _(link to be added)_
