from prometheus_client import Counter, Gauge, Histogram

API_HTTP_REQUESTS_TOTAL = Counter(
    "api_http_requests_total",
    "Total HTTP requests handled by API Gateway",
    ["method", "endpoint", "status_code"],
)

API_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "api_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

CHECKER_CHECKS_TOTAL = Counter(
    "checker_checks_total",
    "Total target health checks executed",
    ["method", "status"],
)

CHECKER_CHECK_DURATION_SECONDS = Histogram(
    "checker_check_duration_seconds",
    "Target probe latency in seconds",
    ["method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

CHECKER_SSL_DAYS_REMAINING = Gauge(
    "checker_ssl_days_remaining",
    "Remaining days before SSL certificate expiration",
    ["monitor_id"],
)

SCHEDULER_DISPATCHED_JOBS_TOTAL = Counter(
    "scheduler_dispatched_jobs_total",
    "Total monitor check jobs dispatched by scheduler",
)

RABBITMQ_QUEUE_DEPTH = Gauge(
    "rabbitmq_queue_depth",
    "Current number of ready messages in queue",
    ["queue_name"],
)
