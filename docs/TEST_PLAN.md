# Test Plan: Minimized PostgreSQL Image Validation

## 1. Introduction

**Project:** Minimus Security – PostgreSQL Minimization
**Objective:** Validate the integrity of the minimized image (`halex1985/postgresql:latest`) and ensure strict backward compatibility with the official Bitnami Helm Chart.
**Note:** The image under test **intentionally contains defects**; the goal is to identify and document them.

**Scope:**

1.  **Manual Forensic Analysis (OCI):** Deep inspection of the image internals (Filesystem, OS, Users).

2.  **Automated Integration (Helm):** Full deployment validation via Kubernetes (covered in separate automation suite).

---

## 2. Manual Test Strategy

The **"Bypass & Inspect"** methodology allows deep inspection of the image internals even when the container crashes on startup. We run the same tests in **two environments** to compare behavior:

1. **Docker (OCI):** Pure image filesystem — exposes defects in the image itself.
2. **Kubernetes (Helm):** Image + mounted volumes — shows how K8s infrastructure can mask or expose different issues.

---

### 2.1 Docker (OCI) — Bypass & Inspect

**Sanity Test (container crashes):**

```bash
docker run --rm --name minimus-test -e POSTGRESQL_PASSWORD=mysecretpassword halex1985/postgresql:latest
```

Since the container crashes immediately upon startup, we override the entrypoint to inspect the image:

```bash
docker run --rm -it --entrypoint /bin/sh halex1985/postgresql:latest
```

Now inside the `/bin/sh` shell we run the test cases below.

---

### 2.2 Kubernetes (Helm) — Bypass & Inspect

**Deploy the chart (pod may or may not crash depending on volume permissions):**

```bash
helm install minimus-manual bitnami/postgresql \
  -f helm-values/defective-image.yaml \
  -n minimus-test --create-namespace
```

**Access the pod shell to run the same tests:**

```bash
kubectl exec -it -n minimus-test <pod-name> -c postgresql -- sh
```

Or run commands directly:

```bash
kubectl exec -n minimus-test <pod-name> -c postgresql -- ls -ld /bitnami/postgresql
```

---

### 2.3 Test Cases (Docker vs Kubernetes)

The same commands are executed in both environments. The table shows the command, expected behavior, and notes on where results may differ.

| ID | Test Name | Command to Execute | Expected (Docker) | Expected (K8s) | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **IMG-01** | OS Distribution Check | `cat /etc/os-release` | MinimOS (or Debian-based) | Same | Image OS is identical in both. |
| **IMG-02** | Shell Compatibility | `ls -l /bin/bash` | File must exist | Same | Image binaries are identical. |
| **IMG-03** | Configuration Path | `ls -d /opt/bitnami/postgresql/conf/conf.d` | Directory must exist | Same | Image paths are identical. |
| **SEC-01** | User Context (1001) | `grep 1001 /etc/passwd` | User postgresql (UID 1001) must exist | Same | Image user config is identical. |
| **SEC-02** | Data Dir Permissions | `ls -ld /bitnami/postgresql` | `drwxr-x---` (FAIL: others have no access) | **May differ**: K8s mounts a PVC here, often with `drwxrwxrwx` | **Key difference**: volume permissions can mask the image defect. |
| **SEC-03** | Init Scripts Access | `ls -ld /docker-entrypoint-initdb.d/` | `drwx------` (FAIL: others have no access) | Same (`drwx------`) | Hook dirs are from the image, not volumes. |
| **SEC-04** | Pre-Init Scripts Access | `ls -ld /docker-entrypoint-preinitdb.d` | `drwx------` (FAIL: others have no access) | Same (`drwx------`) | Entrypoint runs `find` and gets "Permission denied" in both. |

**Key insight:** SEC-02 (data directory) behaves differently because Kubernetes mounts a **PersistentVolume** on `/bitnami/postgresql`. The image defect (`drwxr-x---`) is masked by the volume's permissions. However, SEC-03 and SEC-04 (hook directories) are **not** mounted, so the defect persists in both environments.

---

## 3. Automated Test Strategy (Helm)

**Methodology:** "Black-Box Testing"

We use a Python automation suite (`tests/test_helm_bugs.py`) to deploy the Bitnami PostgreSQL Helm chart with the defective image and validate behavior.

### 3.1 Automated Test Cases

| ID | Scenario | What is Tested | Expected (if defects present) |
| :--- | :--- | :--- | :--- |
| **Test 1** | Unhealthy / Liveness Probe | Pod events contain "Unhealthy" with "Liveness probe failed" | Pass if defect causes crash |
| **Test 2** | Logs: Permission Denied | Container logs contain `Permission denied` | **Pass** (DEF-02 visible in logs) |
| **Test 3** | Logs: Cannot Create Data Dir | Logs contain `cannot create directory '/bitnami/postgresql/data'` | Pass if DEF-01 causes crash |
| **Test 4** | Pod Not Ready | Pod Ready condition is not True | Pass if PostgreSQL fails to start |

### 3.2 Environment-Dependent Results

| Test | Docker (OCI) | Kubernetes (Helm) | Reason |
| :--- | :--- | :--- | :--- |
| **Test 1** (Unhealthy) | Container exits (no events) | **May PASS or FAIL** — depends on whether PVC masks DEF-01 | PVC often has `drwxrwxrwx` |
| **Test 2** (Permission Denied) | Visible in logs | **PASS** — same error in logs | Hook dirs are not volumes |
| **Test 3** (Cannot Create Dir) | Visible in logs | **FAIL** — data dir created on PVC | PVC masks DEF-01 |
| **Test 4** (Pod Not Ready) | Container exits | **FAIL** — pod becomes Ready | PostgreSQL starts on K8s |

**Key insight:** Test 2 is the most reliable cross-environment test because DEF-02 (hook dir permissions) is not masked by K8s volumes.

---

## 4. Pass/Fail Criteria

### Manual Testing (Bypass & Inspect)
* **FAIL:** If any test returns "Not Found", "Root Owner", or **restrictive permissions** (e.g. `drwxr-x---` on `/bitnami/postgresql` or `drwx------` on hook dirs), the image has defects.
* **Note:** On K8s, SEC-02 may show different permissions due to PVC mount — inspect the **image** (Docker) to see the true defect.

### Automated Testing (Helm)
* **PASS (defect reproduced):** Test 2 passes (logs contain "Permission denied") → DEF-02 confirmed.
* **Environment-dependent:** Tests 1, 3, 4 may fail on K8s if PVC masks DEF-01; they confirm DEF-01 on pure Docker.
* **FAIL (no defect):** If Test 2 fails (no "Permission denied" in logs), the defect may be fixed or the image is different.