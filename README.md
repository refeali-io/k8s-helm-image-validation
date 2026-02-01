# Minimus PostgreSQL Image – Assignment

Test suite for the minimized PostgreSQL image (`halex1985/postgresql:latest`) deployed via the Bitnami PostgreSQL Helm chart. The image intentionally contains defects; the automation reproduces them (DEF-01, DEF-02).

## Deliverables

| Deliverable | Location |
|-------------|----------|
| Test Plan | [docs/TEST_PLAN.md](docs/TEST_PLAN.md) |
| Test Report | [docs/TEST_REPORT.md](docs/TEST_REPORT.md) |
| Automation (Helm) | [tests/test_helm_bugs.py](tests/test_helm_bugs.py) |
| Run Instructions | This README |

## Prerequisites

- **Kubernetes:** Local cluster (Docker Desktop with Kubernetes, Minikube, or Kind).
- **CLI:** `kubectl` and `helm` v3 in PATH; kubeconfig pointing at the cluster.
- **Python:** 3.9+ (automation is intended to run in a Linux environment; development on Windows with Docker Desktop K8s is supported).

## Setup

1. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Add Bitnami Helm repo**

   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm repo update
   ```

3. **Ensure cluster is running**

   ```bash
   kubectl cluster-info
   ```

## Run the test suite

### Option A: Locally (Docker Desktop Kubernetes)

1. **Enable Kubernetes in Docker Desktop** (if not already): Settings → Kubernetes → Enable Kubernetes → Apply.

2. **Use the Docker Desktop context** so the tests run against your local cluster:

   ```bash
   kubectl config use-context docker-desktop
   kubectl cluster-info
   kubectl get nodes
   ```

3. **From the repository root**, run:

   ```bash
   pytest tests/test_helm_bugs.py -v -s
   ```

   The suite will create namespace `minimus-test`, install the chart there, run the four tests, then uninstall the release. Namespace `minimus-test` may remain (empty) after the run; you can delete it with `kubectl delete namespace minimus-test` if you like.

### Option B: AWS (EKS cluster)

1. **Point kubectl at your EKS cluster** (replace `<REGION>` with your cluster region, e.g. `us-east-1`):

   ```bash
   aws eks update-kubeconfig --region <REGION> --name minimus-assignment
   kubectl config use-context <CONTEXT_NAME>   # optional if only one context
   kubectl get nodes
   ```

2. **From the repository root**, run the same command:

   ```bash
   pytest tests/test_helm_bugs.py -v -s
   ```

---

- **`-v`** — Verbose test names.
- **`-s`** — Show stdout (What is tested / Expected / Actual for each test).

The suite will:

1. Install the Bitnami PostgreSQL chart with the defective image (`halex1985/postgresql:latest`) in namespace `minimus-test`.
2. Run four tests that reproduce DEF-01/DEF-02 (Unhealthy/liveness, logs “Permission denied”, logs “cannot create directory”, pod not Ready).
3. Uninstall the release after the tests.

**Note:** The first test waits ~90 seconds for the liveness probe to fail; total run time is about 2–3 minutes.

## Tests (summary)

| Test | What is tested | Expected |
|------|----------------|----------|
| **Test 1** | Pod gets Unhealthy event | Liveness probe failed (PostgreSQL never starts) |
| **Test 2** | Container logs | Contains “Permission denied” |
| **Test 3** | Container logs | Contains “cannot create directory” and “/bitnami/postgresql/data” |
| **Test 4** | Pod Ready condition | Pod never becomes Ready |

## Reference

- **Reference image:** `registry-1.docker.io/bitnami/postgresql:latest`
- **Image under test:** `docker.io/halex1985/postgresql:latest`
