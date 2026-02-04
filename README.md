# Minimus Image Validation Framework

Generic Helm-based test infrastructure for validating minimized container images. Currently configured for PostgreSQL; extensible to Redis, MongoDB, or any Bitnami chart.

## Deliverables

| Deliverable | Location |
|-------------|----------|
| Test Plan | [docs/TEST_PLAN.md](docs/TEST_PLAN.md) |
| Test Report | [docs/TEST_REPORT.md](docs/TEST_REPORT.md) |
| Automation (Helm) | [tests/test_postgresql_bugs.py](tests/test_postgresql_bugs.py) |
| Run Instructions | This README |

## Project Structure

```
minimus-assignment/
├── .github/workflows/
│   └── run-tests.yml               # CI: Kind cluster + pytest
├── helm-values/                    # Values files (external data)
│   └── postgresql-defective-image-values.yaml
├── tests/
│   ├── conftest.py                 # Generic fixtures (any chart)
│   └── test_postgresql_bugs.py     # PostgreSQL-specific tests
├── docs/
│   ├── TEST_PLAN.md
│   └── TEST_REPORT.md
├── pytest.ini                      # Pytest configuration
└── requirements.txt
```

## Design

Each test class defines its own configuration as class attributes:

```python
class TestPostgreSQLBugs:
    CHART = "bitnami/postgresql"
    VALUES_FILE = "helm-values/postgresql-defective-image-values.yaml"
    CONTAINER = "postgresql"
    NAMESPACE = "minimus-test"
    RELEASE_PREFIX = "pg-test"

    def test_1_pod_becomes_unhealthy(self, helm_release, pod_name, k8s_client):
        ...
```

The only CLI flag is `--kube-context` to select which Kubernetes cluster to use (e.g. AWS EKS).

### Architecture

The diagram below is in [Mermaid](https://mermaid.js.org/) format. **`flowchart TB`** means "flowchart, top-to-bottom". On GitHub (and in editors with Mermaid support) it renders as a picture; in plain text you see the source.

```mermaid
flowchart TB
    subgraph cli [CLI]
        kubeContext["--kube-context optional"]
    end

    subgraph pytest [Pytest]
        subgraph conftest [conftest.py]
            k8sClient[k8s_client]
            helmRelease[helm_release]
            podName[pod_name]
        end
        subgraph testClass [Test Class]
            classAttrs["CHART, VALUES_FILE, CONTAINER, NAMESPACE"]
            testMethods["test_1, test_2, test_3..."]
        end
    end

    subgraph k8s [Kubernetes - Kind local/CI]
        namespace[Namespace minimus-test]
        pod[Pod under test]
    end

    kubeContext --> k8sClient
    classAttrs --> helmRelease
    helmRelease --> testMethods
    k8sClient --> helmRelease
    podName --> testMethods
    k8sClient --> k8s
    helmRelease --> k8s
```

*Flow: CLI context → k8s client; test class config → helm_release → tests; both k8s_client and helm_release talk to the Kubernetes cluster (Kind for local/CI). On scaling, the cluster will be raised on AWS (e.g. EKS).*

## Prerequisites

- **Kubernetes:** Local cluster (Docker Desktop with Kubernetes, Minikube, or Kind).
- **CLI:** `kubectl` and `helm` v3 in PATH; kubeconfig pointing at the cluster.
- **Python:** 3.9+

## Setup

1. **Create and activate a virtual environment (recommended)**

   ```bash
   python -m venv venv
   # Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # Windows (cmd) or Linux/macOS:
   # venv\Scripts\activate  (Windows)   or   source venv/bin/activate  (Linux/macOS)
   ```

2. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Add Bitnami Helm repo**

   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm repo update
   ```

4. **Ensure cluster is running**

   ```bash
   kubectl cluster-info
   ```

## Run the Test Suite

### Basic Usage

```bash
# Run all tests (uses config from each test class)
pytest

# Run with explicit Kubernetes context
pytest --kube-context=minimus-test

# Run only PostgreSQL tests
pytest tests/test_postgresql_bugs.py --kube-context=docker-desktop
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--kube-context` | (none) | Kubernetes context to use (e.g. `docker-desktop`, `minimus-test`) |

### Setting the Kubernetes context (important)

The cluster you run against depends on your **current kubectl context**. On a new or shared env, the default context may be wrong. Set it **before** tests run:

```bash
# Option 1: Set context via pytest (recommended for automation)
pytest --kube-context=minimus-test

# Option 2: Set context in the shell first, then run pytest
kubectl config use-context minimus-test
pytest
```

With `--kube-context`, the framework runs `kubectl config use-context <name>` once at session start, before any Helm or Kubernetes API calls.

**Allure:** Pytest is configured in `pytest.ini` to write Allure results to `allure-results/` (`--alluredir=allure-results --clean-alluredir`). In CI, results are uploaded and the report is published to GitHub Pages. Locally, install the [Allure CLI](https://allurereport.org/docs/getting-started/installation/) and run `allure serve allure-results` after `pytest` to view the report in the browser.

### Kubernetes probes (nice to have for testing)

Tests wait for **pod Ready** (readiness probe). It helps to know how probes interact:

- **Liveness** and **readiness** run **in parallel** from container start — liveness does *not* wait for readiness to succeed. A slow-starting container can be killed by liveness before it ever becomes ready.
- **Startup probe**: if defined, *all other probes are disabled* until the startup probe succeeds. Only then do liveness and readiness start. Use it for slow-starting apps so liveness does not kill the container during startup.

| Probe       | Purpose                    | On failure              |
|------------|-----------------------------|-------------------------|
| liveness   | Is the container running?   | Kubelet kills container |
| readiness  | Ready to receive traffic?   | Pod removed from Service endpoints |
| startup    | Has the app started?        | Kubelet kills container; other probes disabled until it succeeds |

[Kubernetes docs: Configure Liveness, Readiness and Startup Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).

## Environment Options

### Locally (Docker Desktop Kubernetes)

1. **Enable Kubernetes in Docker Desktop**: Settings -> Kubernetes -> Enable Kubernetes -> Apply.

2. **Run tests**:

   ```bash
   pytest --kube-context=docker-desktop
   ```

### GitHub Actions (CI)

The pipeline [.github/workflows/run-tests.yml](.github/workflows/run-tests.yml) runs the same tests in CI using a **Kind** (Kubernetes in Docker) cluster, then publishes an **Allure** report to **GitHub Pages**. No AWS or EKS.

**Triggers:** Push or pull request to **main** (excluding `README.md`-only changes), or manual **workflow_dispatch**.

**Job 1 – Run QA Tests**

1. **Checkout** — repository is cloned on a fresh Ubuntu runner (Docker is already installed).
2. **Create Kind cluster** — [helm/kind-action](https://github.com/marketplace/actions/kind-cluster) creates a cluster with a fixed name (`KIND_CLUSTER_NAME`, default `minimus-test`). The kubeconfig context is `kind-<name>` (e.g. `kind-minimus-test`).
3. **Python & deps** — virtualenv and `pip install -r requirements.txt` (includes `allure-pytest`).
4. **Helm** — Helm CLI is installed; Bitnami repo is added.
5. **Run tests** — `pytest --kube-context=kind-<name>` runs against the Kind cluster. Pytest is configured in `pytest.ini` to write Allure data to `allure-results/` (`--alluredir=allure-results --clean-alluredir`). The test class installs the chart, runs assertions, and uninstalls.
6. **Upload Allure results** — the `allure-results/` directory is uploaded as an artifact (`if: always()` so it runs even if tests fail). Retention: 3 days.

**Job 2 – Deploy Allure Report to Pages** (runs after the test job, `if: always()`)

1. **Checkout** (with `fetch-depth: 0` for history).
2. **Download Allure results** — artifact from the test job.
3. **Install Allure CLI** — Java + [Allure 2.35.1](https://github.com/allure-framework/allure2/releases) so we can generate the HTML report.
4. **Restore history from gh-pages** — if the `gh-pages` branch already has a `history/` directory, it is copied into `allure-results/history` so the new report keeps trend history.
5. **Generate Allure Report** — `allure generate allure-results --clean -o allure-report`.
6. **Deploy to GitHub Pages** — [peaceiris/actions-gh-pages](https://github.com/peaceiris/actions-gh-pages) publishes `./allure-report` to the **gh-pages** branch. The report is then available at `https://<owner>.github.io/<repo>/`.
7. **Comment PR with Allure Report link** — on `pull_request` events, a comment is added to the PR with the report URL.
8. **Add Action Summary** — the run summary in the Actions tab includes the report link.

**One-time setup:** In the repository **Settings → Pages**, set **Source** to “Deploy from a branch” and choose branch **gh-pages** (folder `/ (root)`). The first successful run of the deploy job will create the branch and the report URL.

**To change the cluster name:** set the `KIND_CLUSTER_NAME` env var at the top of the workflow. The same value is used for the Kind cluster and for `--kube-context=kind-$KIND_CLUSTER_NAME`.

**Allure locally:** To generate and view the report on your machine, install the [Allure CLI](https://allurereport.org/docs/getting-started/installation/) (requires Java), then run `pytest` and `allure serve allure-results`.

## Tests (PostgreSQL)

| Test | What is tested | Expected |
|------|----------------|----------|
| **Test 1 (SEC-04)** | Pre-init scripts dir `/docker-entrypoint-preinitdb.d` | `ls -ld` shows drwx------; logs contain "Permission denied" for preinitdb.d |
| **Test 2 (SEC-03)** | Init scripts dir `/docker-entrypoint-initdb.d` | `ls -ld` shows drwx------; logs contain "Permission denied" for initdb.d |
| **Test 3 (SEC-02)** | Data dir `/bitnami/postgresql` | Documents Docker vs K8s: PVC masks DEF-01 (permissions NOT drwxr-x--- on K8s) |

## Adding New Tests (e.g., Redis)

Create a new test file with its own class attributes:

```python
# tests/test_redis_bugs.py
class TestRedisBugs:
    CHART = "bitnami/redis"
    VALUES_FILE = "helm-values/redis-defective-image-values.yaml"
    CONTAINER = "redis"
    NAMESPACE = "minimus-test"
    RELEASE_PREFIX = "redis-test"

    def test_1_redis_specific_defect(self, helm_release, pod_name, k8s_client):
        ...
```

No changes to `conftest.py` needed.

## Reference

- **Reference image:** `registry-1.docker.io/bitnami/postgresql:latest`
- **Image under test:** `docker.io/halex1985/postgresql:latest`
