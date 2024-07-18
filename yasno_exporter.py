import logging as log
import os
import re
import signal
import sys
import time
from datetime import datetime

import requests
from icalendar import Calendar
from prometheus_client import REGISTRY, Gauge, start_http_server
from pytz import UTC


class YasnoMetricException(Exception):
    pass


class YasnoMetric:
    def __init__(self, yasno_key):
        self.yasno_key = yasno_key
        self.name = f"yasno_{self.convert_yasno_key_to_prometheus_name()}"
        self.metric = Gauge(
            self.name, f"value from Yasno {yasno_key}", labelnames=["group"]
        )

    def convert_yasno_key_to_prometheus_name(self):
        # bms_bmsStatus.maxCellTemp -> bms_bms_status_max_cell_temp
        # pd.ext4p8Port -> pd_ext4p8_port
        key = self.yasno_key.replace(".", "_")
        new = key[0].lower()
        for character in key[1:]:
            if character.isupper() and not new[-1] == "_":
                new += "_"
            new += character.lower()
        # Check that metric name complies with the data model for valid characters
        # https://prometheus.io/docs/concepts/data_model/#metric-names-and-labels
        if not re.match("[a-zA-Z_:][a-zA-Z0-9_:]*", new):
            raise YasnoMetricException(
                f"Cannot convert key {self.yasno_key} to comply with the Prometheus data model. Please, raise an issue!"
            )
        return new

    def set(self, value, label):
        # According to best practices for naming metrics and labels, the voltage should be in volts and the current in amperes
        # WARNING! This will ruin all Prometheus historical data and backward compatibility of Grafana dashboard
        # value = value / 1000 if value.endswith("_vol") or value.endswith("_amp") else value
        log.debug(f"Set {self.name} = {value} with {label}")
        self.metric.labels(group=label).set(value)

    def clear(self):
        log.debug(f"Clear {self.name}")
        self.metric.clear()


class Worker:
    def __init__(self, collecting_interval_seconds):
        self.collecting_interval_seconds = collecting_interval_seconds
        self.metrics_collector = []
        self.BLACKOUT = "blackout"
        self.POSSIBLE_BLACKOUT = "possible_blackout"
        self.NO_BLACKOUT = "no_blackout"

    def loop(self):
        while True:
            self.process_calendar()
            time.sleep(self.collecting_interval_seconds)

    def get_metric_by_yasno_key(self, yasno_key):
        for metric in self.metrics_collector:
            if metric.yasno_key == yasno_key:
                log.debug(f"Found metric {metric.name} linked to {yasno_key} for group")
                return metric
        log.debug(f"Cannot find metric linked to {yasno_key}")
        return False

    def process_calendar(self):
        for id in range(1, 7):
            group_name = f"group_{id}"
            for yasno_key in [self.BLACKOUT, self.POSSIBLE_BLACKOUT, self.NO_BLACKOUT]:
                metric = self.get_metric_by_yasno_key(yasno_key)
                if not metric:
                    try:
                        metric = YasnoMetric(yasno_key)
                    except YasnoMetricException as error:
                        log.error(error)
                        continue
                    log.info(
                        f"Created new metric from payload key {metric.yasno_key} -> {metric.name}"
                    )
                    self.metrics_collector.append(metric)

            response = requests.get(
                f"https://tarik02.github.io/yasno-ics/kyiv/{group_name}.ics"
            )

            data = response.content
            blackout = False
            possible_blackout = False

            gcal = Calendar.from_ical(data)
            for component in gcal.walk():
                if component.name == "VEVENT":
                    summary = component.get("summary")
                    now = UTC.localize(datetime.now())
                    start_time = component.get("dtstart").dt
                    end_time = component.get("dtend").dt
                    if now > start_time and now < end_time:
                        match summary:
                            case "Світла немає":
                                blackout = True
                                break
                            case "Можливе відключення":
                                possible_blackout = True

            if blackout:
                metric = self.get_metric_by_yasno_key(self.BLACKOUT)
                metric.set(1, group_name)
                metric = self.get_metric_by_yasno_key(self.POSSIBLE_BLACKOUT)
                metric.set(0, group_name)
                metric = self.get_metric_by_yasno_key(self.NO_BLACKOUT)
                metric.set(0, group_name)
            elif possible_blackout:
                metric = self.get_metric_by_yasno_key(self.BLACKOUT)
                metric.set(0, group_name)
                metric = self.get_metric_by_yasno_key(self.POSSIBLE_BLACKOUT)
                metric.set(1, group_name)
                metric = self.get_metric_by_yasno_key(self.NO_BLACKOUT)
                metric.set(0, group_name)
            else:
                metric = self.get_metric_by_yasno_key(self.BLACKOUT)
                metric.set(0, group_name)
                metric = self.get_metric_by_yasno_key(self.POSSIBLE_BLACKOUT)
                metric.set(0, group_name)
                metric = self.get_metric_by_yasno_key(self.NO_BLACKOUT)
                metric.set(1, group_name)


def signal_handler(signum, frame):
    log.info(f"Received signal {signum}. Exiting...")
    sys.exit(0)


def main():
    # Register the signal handler for SIGTERM
    signal.signal(signal.SIGTERM, signal_handler)

    # Disable Process and Platform collectors
    for coll in list(REGISTRY._collector_to_names.keys()):
        REGISTRY.unregister(coll)

    log_level = os.getenv("LOG_LEVEL", "INFO")

    match log_level:
        case "DEBUG":
            log_level = log.DEBUG
        case "INFO":
            log_level = log.INFO
        case "WARNING":
            log_level = log.WARNING
        case "ERROR":
            log_level = log.ERROR
        case _:
            log_level = log.INFO

    log.basicConfig(
        stream=sys.stdout,
        level=log_level,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    exporter_port = int(os.getenv("EXPORTER_PORT", "9090"))
    collecting_interval_seconds = int(os.getenv("COLLECTING_INTERVAL", "300"))

    metrics = Worker(collecting_interval_seconds)

    start_http_server(exporter_port)

    try:
        metrics.loop()

    except KeyboardInterrupt:
        log.info("Received KeyboardInterrupt. Exiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()
