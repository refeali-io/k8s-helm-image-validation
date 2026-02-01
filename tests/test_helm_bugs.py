"""
Helm-based automated tests for the minimized PostgreSQL image (halex1985/postgresql:latest).
Reproduces DEF-01/DEF-02: permission denied and liveness failure.
"""
import time


def _report(what: str, expected: str, actual: str) -> None:
    """Print what is tested, expected, and actual for assignment clarity."""
    print(f"\n  What is tested: {what}")
    print(f"  Expected:       {expected}")
    print(f"  Actual:         {actual}")


def _get_pod_logs(k8s_client, namespace: str, pod_name: str, tail: int = 200) -> str:
    """Fetch logs from the primary container."""
    return k8s_client.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container="postgresql",
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


# Wait for liveness probe to fail and Unhealthy event to appear
EVENT_WAIT_SEC = 90


class TestHelmDefectiveImage:
    """Tests that reproduce known defects when deploying halex1985/postgresql via Bitnami Helm chart."""

    def test_1_pod_becomes_unhealthy_liveness_fails(
            self,
            helm_release,
            pod_name,
            k8s_client,
    ):
        """Test 1 (Primary): Pod gets Unhealthy event due to liveness probe failure (PostgreSQL never starts)."""
        release_name, namespace = helm_release
        what = "After deploy with defective image, pod gets Unhealthy event (Liveness probe failed)."
        expected = "At least one event with reason Unhealthy and message containing 'Liveness probe failed'."

        # Give time for liveness probe to fail
        time.sleep(EVENT_WAIT_SEC)

        events = _get_pod_events(k8s_client, namespace, pod_name)
        unhealthy_events = [
            e for e in events
            if e.reason == "Unhealthy" and "Liveness probe failed" in (e.message or "")
        ]
        actual = (
            f"Found {len(unhealthy_events)} Unhealthy/Liveness probe failed event(s)."
            if unhealthy_events
            else f"No Unhealthy event found. Events: {[(e.reason, e.message) for e in events]}"
        )
        _report(what, expected, actual)

        assert len(unhealthy_events) >= 1, f"Expected Unhealthy (Liveness probe failed) event. {actual}"

    def test_2_pod_logs_contain_permission_denied(
            self,
            helm_release,
            pod_name,
            k8s_client,
    ):
        """Test 2: Container logs contain 'Permission denied' (DEF-02)."""
        release_name, namespace = helm_release
        what = "Container logs show permission-denied errors from entrypoint."
        expected = "Logs contain the string 'Permission denied'."

        logs = _get_pod_logs(k8s_client, namespace, pod_name)
        has_perm_denied = "Permission denied" in logs
        actual = "Logs contain 'Permission denied'" if has_perm_denied else "Logs do not contain 'Permission denied'"
        _report(what, expected, actual)

        assert has_perm_denied, f"Expected 'Permission denied' in logs. Snippet: {logs[:500]}"

    def test_3_pod_logs_contain_cannot_create_data_dir(
            self,
            helm_release,
            pod_name,
            k8s_client,
    ):
        """Test 3: Container logs contain 'cannot create directory' for /bitnami/postgresql/data (DEF-01)."""
        release_name, namespace = helm_release
        what = "Container logs show failure to create data directory."
        expected = "Logs contain 'cannot create directory' and '/bitnami/postgresql/data'."

        logs = _get_pod_logs(k8s_client, namespace, pod_name)
        has_cannot_create = "cannot create directory" in logs and "/bitnami/postgresql/data" in logs
        actual = (
            "Logs contain 'cannot create directory' and '/bitnami/postgresql/data'"
            if has_cannot_create
            else "Logs do not contain expected strings"
        )
        _report(what, expected, actual)

        assert has_cannot_create, f"Expected 'cannot create directory' and '/bitnami/postgresql/data' in logs. Snippet: {logs[:500]}"

    def test_4_pod_never_reaches_ready(
            self,
            helm_release,
            pod_name,
            k8s_client,
    ):
        """Test 4: Pod never becomes Ready (readiness probe fails / PostgreSQL not up)."""
        release_name, namespace = helm_release
        what = "With defective image, pod never becomes Ready."
        expected = "After wait, pod Ready condition is not True."

        # Wait so readiness has had time to be evaluated
        time.sleep(30)
        ready = _is_pod_ready(k8s_client, namespace, pod_name)
        actual = f"Pod Ready = {ready} (expected False)."
        _report(what, expected, actual)

        assert not ready, f"Expected pod not Ready (defective image); got Ready=True."
