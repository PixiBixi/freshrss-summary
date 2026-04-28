"""Shared configuration loading and built-in defaults for FreshRSS Summary."""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    """
    Load config from config.yaml (if present), then apply env var overrides.

    Supported env vars (all optional, take priority over config.yaml):
      FRESHRSS_URL           → freshrss.url
      FRESHRSS_USERNAME      → freshrss.username
      FRESHRSS_API_PASSWORD  → freshrss.api_password
      SERVER_HOST            → server.host
      SERVER_PORT            → server.port
      REFRESH_INTERVAL_MINUTES → scheduler.interval_minutes
      DATABASE_URL           → database.url
      TELEGRAM_BOT_TOKEN     → telegram.bot_token
      TELEGRAM_CHAT_ID       → telegram.chat_id
      TELEGRAM_WEBHOOK_SECRET → telegram.webhook_secret
      PUBLIC_URL             → server.public_url
    """
    cfg: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            cfg = yaml.safe_load(f) or {}
    else:
        logger.warning("config.yaml not found — relying entirely on environment variables")

    fr = cfg.setdefault("freshrss", {})
    if v := os.environ.get("FRESHRSS_URL"):
        fr["url"] = v
    if v := os.environ.get("FRESHRSS_USERNAME"):
        fr["username"] = v
    if v := os.environ.get("FRESHRSS_API_PASSWORD"):
        fr["api_password"] = v

    srv = cfg.setdefault("server", {})
    if v := os.environ.get("SERVER_HOST"):
        srv["host"] = v
    if v := os.environ.get("SERVER_PORT"):
        srv["port"] = int(v)
    if v := os.environ.get("PUBLIC_URL"):
        srv["public_url"] = v

    sched = cfg.setdefault("scheduler", {})
    if v := os.environ.get("REFRESH_INTERVAL_MINUTES"):
        sched["interval_minutes"] = int(v)

    db = cfg.setdefault("database", {})
    if v := os.environ.get("DATABASE_URL"):
        db["url"] = v

    tg = cfg.setdefault("telegram", {})
    if v := os.environ.get("TELEGRAM_BOT_TOKEN"):
        tg["bot_token"] = v
    if v := os.environ.get("TELEGRAM_CHAT_ID"):
        tg["chat_id"] = v
    if v := os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        tg["webhook_secret"] = v

    # Validate required FreshRSS fields
    missing = [k for k in ("url", "username", "api_password") if not fr.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing FreshRSS config: {', '.join(missing)}. "
            "Set them in config.yaml or via FRESHRSS_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
        )

    return cfg


DEFAULT_TOPICS: dict = {
    "SRE": {
        "weight": 1.5,
        "keywords": [
            "sre",
            "site reliability",
            "slo",
            "sla",
            "error budget",
            "toil",
            "incident",
            "postmortem",
            "runbook",
            "on-call",
            "oncall",
            "pagerduty",
            "chaos engineering",
            "mttr",
            "mttd",
            "capacity planning",
        ],
    },
    "Kubernetes": {
        "weight": 1.5,
        "keywords": [
            "kubernetes",
            "k8s",
            "kubectl",
            "helm",
            "kustomize",
            "pod",
            "deployment",
            "statefulset",
            "daemonset",
            "container runtime",
            "cri",
            "cni",
            "csi",
            "crd",
            "operator",
            "karpenter",
            "cluster api",
            "vcluster",
            "gateway api",
            "talos",
            "kairos",
            "k3s",
            "rke2",
            "rancher",
            "containerd",
        ],
    },
    "GKE": {
        "weight": 2.0,
        "keywords": [
            "gke",
            "google kubernetes engine",
            "google cloud",
            "gcp",
            "autopilot",
            "workload identity",
            "binary authorization",
            "cloud run",
            "artifact registry",
            "cloud armor",
            "cloud nat",
            "cloud build",
            "cloud deploy",
            "gke enterprise",
            "anthos",
        ],
    },
    "GitOps": {
        "weight": 1.5,
        "keywords": [
            "argocd",
            "argo cd",
            "argo rollouts",
            "argo workflows",
            "gitops",
            "applicationset",
            "sync wave",
            "flux",
            "fluxcd",
        ],
    },
    "Terraform": {
        "weight": 1.3,
        "keywords": [
            "terraform",
            "opentofu",
            "tofu",
            "hcl",
            "tfstate",
            "terragrunt",
            "atlantis",
            "infrastructure as code",
            "iac",
            "pulumi",
            "crossplane",
            "spacelift",
        ],
    },
    "Immutable OS": {
        "weight": 1.4,
        "keywords": [
            "immutable",
            "ostree",
            "bootc",
            "rpm-ostree",
            "flatcar",
            "coreos",
            "fedora coreos",
            "talos",
            "kairos",
            "nixos",
            "butane",
            "sysext",
        ],
    },
    "Platform Engineering": {
        "weight": 1.2,
        "keywords": [
            "platform engineering",
            "internal developer platform",
            "backstage",
            "developer experience",
            "devex",
            "golden path",
            "crossplane",
            "self-service",
            "developer portal",
        ],
    },
    "Observability": {
        "weight": 1.1,
        "keywords": [
            "prometheus",
            "grafana",
            "alertmanager",
            "loki",
            "tempo",
            "mimir",
            "thanos",
            "opentelemetry",
            "otel",
            "tracing",
            "jaeger",
            "pyroscope",
            "monitoring",
            "observability",
            "ebpf",
            "fluent bit",
            "victoria metrics",
            "datadog",
        ],
    },
    "Security": {
        "weight": 1.1,
        "keywords": [
            "cve",
            "vulnerability",
            "rbac",
            "iam",
            "secrets management",
            "vault",
            "trivy",
            "falco",
            "supply chain",
            "sbom",
            "zero trust",
            "opa",
            "gatekeeper",
            "kyverno",
            "external secrets",
            "cert-manager",
            "cosign",
            "sigstore",
            "slsa",
            "kubescape",
        ],
    },
    "CI/CD": {
        "weight": 1.0,
        "keywords": [
            "ci/cd",
            "github actions",
            "gitlab ci",
            "tekton",
            "pipeline",
            "continuous integration",
            "continuous deployment",
            "dora metrics",
            "progressive delivery",
            "canary",
            "blue-green",
            "feature flag",
            "dagger",
        ],
    },
    "Networking": {
        "weight": 1.0,
        "keywords": [
            "service mesh",
            "istio",
            "cilium",
            "calico",
            "envoy",
            "linkerd",
            "ingress",
            "gateway api",
            "ebpf",
            "network policy",
            "metallb",
            "external-dns",
            "coredns",
            "traefik",
            "bgp",
        ],
    },
    "FinOps": {
        "weight": 1.2,
        "keywords": [
            "finops",
            "cost optimization",
            "rightsizing",
            "committed use",
            "spot vm",
            "preemptible",
            "reserved instance",
            "cloud cost",
            "kubecost",
            "opencost",
            "cost allocation",
            "showback",
            "chargeback",
        ],
    },
}
