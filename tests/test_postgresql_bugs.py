"""
Helm-based automated tests for the minimized PostgreSQL image.
Validates DEF-02: hook directory permission denied errors visible in container logs.

Note on K8s vs Docker behavior:
- On Docker: Pod crashes (DEF-01 data dir + DEF-02 hook dir both fail)
- On K8s: Pod starts (PVC masks DEF-01), but DEF-02 still shows in logs

These tests validate defects that are visible on Kubernetes.

Usage:
    pytest --kube-context=docker-desktop
    pytest tests/test_postgresql_bugs.py::TestPostgreSQLBugs::test_1_sec02_preinitdb_permission_denied_in_logs
"""
import time

import pytest


# =============================================================================
# HELPERS
# =============================================================================

def _report(what: str, expected: str, actual: str) -> None:
    """Print what is tested, expected, and actual for assignment clarity."""
    print(f"\n  What is tested: {what}")
    print(f"  Expected:       {expected}")
    print(f"  Actual:         {actual}")


def _get_pod_logs(k8s_client, namespace: str, pod_name: str, container: str, tail: int = 200) -> str:
    """Fetch logs from the specified container."""
    return k8s_client.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container=container,
        tail_lines=tail,
    )


def _get_pod_events(k8s_client, namespace: str, pod_name: str):
    """List events involving the pod (involvedObject)."""
    events = k8s_client.list_namespaced_event(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name}",
    )
    return events.items


def _is_pod_ready(k8s_client, namespace: str, pod_name: str) -> bool:
    """Return True if pod Ready condition status is True."""
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=namespace)
    for c in pod.status.conditions or []:
        if c.type == "Ready":
            return c.status == "True"
    return False


def _wait_for_pod_ready(k8s_client, namespace: str, pod_name: str, timeout_sec: int = 90, poll_sec: float = 2.0) -> bool:
    """Wait for pod Ready condition (readiness probe). Returns True when ready."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _is_pod_ready(k8s_client, namespace, pod_name):
            return True
        time.sleep(poll_sec)
    return False


# =============================================================================
# TEST CLASS
# =============================================================================

@pytest.mark.helm
@pytest.mark.defect
class TestPostgreSQLBugs:
    """
    Tests that reproduce known defects when deploying the defective PostgreSQL image
    (halex1985/postgresql:latest) via the Bitnami Helm chart.

    SEC-02 / DEF-02: Hook directory permissions (/docker-entrypoint-preinitdb.d/)
    are drwx------ which causes "Permission denied" errors in container logs.
    
    This defect is visible on Kubernetes even though the pod starts successfully
    (because the PVC masks DEF-01 for the data directory).
    """

    # =========================================================================
    # TEST CONFIGURATION (read by conftest.py fixtures)
    # =========================================================================
    CHART = "bitnami/postgresql"
    VALUES_FILE = "helm-values/postgresql-defective-image-values.yaml"
    CONTAINER = "postgresql"
    NAMESPACE = "minimus-test"
    RELEASE_PREFIX = "pg-test"

    # =========================================================================
    # TESTS
    # =========================================================================

    def test_1_sec02_preinitdb_permission_denied_in_logs(
        self,
        helm_release,
        pod_name,
        k8s_client,
        container_name,
    ):
        """
        Test 1 (SEC-02): Container logs contain 'Permission denied' for hook directory.
        
        Validates DEF-02: /docker-entrypoint-preinitdb.d/ has drwx------ permissions,
        causing 'find: Permission denied' when entrypoint tries to scan it.
        
        This test passes on K8s because the defect is visible in logs even though
        the pod starts successfully (PVC masks DEF-01 but not DEF-02).
        """
        print("\n[STEP 1] Resolving release and namespace from helm_release fixture...")
        release_name, namespace = helm_release
        print(f"         release_name={release_name}, namespace={namespace}")

        print("\n[STEP 2] Resolving pod and container...")
        print(f"         pod_name={pod_name}, container_name={container_name}")

        print("\n[STEP 3] Waiting for pod readiness (readiness probe / pg_isready)...")
        ready = _wait_for_pod_ready(k8s_client, namespace, pod_name, timeout_sec=90)
        print(f"         Pod ready: {ready}")

        print("\n[STEP 4] Fetching container logs from Kubernetes API...")
        logs = _get_pod_logs(k8s_client, namespace, pod_name, container_name)
        print(f"         Retrieved {len(logs)} characters of log output.")

        print("\n[STEP 5] Checking logs for 'Permission denied' for /docker-entrypoint-preinitdb.d/ (DEF-02)...")
        has_preinitdb_perm_denied = "Permission denied" in logs and "docker-entrypoint-preinitdb.d" in logs

        what = "Container logs show 'Permission denied' for /docker-entrypoint-preinitdb.d/ (DEF-02: hook dir)."
        expected = "Logs contain 'Permission denied' for preinitdb.d/ (find on hook dir)."

        if has_preinitdb_perm_denied:
            perm_lines = [line for line in logs.split('\n') if 'Permission denied' in line and 'preinitdb' in line]
            actual = f"Logs contain 'Permission denied' for preinitdb.d/: {perm_lines[0].strip() if perm_lines else '(found)'}"
            print(f"         FOUND: {perm_lines[0].strip() if perm_lines else 'Permission denied (preinitdb.d)'}")
        else:
            actual = f"Logs do NOT contain expected preinitdb.d/ permission error. Snippet: {logs[:300]}"
            print(f"         NOT FOUND. First 200 chars: {logs[:200]}")

        has_perm_denied = has_preinitdb_perm_denied

        print("\n[STEP 6] Reporting result...")
        _report(what, expected, actual)

        assert has_perm_denied, f"Expected 'Permission denied' for preinitdb.d/ in logs (DEF-02). Snippet: {logs[:500]}"
        print("\n[STEP 7] Assert passed. Test complete.")

    # def test_2_logs_contain_preinitdb_permission_error(
    #     self,
    #     helm_release,
    #     pod_name,
    #     k8s_client,
    #     container_name,
    # ):
    #     """
    #     Test 2 (SEC-02 specific): Logs show permission error for /docker-entrypoint-preinitdb.d/.
    #     
    #     More specific check - validates the exact path that has the permission issue.
    #     """
    #     release_name, namespace = helm_release
    #     what = "Container logs show permission error for /docker-entrypoint-preinitdb.d/."
    #     expected = "Logs contain 'docker-entrypoint-preinitdb.d' and 'Permission denied'."

    #     logs = _get_pod_logs(k8s_client, namespace, pod_name, container_name)
    #     has_preinitdb_error = "docker-entrypoint-preinitdb.d" in logs and "Permission denied" in logs
    #     
    #     actual = (
    #         "Logs contain preinitdb.d permission error"
    #         if has_preinitdb_error
    #         else f"Expected pattern not found. Log snippet: {logs[:300]}"
    #     )
    #     _report(what, expected, actual)

    #     assert has_preinitdb_error, f"Expected preinitdb.d permission error in logs. Snippet: {logs[:500]}"

    # def test_3_pod_started_successfully(
    #     self,
    #     helm_release,
    #     pod_name,
    #     k8s_client,
    # ):
    #     """
    #     Test 3: Pod starts successfully on K8s (PVC masks DEF-01).
    #     
    #     This documents the environmental difference: on K8s with PVC, the pod
    #     starts even though the image has defects. This is expected behavior
    #     that we want to document - the defect is masked, not fixed.
    #     """
    #     release_name, namespace = helm_release
    #     what = "Pod starts successfully on K8s (PVC masks DEF-01 data dir issue)."
    #     expected = "Pod is in Running phase."

    #     pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=namespace)
    #     phase = pod.status.phase
    #     actual = f"Pod phase = {phase}."
    #     _report(what, expected, actual)

    #     assert phase == "Running", f"Expected pod Running; got {phase}."

    # def test_4_postgresql_ready_despite_image_defects(
    #     self,
    #     helm_release,
    #     pod_name,
    #     k8s_client,
    # ):
    #     """
    #     Test 4: PostgreSQL becomes Ready on K8s despite image defects.
    #     
    #     Documents that on K8s the pod becomes Ready because PVC masks DEF-01.
    #     The image still has defects (visible in logs), but they don't prevent startup.
    #     """
    #     release_name, namespace = helm_release
    #     what = "Pod becomes Ready on K8s (defects masked by PVC)."
    #     expected = "Pod Ready condition is True."

    #     # Wait for readiness
    #     time.sleep(30)
    #     ready = _is_pod_ready(k8s_client, namespace, pod_name)
    #     actual = f"Pod Ready = {ready}."
    #     _report(what, expected, actual)

    #     assert ready, f"Expected pod Ready=True on K8s; got {ready}."
