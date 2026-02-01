"""
Pytest fixtures for Helm-based PostgreSQL tests.
Uses subprocess for Helm CLI and kubernetes client for pod/logs/events.
"""
import subprocess
import time
import uuid
from pathlib import Path
from typing import Generator, Tuple

import pytest
from kubernetes import client, config
from kubernetes.client.rest import ApiException


# Release and namespace for the defective image deployment
HELM_REPO_NAME = "bitnami"
HELM_REPO_URL = "https://charts.bitnami.com/bitnami"
CHART_NAME = "bitnami/postgresql"
NAMESPACE = "minimus-test"
POD_WAIT_TIMEOUT = 120
EVENT_WAIT_TIMEOUT = 90


def _helm(*args: str) -> subprocess.CompletedProcess:
    """Run helm command; raise on failure."""
    cmd = ["helm", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _ensure_helm_repo() -> None:
    try:
        _helm("repo", "add", HELM_REPO_NAME, HELM_REPO_URL)
    except subprocess.CalledProcessError as e:
        if "already exists" in (e.stderr or ""):
            _helm("repo", "update", HELM_REPO_NAME)
        else:
            raise


@pytest.fixture(scope="module")
def k8s_client() -> client.CoreV1Api:
    """Load kubeconfig and return CoreV1Api."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


@pytest.fixture(scope="module")
def helm_release(k8s_client: client.CoreV1Api) -> Generator[Tuple[str, str], None, None]:
    """
    Install Bitnami PostgreSQL with the defective image, wait for pod to run, then uninstall.
    Yields (release_name, namespace).
    """
    release_name = f"minimus-test-{uuid.uuid4().hex[:8]}"
    _ensure_helm_repo()

    values_file = Path(__file__).parent.parent / "helm-values" / "defective-image.yaml"
    _helm(
        "install",
        release_name,
        CHART_NAME,
        "--namespace", NAMESPACE,
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
                namespace=NAMESPACE,
                label_selector=selector,
            )
            if pods.items:
                pod = pods.items[0]
                pod_name = pod.metadata.name
                if pod.status.phase == "Running":
                    break
        except ApiException:
            pass
        time.sleep(2)
    if not pod_name:
        pytest.fail(f"Pod with selector {selector} did not reach Running within {POD_WAIT_TIMEOUT}s")

    yield release_name, NAMESPACE

    # Cleanup
    try:
        _helm("uninstall", release_name, "--namespace", NAMESPACE)
    except subprocess.CalledProcessError:
        pass



@pytest.fixture
def pod_name(helm_release: Tuple[str, str], k8s_client: client.CoreV1Api) -> str:
    """Resolve pod name for the current release (same as in helm_release)."""
    release_name, namespace = helm_release
    selector = f"app.kubernetes.io/instance={release_name}"
    pods = k8s_client.list_namespaced_pod(
        namespace=namespace,
        label_selector=selector,
    )
    if not pods.items:
        pytest.fail(f"No pod found for {selector} in {namespace}")
    return pods.items[0].metadata.name
