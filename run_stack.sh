#!/usr/bin/env bash
# Starts node_exporter, Prometheus, Alertmanager, the alert receiver and Grafana.
# The Streamlit app is started separately (see README).
set -e
cd "$(dirname "$0")"
TOOLS=${TOOLS:-$HOME/Desktop/monitoring-tools}     # where the course tarballs were extracted
NODE=$TOOLS/node_exporter-1.12.1.linux-amd64
PROM=$TOOLS/prometheus-3.15.0.linux-amd64
AM=$TOOLS/alertmanager-0.34.1.linux-amd64
mkdir -p results/logs run

start() {   # name, command...
  local name=$1; shift
  nohup "$@" > results/logs/$name.log 2>&1 &
  echo $! > run/$name.pid
  echo "started $name (pid $!)"
}

# hwmon and powersupplyclass read laptop sensors/battery over ACPI and sometimes take ~0.8 s each,
# which made node scrapes miss the 1 s timeout (gaps in the up{job="node"} lane). Not needed here.
start node_exporter  $NODE/node_exporter --web.listen-address=127.0.0.1:9100 \
                       --no-collector.hwmon --no-collector.powersupplyclass
start prometheus     $PROM/prometheus --config.file=prometheus.yml --storage.tsdb.path=run/prom-data \
                       --web.listen-address=127.0.0.1:9090 --web.enable-lifecycle
start alertmanager   $AM/alertmanager --config.file=alertmanager.yml --storage.path=run/am-data \
                       --web.listen-address=127.0.0.1:9093 --cluster.listen-address=
start alert_receiver python3 alert_receiver.py

# Grafana in Docker. Host network so it can reach Prometheus on 127.0.0.1:9090.
# Anonymous admin is only OK because it listens on 127.0.0.1.
docker rm -f a4-grafana >/dev/null 2>&1 || true
docker run -d --name a4-grafana --network host \
  -e GF_SERVER_HTTP_ADDR=127.0.0.1 \
  -e GF_AUTH_ANONYMOUS_ENABLED=true -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
  -e GF_AUTH_DISABLE_LOGIN_FORM=true -e GF_ANALYTICS_REPORTING_ENABLED=false \
  -e GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/var/lib/grafana/dashboards/dashboard.json \
  -v "$PWD/grafana/provisioning:/etc/grafana/provisioning:ro" \
  -v "$PWD/grafana/dashboard.json:/var/lib/grafana/dashboards/dashboard.json:ro" \
  -v a4-grafana-data:/var/lib/grafana \
  grafana/grafana-enterprise:latest > /dev/null
echo "started grafana (container a4-grafana)"

echo
echo "node_exporter  http://127.0.0.1:9100/metrics"
echo "Prometheus     http://127.0.0.1:9090/targets"
echo "Alertmanager   http://127.0.0.1:9093"
echo "Grafana        http://127.0.0.1:3000"
