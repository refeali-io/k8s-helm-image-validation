"""
Pytest fixtures for Helm-based image validation.
Generic infrastructure - works for PostgreSQL, Redis, or any Bitnami chart.

Configuration is defined inside each test class (not via CLI flags).
The only CLI option is --kube-context to select the Kubernetes cluster.

Usage:
    pytest --kube-context=minimus-test
    pytest tests/test_postgresql_bugs.py --kube-context=docker-desktop
"""
import subprocess
import time
import uuid
from pathlib import Path
from typing import Generator, Tuple

import pytest
from kubernetes import client, config
from kubernetes.client.rest import ApiException


# =============================================================================
# CLI OPTIONS (only --kube-context)
# =============================================================================

def pytest_addoption(parser):
    """Add custom CLI options for Helm test configuration."""
    parser.addoption(
        "--kube-context",
        action="store",
        default=None,
        help="Kubernetes context to use (e.g. docker-desktop, minimus-test). Set before any k8s/helm calls.",
    )


# =============================================================================
# HELM HELPERS
# =============================================================================

HELM_REPO_NAME = "bitnami"
HELM_REPO_URL = "https://charts.bitnami.com/bitnami"
POD_WAIT_TIMEOUT = 120


def _helm(*args: str) -> subprocess.CompletedProcess:
    """Run helm command as subprocess; raise on failure."""
    cmd = ["helm", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def _ensure_helm_repo() -> None:
    """Ensure Bitnami Helm repo is added and updated."""
    try:
        _helm("repo", "add", HELM_REPO_NAME, HELM_REPO_URL)
    except subprocess.CalledProcessError as e:
        if "already exists" in (e.stderr or ""):
            _helm("repo", "update", HELM_REPO_NAME)
        else:
            raise


# =============================================================================
# KUBERNETES CONTEXT (set before any k8s/helm usage)
# =============================================================================

def _set_kube_context(context_name: str) -> None:
    """Switch kubectl context so all subsequent k8s/helm commands use it."""
    subprocess.run(
        ["kubectl", "config", "use-context", context_name],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# =============================================================================
# KUBERNETES CLIENT
# =============================================================================

@pytest.fixture(scope="session")
def k8s_client(request) -> client.CoreV1Api:
    """Load kubeconfig and return CoreV1Api. If --kube-context is set, switch to it first."""
    kube_context = request.config.getoption("--kube-context", default=None)
    if kube_context:
        print(f"\n[K8S] Setting context to: {kube_context}")
        _set_kube_context(kube_context)
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


# =============================================================================
# CONFIGURATION FROM TEST CLASS
# =============================================================================

@pytest.fixture(scope="class")
def container_name(request) -> str:
    """Container name inside the pod (read from test class CONTAINER attribute)."""
    return request.cls.CONTAINER


# =============================================================================
# HELM RELEASE (main fixture - install/uninstall)
# =============================================================================

@pytest.fixture(scope="class")
def helm_release(
    request,
    k8s_client: client.CoreV1Api,
) -> Generator[Tuple[str, str], None, None]:
    """
    Install Helm chart with config from the test class, wait for pod, then uninstall.
    
    Test class must define:
        CHART: str           - e.g. "bitnami/postgresql"
        VALUES_FILE: str     - e.g. "helm-values/postgresql-defective-image-values.yaml"
        NAMESPACE: str       - e.g. "minimus-test"
        RELEASE_PREFIX: str  - e.g. "pg-test"
    
    Yields (release_name, namespace).
    """
    cls = request.cls
    chart = cls.CHART
    values_file = Path(cls.VALUES_FILE)
    namespace = cls.NAMESPACE
    release_prefix = cls.RELEASE_PREFIX

    if not values_file.exists():
        pytest.fail(f"Values file not found: {values_file}")

    release_name = f"{release_prefix}-{uuid.uuid4().hex[:8]}"
    _ensure_helm_repo()

    print(f"\n[HELM] Installing {chart} as '{release_name}' in namespace '{namespace}'")
    print(f"[HELM] Values file: {values_file}")

    _helm(
        "install",
        release_name,
        chart,
        "--namespace", namespace,
        "--create-namespace",
        "-f", str(values_file),
    )

    # Wait for pod to exist and be Running (container started)
    selector = f"app.kubernetes.io/instance={release_name}"
    start = time.time()
    pod_name = None
    while (time.time() - start) < POD_WAIT_TIMEOUT:
        try:
            pods = k8s_client.list_namespaced_pod(
                namespace=namespace,
                label_selector=selector,
            )
            if pods.items:
                pod = pods.items[0]
                pod_name = pod.metadata.name
                if pod.status.phase == "Running":
                    print(f"[HELM] Pod '{pod_name}' is Running")
                    break
        except ApiException:
            pass
        time.sleep(2)

    if not pod_name:
        pytest.fail(f"Pod with selector {selector} did not reach Running within {POD_WAIT_TIMEOUT}s")

    yield release_name, namespace

    # Cleanup
    print(f"\n[HELM] Uninstalling '{release_name}'")
    try:
        _helm("uninstall", release_name, "--namespace", namespace)
    except subprocess.CalledProcessError:
        pass


# =============================================================================
# POD NAME (resolved from release)
# =============================================================================

@pytest.fixture
def pod_name(request, helm_release: Tuple[str, str], k8s_client: client.CoreV1Api) -> str:
    """Resolve pod name for the current release."""
    release_name, namespace = helm_release
    selector = f"app.kubernetes.io/instance={release_name}"
    pods = k8s_client.list_namespaced_pod(
        namespace=namespace,
        label_selector=selector,
    )
    if not pods.items:
        pytest.fail(f"No pod found for {selector} in {namespace}")
    return pods.items[0].metadata.name
