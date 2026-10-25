# AI Disclosure: DA3408 Assignment 4

Kiran Kumar P

This file is required by section 4 of the course *Code of Conduct: Fair and Responsible Use of AI* and by
section 4 of the A4 brief ("Code of Conduct: Fair Use of AI").

## 1. Tools used

| Tool | Used for |
|---|---|
| Claude (Anthropic), through Claude Code in VS Code | PromQL, config boilerplate, debugging, Grafana panel JSON, wording of the docs |

No other AI assistants were used. The BLIP model (`Salesforce/blip-image-captioning-base`) is the model the
app serves. It is part of the assignment and was not used to help write anything.

## 2. How they were used

| Part | What Claude did | What I did |
|---|---|---|
| PromQL ([`rules.yml`](rules.yml), [`grafana/dashboard.json`](grafana/dashboard.json)) | Wrote the queries from my metric names | Set the alert thresholds from my measured runs (bulk ZIPs push the host CPU to ~53%, so `HostCPUHigh` is at 40%). Ran every query in the Prometheus expression browser. Worked the main ones out by hand (section 4) |
| Grafana dashboard JSON | Helped with the panel JSON: axis labels, Okabe-Ito colour overrides, line styles, panel descriptions | Picked the 7-row layout from health down to hardware, chose which metric goes in which panel, and added the "App vs host" row and the ZIP-upload annotation to show the bulk/CPU correlation |
| Boilerplate | Grafana provisioning files, `run_stack.sh` / `stop_stack.sh`, `alert_receiver.py`, `make_test_zips.py` | Adapted `prometheus.yml` and `alertmanager.yml` from the course samples (section 5). Read every script before running it |
| Python syntax | Streamlit and `prometheus_client` API details (`st.cache_resource`, `set_function`, `track_inprogress`, the raw peer IP when `st.context.ip_address` is `None`) | Chose the metrics, labels and histogram buckets (from test runs), the model, 8 torch threads, the model lock, and captioning ZIP images one at a time |
| Debugging | Explained the root cause when I gave it the error or symptom | Found and checked the four problems in the README ("Problems I ran into"), e.g. node_exporter gaps found with `scrape_duration_seconds` |
| Documentation | Helped with the structure and wording of the README and `Instructions_for_TAs.md` | All numbers, logs and screenshots come from my own runs on 23 Oct 2026 |

## 3. Prompts for the AI-generated PromQL and regex

The brief says AI-generated PromQL and regex must carry the prompt used.

- **`rules.yml`:** the prompt is in the comment at the top of the file.
- **`grafana/dashboard.json`:** JSON has no comments, so the prompt is recorded here. Prompt: "write the PromQL
  for each panel of the A4 dashboard (health, throughput and latency, bulk jobs, clients, errors, node_exporter
  system, app vs host) using the caption_* metrics in metrics.py and the node_exporter metrics". Every panel's
  description (the (i) next to its title) says which metric and query it uses.

Regex matchers in the AI-generated PromQL:

| Regex | Where | What it matches |
|---|---|---|
| `mode=~"system\|user"` | `cpu_util` rule (copied from the course sample) | CPU time in user and kernel mode |
| `mode=~"user\|system\|iowait\|nice\|softirq\|irq"` | Host CPU by mode | every busy CPU mode, without `idle` and `steal` |
| `device!~"lo\|docker.*\|veth.*\|br-.*"` | Network panel | real network cards only, no loopback or Docker bridges |
| `job=~"caption_app\|node\|prometheus"` | Up/down history | the three scrape jobs |


## 4. Impact

Claude made me faster at writing PromQL and Grafana JSON and at debugging.
