"""
Helm-based automated tests for the minimized PostgreSQL image.
Validates DEF-02: hook directory permission denied (preinitdb.d, initdb.d) via
ls -ld and container logs.

Note on K8s vs Docker:
- Docker: Pod crashes (DEF-01 + DEF-02).
- K8s: Pod starts (PVC masks DEF-01); DEF-02 still visible in perms and logs.

Usage:
    pytest --kube-context=docker-desktop
    pytest tests/test_postgresql_bugs.py
"""
import subprocess
import time
from typing import Tuple

import allure
import pytest


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# DEF-02: hook dirs have drwx------ root root
DEFECTIVE_HOOK_DIR_MODE = "drwx------"
DEFECTIVE_OWNER_GROUP = "root root"

# DEF-01: data dir has drwxr-x--- root root (on Docker; masked by PVC on K8s)
DEFECTIVE_DATA_DIR_MODE = "drwxr-x---"


# -----------------------------------------------------------------------------
# Helpers: reporting & pod (decorated with @allure.step)
# -----------------------------------------------------------------------------

@allure.step("Report: {what}")
def _report(what: str, expected: str, actual: str) -> None:
    """Print what is tested, expected, and actual."""
    print(f"\n  What is tested: {what}")
    print(f"  Expected:       {expected}")
    print(f"  Actual:         {actual}")


@allure.step("Fetch container logs (tail={tail})")
def _get_pod_logs(k8s_client, namespace: str, pod_name: str, container: str, tail: int = 200) -> str:
    """Fetch logs from the container."""
    return k8s_client.read_namespaced_pod_log(
        name=pod_name, namespace=namespace, container=container, tail_lines=tail
    )


@allure.step("Check if pod is ready")
def _is_pod_ready(k8s_client, namespace: str, pod_name: str) -> bool:
    """True if pod Ready condition is True."""
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=namespace)
    for c in pod.status.conditions or []:
        if c.type == "Ready":
            return c.status == "True"
    return False


@allure.step("Wait for pod readiness (timeout={timeout_sec}s)")
def _wait_for_pod_ready(
    k8s_client, namespace: str, pod_name: str, timeout_sec: int = 90, poll_sec: float = 2.0
) -> bool:
    """Wait for pod Ready (readiness probe). Returns True when ready."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _is_pod_ready(k8s_client, namespace, pod_name):
            return True
        time.sleep(poll_sec)
    return False


@allure.step("Execute: kubectl exec ls -ld {path}")
def _exec_ls_ld(namespace: str, pod_name: str, container: str, path: str) -> str:
    """Run ls -ld <path> in the pod. Returns stripped stdout."""
    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name, "-c", container, "--", "ls", "-ld", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return (result.stdout or "").strip()


@allure.step("Parse ls -ld output")
def _parse_ls_ld(line: str) -> Tuple[str, str]:
    """Parse 'ls -ld' output. Returns (mode, 'owner group')."""
    parts = line.split()
    mode = parts[0] if len(parts) >= 1 else ""
    owner_group = f"{parts[2]} {parts[3]}" if len(parts) >= 4 else ""
    return mode, owner_group


@allure.step("Assert hook dir permissions: {path} ({sec_id})")
def _assert_hook_dir_permissions(
    namespace: str,
    pod_name: str,
    container: str,
    path: str,
    sec_id: str,
    path_label: str,
) -> None:
    """
    Exec ls -ld <path> in pod, compare to DEF-02 expected (drwx------ root root),
    report and assert.
    """
    ls_output = _exec_ls_ld(namespace, pod_name, container, path)
    mode, owner_group = _parse_ls_ld(ls_output)
    actual = f"{mode} {owner_group}"
    expected = f"{DEFECTIVE_HOOK_DIR_MODE} {DEFECTIVE_OWNER_GROUP}"
    match = mode == DEFECTIVE_HOOK_DIR_MODE and owner_group == DEFECTIVE_OWNER_GROUP

    _report(
        f"Directory permissions for {path} ({sec_id}).",
        f"Defective perms: {expected} (DEF-02).",
        f"Actual: {actual}",
    )
    assert match, f"Expected {expected}; got: {ls_output}"


@allure.step("Assert data dir masked by PVC: {path}")
def _assert_data_dir_masked_by_pvc(
    namespace: str,
    pod_name: str,
    container: str,
    path: str,
) -> str:
    """
    Exec ls -ld <path> (data dir), log the behavioral difference Docker vs K8s,
    assert that PVC has masked the defect (mode is NOT the defective drwxr-x---).
    Returns the actual mode for further reporting.
    """
    ls_output = _exec_ls_ld(namespace, pod_name, container, path)
    mode, owner_group = _parse_ls_ld(ls_output)
    actual = f"{mode} {owner_group}"
    defective = f"{DEFECTIVE_DATA_DIR_MODE} {DEFECTIVE_OWNER_GROUP}"

    print(f"\n      --- Behavioral Difference: Docker vs K8s ---")
    print(f"      Docker (image):  {defective}  --> container CRASHES (DEF-01)")
    print(f"      K8s (PVC mount): {actual}  --> container STARTS (defect masked)")
    print(f"      -------------------------------------------------")

    _report(
        f"Directory permissions for {path} (SEC-02).",
        f"NOT defective ({DEFECTIVE_DATA_DIR_MODE}) – PVC should mask DEF-01.",
        f"Actual: {actual} (PVC-provided)",
    )

    is_masked = mode != DEFECTIVE_DATA_DIR_MODE
    assert is_masked, (
        f"Expected PVC to mask defect; got defective mode {DEFECTIVE_DATA_DIR_MODE}. "
        f"ls -ld: {ls_output}"
    )
    return actual


@allure.step("Assert logs contain 'Permission denied' for {path_label} ({sec_id})")
def _assert_logs_permission_denied_for_path(
    logs: str,
    path_substring: str,
    sec_id: str,
    path_label: str,
) -> None:
    """
    Assert logs contain 'Permission denied' and path substring; report and assert.
    """
    found = "Permission denied" in logs and path_substring in logs
    what = f"Container logs show 'Permission denied' for {path_label} ({sec_id})."
    expected = f"Logs contain 'Permission denied' for {path_label}."

    if found:
        lines = [l for l in logs.split("\n") if "Permission denied" in l and path_substring in l]
        actual = f"Logs contain 'Permission denied' for {path_label}: {lines[0].strip() if lines else '(found)'}"
    else:
        actual = f"Logs do NOT contain expected {path_label} permission error. Snippet: {logs[:300]}"

    _report(what, expected, actual)
    assert found, f"Expected 'Permission denied' for {path_label} in logs (DEF-02). Snippet: {logs[:500]}"


# -----------------------------------------------------------------------------
# Test class
# -----------------------------------------------------------------------------

@pytest.mark.helm
@pytest.mark.defect
@allure.epic("Minimus PostgreSQL Image Validation")
@allure.feature("Permission Defects (DEF-01, DEF-02)")
class TestPostgreSQLBugs:
    """
    Defects when deploying halex1985/postgresql:latest via Bitnami Helm chart.

    SEC-04 (preinitdb.d) and SEC-03 (initdb.d): hook dirs have drwx------ (DEF-02),
    visible in ls -ld and in container logs. Pod still starts on K8s (PVC masks DEF-01).
    """

    CHART = "bitnami/postgresql"
    VALUES_FILE = "helm-values/postgresql-defective-image-values.yaml"
    CONTAINER = "postgresql"
    NAMESPACE = "test-postgre-sql-bugs"
    RELEASE_PREFIX = "pg-test"

    # --- Test 1: SEC-04 Pre-Init Scripts Access ---

    @pytest.mark.warning
    @allure.story("SEC-04: Pre-init scripts directory access")
    @allure.title("SEC-04: Pre-init dir permissions and Permission denied in logs")
    @allure.description(
        "SEC-04: /docker-entrypoint-preinitdb.d/ has drwx------ (DEF-02). "
        "On K8s defect is visible in logs but non-fatal (pod still starts). "
        "Asserts ls -ld shows defective perms and logs show 'Permission denied'."
    )
    @allure.severity(allure.severity_level.MINOR)
    @allure.issue("docs/TEST_REPORT.md", name="TEST_REPORT – DEF-02")
    @allure.testcase("docs/TEST_PLAN.md", name="TEST_PLAN – SEC-04")
    def test_1_sec04_preinitdb_permission_denied_in_logs(
        self, helm_release, pod_name, k8s_client, container_name
    ):
        release_name, namespace = helm_release
        path = "/docker-entrypoint-preinitdb.d"
        path_label = "preinitdb.d/"

        print("\n[1/4] Resolving release, namespace, pod, container...")
        print(f"      release={release_name}, namespace={namespace}, pod={pod_name}, container={container_name}")

        print("\n[2/4] Waiting for pod readiness (readiness probe / pg_isready)...")
        ready = _wait_for_pod_ready(k8s_client, namespace, pod_name, timeout_sec=90)
        print(f"      Pod ready: {ready}")

        print(f"\n[3/4] Assert directory permissions: ls -ld {path} (SEC-04)...")
        _assert_hook_dir_permissions(
            namespace, pod_name, container_name, path, "SEC-04", path_label
        )

        print("\n[4/4] Assert logs contain 'Permission denied' for preinitdb.d (SEC-04)...")
        logs = _get_pod_logs(k8s_client, namespace, pod_name, container_name)
        _assert_logs_permission_denied_for_path(
            logs, "docker-entrypoint-preinitdb.d", "SEC-04", path_label
        )
        print("\n      Test 1 (SEC-04) passed.")

    # --- Test 2: SEC-03 Init Scripts Access ---

    @pytest.mark.warning
    @allure.story("SEC-03: Init scripts directory access")
    @allure.title("SEC-03: Init dir permissions and Permission denied in logs")
    @allure.description(
        "SEC-03: /docker-entrypoint-initdb.d/ has drwx------ (DEF-02). "
        "On K8s defect is visible in logs but non-fatal (pod still starts). "
        "Asserts ls -ld shows defective perms and logs show 'Permission denied'."
    )
    @allure.severity(allure.severity_level.MINOR)
    @allure.issue("docs/TEST_REPORT.md", name="TEST_REPORT – DEF-02")
    @allure.testcase("docs/TEST_PLAN.md", name="TEST_PLAN – SEC-03")
    def test_2_sec03_initdb_permission_denied_in_logs(
        self, helm_release, pod_name, k8s_client, container_name
    ):
        release_name, namespace = helm_release
        path = "/docker-entrypoint-initdb.d"
        path_label = "initdb.d/"

        print("\n[1/4] Resolving release, namespace, pod, container...")
        print(f"      release={release_name}, namespace={namespace}, pod={pod_name}, container={container_name}")

        print("\n[2/4] Waiting for pod readiness (readiness probe / pg_isready)...")
        ready = _wait_for_pod_ready(k8s_client, namespace, pod_name, timeout_sec=90)
        print(f"      Pod ready: {ready}")

        print(f"\n[3/4] Assert directory permissions: ls -ld {path} (SEC-03)...")
        _assert_hook_dir_permissions(
            namespace, pod_name, container_name, path, "SEC-03", path_label
        )

        print("\n[4/4] Assert logs contain 'Permission denied' for initdb.d (SEC-03)...")
        logs = _get_pod_logs(k8s_client, namespace, pod_name, container_name)
        _assert_logs_permission_denied_for_path(
            logs, "docker-entrypoint-initdb.d", "SEC-03", path_label
        )
        print("\n      Test 2 (SEC-03) passed.")

    # --- Test 3: SEC-02 Data Dir Permissions (masked by PVC on K8s) ---

    @pytest.mark.env_difference
    @allure.story("SEC-02: Data directory permissions (PVC masks DEF-01)")
    @allure.title("SEC-02: Data dir masked by PVC on K8s (DEF-01 not visible)")
    @allure.description(
        "SEC-02: /bitnami/postgresql has drwxr-x--- in the IMAGE (DEF-01). "
        "On K8s, PVC is mounted here with different permissions, masking the defect. "
        "Documents behavioral difference: Docker fails (container crashes), K8s passes (PVC masks DEF-01)."
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.issue("docs/TEST_REPORT.md", name="TEST_REPORT – DEF-01")
    @allure.testcase("docs/TEST_PLAN.md", name="TEST_PLAN – SEC-02")
    def test_3_sec02_data_dir_masked_by_pvc(
        self, helm_release, pod_name, k8s_client, container_name
    ):
        release_name, namespace = helm_release
        path = "/bitnami/postgresql"

        print("\n[1/3] Resolving release, namespace, pod, container...")
        print(f"      release={release_name}, namespace={namespace}, pod={pod_name}, container={container_name}")

        print("\n[2/3] Waiting for pod readiness (readiness probe / pg_isready)...")
        ready = _wait_for_pod_ready(k8s_client, namespace, pod_name, timeout_sec=90)
        print(f"      Pod ready: {ready}")

        print(f"\n[3/3] Check data dir permissions: ls -ld {path} (SEC-02)...")
        _assert_data_dir_masked_by_pvc(namespace, pod_name, container_name, path)

        print("\n      Test 3 (SEC-02) passed – PVC masked DEF-01, PostgreSQL running.")
