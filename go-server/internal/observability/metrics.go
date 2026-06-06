package observability

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Metrics holds the Prometheus collectors used by the Go server.
type Metrics struct {
	RequestDuration *prometheus.HistogramVec
	RequestTotal    *prometheus.CounterVec
	UpstreamFailure *prometheus.CounterVec
	InFlight        prometheus.Gauge
}

// NewMetrics registers and returns the metrics collectors.
func NewMetrics() *Metrics {
	m := &Metrics{
		RequestDuration: promauto.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "HTTP request latency in seconds.",
			Buckets: []float64{0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10},
		}, []string{"service", "method", "path", "status"}),
		RequestTotal: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "http_requests_total",
			Help: "Total HTTP requests processed.",
		}, []string{"service", "method", "path", "status"}),
		UpstreamFailure: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "upstream_failures_total",
			Help: "Failures calling upstream services.",
		}, []string{"upstream", "reason"}),
		InFlight: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "http_in_flight_requests",
			Help: "Number of HTTP requests currently being processed.",
		}),
	}
	return m
}
