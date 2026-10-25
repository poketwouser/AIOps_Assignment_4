# Instructions for TAs: DA3408 Assignment 4

Kiran Kumar P

How to check each rubric item quickly. If you don't want to run anything, every check has screenshots in
[`screenshots/`](screenshots/) (one folder per section of the brief) and the raw logs are in [`results/`](results/).

## 1. Running it

Needs Linux, Docker and Python 3.12+. The Prometheus / node_exporter / Alertmanager binaries are expected in
`~/Desktop/monitoring-tools/` (same tarballs as in class). If yours are somewhere else, change `TOOLS=` in `run_stack.sh`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python make_test_zips.py /path/to/coco/val2017      # or just use your own images / ZIP
./run_stack.sh                                      # node_exporter, Prometheus, Alertmanager, receiver, Grafana
streamlit run app.py --server.address localhost     # first start downloads BLIP (~990 MB)
```

Open http://localhost:8501 once, the metrics server on :18000 starts with the first page load.

| URL | What you should see |
|---|---|
| http://localhost:8501 | the app, your `client_ip` / `session_id` / `browser` labels are in the sidebar |
| http://127.0.0.1:18000/metrics | the `caption_*` metrics |
| http://127.0.0.1:9100/metrics | node_exporter metrics |
| http://127.0.0.1:9090/targets | `caption_app`, `node`, `prometheus`, all UP |
| http://127.0.0.1:9090/alerts | 5 alert rules |
| http://127.0.0.1:9093 | Alertmanager |
| http://127.0.0.1:3000 | Grafana, dashboard "A4 Image Captioner" in folder DA3408 (no login) |

To stop: `./stop_stack.sh`, then Ctrl+C on Streamlit.

## 2. Checklist

### 1. Application Logic (10)

Screenshots: [`screenshots/1_application`](screenshots/1_application)

| Check | How | Expected |
|---|---|---|
| Single image | Single tab, upload a jpg, Generate caption | caption + time (01, 02) |
| Bulk ZIP | Bulk tab, `test_data/bulk_100.zip`, Caption all images | progress bar, ~75 s, 100/100 (03, 04) |
| Two users | two browser tabs, start a ZIP in each | both finish (05) |
| Broken files in a ZIP | `test_data/bulk_dirty.zip` | 10/12 captioned, 2 error rows, no crash (06, 07) |
| Not a ZIP | `test_data/not_a_zip.zip` | "That file is not a valid ZIP archive." (08) |

### 2A. Python Instrumentation (25)

Screenshots: [`screenshots/2A_instrumentation`](screenshots/2A_instrumentation)

| Check | Where |
|---|---|
| Counters with labels | `caption_images_processed_total`, `caption_requests_total`, ... in [`metrics.py`](metrics.py) (01) |
| Gauges (set, inc/dec, `track_inprogress`, `set_function`) | `caption_active_requests`, `caption_bulk_images_remaining`, `caption_app_memory_rss_bytes` (02) |
| Histograms with custom buckets | `caption_inference_seconds` and 5 more (02) |
| Summaries (`_sum` / `_count`) | `caption_image_bytes`, `caption_request_seconds`, `caption_zip_bytes`, `caption_zip_images` (03) |
| Client labels | `client_ip`, `session_id`, `browser`; per-client table in the Grafana "Clients" row ([2D/06](screenshots/2D_grafana_dashboard/06_clients_and_errors.jpg)) |
| Live check | `curl -s 127.0.0.1:18000/metrics \| grep '^# TYPE caption_'` gives 29 metric families |

### 2B. Node Exporting (5)

Screenshots: [`screenshots/2B_node_exporter`](screenshots/2B_node_exporter)

| Check | Where |
|---|---|
| node_exporter running and scraped | `node` job in [`prometheus.yml`](prometheus.yml) (01, 02) |
| System metrics in Grafana | "System (node_exporter)" row (03, 04) and "App vs host" row ([2D/08](screenshots/2D_grafana_dashboard/08_app_vs_host.jpg)) |

### 2C. Alerting

Screenshots: [`screenshots/2C_alerting`](screenshots/2C_alerting)

Stop Streamlit for ~15 s. `CaptionAppDown` fires in Prometheus, goes through Alertmanager and `alert_receiver.py`
writes it to [`results/logs/alerts.log`](results/logs/alerts.log) (02, 03, 04).

### 2D. Grafana Intuitiveness (20)

Screenshots: [`screenshots/2D_grafana_dashboard`](screenshots/2D_grafana_dashboard)

| Check | Where |
|---|---|
| Health first, hardware last | 7 rows top to bottom (01 to 08) |
| Up/Down status | Health row, also with the app stopped (11) |
| Throughput and latency | (01, 03) |
| System use vs bulk uploads | "App vs host" row, plus the purple markers where a ZIP was uploaded (08) |
| 7 Commandments | table in the [README](README.md#2d-grafana-dashboard-grafanadashboardjson); panel description (02); query, axis label and log scale in the panel editor (09, 10) |
| JSON export | [`grafana/dashboard.json`](grafana/dashboard.json) (Dashboards → New → Import, datasource uid `prometheus-a4`) |

## 3. What the numbers should look like

On another CPU the numbers will be different, but the pattern should be the same:

- BLIP base with 8 torch threads: ~0.5-1 s per 640x480 image, so ~1.3 images/s for a ZIP.
- During a ZIP the host CPU is about (torch threads / logical CPUs), ~50% here, and the app process line in
  "Throughput vs CPU" is just under the host line.
- App memory stays flat (~1.6 GB) during ZIPs.

## 4. Checking the metric logic by hand

Real values from my run (Prometheus API at 22:30:17 IST on 23 Oct 2026; the `/metrics` text is in
[`results/metrics_snapshot_app.txt`](results/metrics_snapshot_app.txt)).

**a) Throughput: `rate()` of a counter**

`sum(caption_images_processed_total{mode="bulk",status="ok",session_id="7e67d34c"})`

| time | value |
|---|---|
| 22:29:17 | 5 |
| 22:30:17 | 89 |

(89 - 5) / 60 s = **1.400 images/s**.
Prometheus `rate(...[1m])` at 22:30:17 gives **1.4068**. It's a bit higher because `rate()` extrapolates to the
ends of the 1 minute window (the first and last samples inside it are not exactly 60 s apart).
`increase(...[1m])` gives 84.41 instead of 84 for the same reason.

**b) p95 latency: `histogram_quantile()`**

Buckets of `caption_inference_seconds{mode="bulk"}` after one 100-image ZIP (cumulative):

| le (s) | 0.25 | 0.5 | 0.75 | 1.0 | 1.5 | ... +Inf |
|---|---|---|---|---|---|---|
| count <= le | 0 | 2 | 67 | 99 | 100 | 100 |

95th of 100 = rank 95. The first bucket with count >= 95 is le = 1.0 (99), the one before is le = 0.75 (67).
Interpolating inside that bucket:

p95 = 0.75 + (1.0 - 0.75) x (95 - 67) / (99 - 67) = 0.75 + 0.25 x 28/32 = **0.96875 s**

`histogram_quantile(0.95, caption_inference_seconds_bucket{mode="bulk"})` returns **0.96875**.
(The real p95 is somewhere between 0.75 and 1.0 s. Prometheus assumes the values are spread evenly inside a bucket.)

**c) Mean from a Summary: `_sum / _count`**

- `caption_inference_seconds_sum{mode="bulk"}` = 71.672, `_count` = 100, so **0.717 s per image**
- `caption_request_seconds_sum{mode="bulk"}` = 72.766, `_count` = 1, so that ZIP took **72.8 s** in total
  (the extra ~1.1 s on top of inference is unzipping, decoding and preprocessing)
- `caption_image_bytes_sum{mode="bulk"}` = 6,374,938, `_count` = 100, so **63.7 kB (62.3 KiB)** per image,
  same as the "Average upload size" panel showed at that time

For `mode="single"` there were no requests yet in that process, so 0 / 0 = **NaN**. That's why the query in
[2A/05](screenshots/2A_instrumentation/05_prometheus_p95_and_summary_mean.jpg) shows NaN for single.

**d) App CPU: `rate()` of `process_cpu_seconds_total`**

| time | process_cpu_seconds_total |
|---|---|
| 22:29:17 | 38.15 |
| 22:30:17 | 496.66 |

(496.66 - 38.15) / 60 = **7.64 CPU seconds per second**, so about 8 cores busy, which matches `torch.set_num_threads(8)`.
As a share of 16 CPUs: 7.64 / 16 = **47.8%**. Prometheus gives 7.642 and the dashboard showed 47.77%.
The host CPU at the same time was 53.5% (`node:cpu_busy:percent`), the other ~6% is Streamlit, Chrome,
Prometheus and the OS.

## 5. Known limitations

- I only tested from my own laptop, so `client_ip` is always `127.0.0.1` and users are told apart by `session_id`.
  `session_id` is a high-cardinality label. Fine for this assignment, but in production I would keep it in the
  logs and not on the counters.
- Counters reset when Streamlit restarts. `rate()` / `increase()` handle that, but the "since start" panels
  (table, bar gauges) only show the current process.
- `rate(...[1m])` shows a lower throughput for batches shorter than a minute (README, "Problems I ran into").
