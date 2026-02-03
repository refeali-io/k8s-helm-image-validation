# Test Report: Minimized PostgreSQL Image Validation

## Overview

| Item | Value |
|------|--------|
| **Reference image** | `registry-1.docker.io/bitnami/postgresql:latest` |
| **Image under test** | `docker.io/halex1985/postgresql:latest` |
| **Reference behavior** | Starts and initializes PostgreSQL successfully |
| **Image under test** | Fails during setup (intentional defects) |

---

## Part 1: Manual OCI Testing (Docker CLI)

### 1.1 Sanity Test — Container Startup

**Command executed:**

```bash
docker run --rm --name minimus-test -e POSTGRESQL_PASSWORD=mysecretpassword halex1985/postgresql:latest
```

**Result:** Container crashes immediately with permission errors:

```
postgresql 14:20:49.09 INFO  ==> ** Starting PostgreSQL setup **
+ /opt/bitnami/scripts/postgresql/setup.sh
postgresql 14:20:49.11 INFO  ==> Validating settings in POSTGRESQL_* env vars..
postgresql 14:20:49.12 WARN  ==> You set the environment variable ALLOW_EMPTY_PASSWORD=yes. For safety reasons, do not use this flag in a production environment.
postgresql 14:20:49.13 INFO  ==> Loading custom pre-init scripts...
find: '/docker-entrypoint-preinitdb.d/': Permission denied
postgresql 14:20:49.14 INFO  ==> Initializing PostgreSQL database...
mkdir: cannot create directory '/bitnami/postgresql/data': Permission denied
```

**Conclusion:** Sanity test **FAILED**. Proceeding to "Bypass & Inspect" methodology.

---

### 1.2 Bypass & Inspect — Forensic Analysis (Docker vs Kubernetes)

We run the same inspection commands in **two environments** to compare behavior:

**Docker (OCI):**
```bash
docker run --rm -it --entrypoint /bin/sh halex1985/postgresql:latest
```

**Kubernetes (Helm):**
```bash
kubectl exec -it -n minimus-test <pod-name> -c postgresql -- sh
```

#### Test Results: Docker vs Kubernetes Side-by-Side

| Test ID | Test Name | Command | Docker Result | K8s Result | Docker | K8s |
|---------|-----------|---------|---------------|------------|--------|-----|
| **IMG-01** | OS Distribution Check | `cat /etc/os-release` | `ID=minimos`, `NAME="MinimOS"`, `VERSION_ID="20241031"` | Same | **PASS** | **PASS** |
| **IMG-02** | Shell Compatibility | `ls -l /bin/bash` | `-rwxr-xr-x 1 root root 1544952` | Same | **PASS** | **PASS** |
| **IMG-03** | Configuration Path | `ls -d .../conf/conf.d` | Exists | Same | **PASS** | **PASS** |
| **SEC-01** | User Context (1001) | `grep 1001 /etc/passwd` | `postgresql:x:1001:0:...` | Same | **PASS** | **PASS** |
| **SEC-02** | Data Dir Permissions | `ls -ld /bitnami/postgresql` | `drwxr-x--- root root` | `drwxrwxrwx root root` (PVC) | **FAIL** | **PASS** |
| **SEC-03** | Init Scripts Access | `ls -ld /docker-entrypoint-initdb.d/` | `drwx------ root root` | Same | **FAIL** | **FAIL** |
| **SEC-04** | Pre-Init Scripts Access | `ls -ld /docker-entrypoint-preinitdb.d` | `drwx------ root root` | Same | **FAIL** | **FAIL** |

#### Key Observations

- **IMG-01 to SEC-01:** Identical in both environments — these come from the image itself.
- **SEC-02 (Data Dir):** **Different!**
  - **Docker:** Image filesystem shows `drwxr-x---` → UID 1001 cannot write → container crashes.
  - **K8s:** PVC is mounted on `/bitnami/postgresql` with `drwxrwxrwx` → UID 1001 can write → PostgreSQL starts.
- **SEC-03, SEC-04 (Hook Dirs):** Same in both (`drwx------`) — these are **not** mounted volumes, so the image defect is visible in both. Logs show `find: '...': Permission denied` in both environments.

---

## Part 2: Identified Defects

### DEF-01: Data Directory Not Writable by PostgreSQL User (Critical)

**Priority:** **P0 / Critical** — PostgreSQL cannot start; database is unusable.

**Description:** The main data directory (`/bitnami/postgresql`) is owned by Root, and the `postgresql` user (UID 1001) has no write permission to it.

**Evidence:**

```
drwxr-x--- 2 root root 4096 Dec 30 10:07 /bitnami/postgresql
```

- Mode `drwxr-x---`: Owner (root) has rwx, Group (root) has r-x, Others have **no access**.
- User `postgresql` (UID 1001) is in "others" category → cannot create `/bitnami/postgresql/data`.

**Impact:** The entrypoint script fails with `mkdir: cannot create directory '/bitnami/postgresql/data': Permission denied`.

**Suggested fix:** Set ownership to `1001:root` or mode to `drwxrwxr-x` (or add UID 1001 to root group with write access).

---

### DEF-02: Init Script Directories Locked to Root Only (Critical)

**Priority:** **P0 / Critical** — Entrypoint fails to scan for user scripts.

**Description:** The hook directories (`/docker-entrypoint-initdb.d/` and `/docker-entrypoint-preinitdb.d`) are locked to Root only with mode `drwx------`.

**Evidence:**

```
drwx------ 2 root root 4096 Jan  1  1970 /docker-entrypoint-initdb.d/
drwx------ 2 root root 4096 Jan  1  1970 /docker-entrypoint-preinitdb.d
```

- Mode `drwx------`: Only Root has any access; no read/execute for anyone else.

**Impact:** The entrypoint script runs `find` on `/docker-entrypoint-preinitdb.d/` and fails with `find: '/docker-entrypoint-preinitdb.d/': Permission denied`, causing startup failure.

**Suggested fix:** Set mode to at least `drwxr-xr-x` (755) or ensure the entrypoint user can read/execute these directories.

---

## Part 3: Reproduction Steps (OCI / Docker)

1. Pull the image once:
   ```bash
   docker pull docker.io/halex1985/postgresql:latest
   ```

2. Run the container with a password (observe crash):
   ```bash
   docker run --rm --name minimus-test -e POSTGRESQL_PASSWORD=mysecretpassword halex1985/postgresql:latest
   ```

3. Observe logs showing both defects:
   - `find: '/docker-entrypoint-preinitdb.d/': Permission denied` (DEF-02)
   - `mkdir: cannot create directory '/bitnami/postgresql/data': Permission denied` (DEF-01)

4. Bypass entrypoint to confirm permissions:
   ```bash
   docker run --rm -it --entrypoint /bin/sh halex1985/postgresql:latest
   ```
   Then inside the shell:
   ```bash
   ls -ld /bitnami/postgresql
   ls -ld /docker-entrypoint-initdb.d/
   ls -ld /docker-entrypoint-preinitdb.d
   ```

---

## Part 4: Manual Testing Summary (Docker vs Kubernetes)

| Test ID | Test Name | Docker | K8s | Defect | Notes |
|---------|-----------|--------|-----|--------|-------|
| **IMG-01** | OS Distribution Check | **PASS** | **PASS** | — | MinimOS in both |
| **IMG-02** | Shell Compatibility | **PASS** | **PASS** | — | `/bin/bash` exists |
| **IMG-03** | Configuration Path | **PASS** | **PASS** | — | `conf.d` exists |
| **SEC-01** | User Context (1001) | **PASS** | **PASS** | — | UID 1001 exists |
| **SEC-02** | Data Dir Permissions | **FAIL** | **PASS** | DEF-01 | K8s: PVC masks defect |
| **SEC-03** | Init Scripts Access | **FAIL** | **FAIL** | DEF-02 | `drwx------` in both |
| **SEC-04** | Pre-Init Scripts Access | **FAIL** | **FAIL** | DEF-02 | `drwx------` in both |

**Manual Testing: COMPLETED**

**Total Defects Found:** 2 (DEF-01, DEF-02)

- **DEF-01:** Causes crash on Docker; masked by PVC on K8s.
- **DEF-02:** Causes "Permission denied" error in logs on both Docker and K8s (non-fatal on K8s).

---

## Part 5: Helm / Kubernetes Testing

### 5.1 Deployment Command

```bash
helm install minimus-manual bitnami/postgresql \
  -f helm-values/postgresql-defective-image-values.yaml \
  -n minimus-test --create-namespace
```

### 5.2 Observed Behavior

| Aspect | Expected (based on Docker) | Actual (K8s) |
|--------|---------------------------|--------------|
| Container startup | Crash (Permission denied) | **Pod runs** — PostgreSQL starts |
| Data directory | Cannot create `/bitnami/postgresql/data` | **Created successfully** (PVC has `drwxrwxrwx`) |
| Hook dir errors in logs | `find: '/docker-entrypoint-preinitdb.d/': Permission denied` | **Same error in logs** |
| Init dir errors in logs | `find: '/docker-entrypoint-initdb.d/': Permission denied` | **Same error in logs** |
| PostgreSQL status | Never starts | **Starts and accepts connections** |

### 5.3 Root Cause of Difference

The Bitnami Helm chart mounts a **PersistentVolumeClaim (PVC)** on `/bitnami/postgresql`. Kubernetes (via `fsGroup` or default volume permissions) makes this mount world-writable (`drwxrwxrwx`), which **masks** the image defect (DEF-01).

However, the hook directories (`/docker-entrypoint-initdb.d/`, `/docker-entrypoint-preinitdb.d/`) are **not** mounted volumes — they come from the image. So DEF-02 still appears in the logs ("Permission denied" on `find`), but the entrypoint script treats this as non-fatal and continues.

### 5.4 Helm Testing Summary

| Test ID | Test Name | Docker | K8s | Notes |
|---------|-----------|--------|-----|-------|
| **SEC-02** | Data Dir Permissions | **FAIL** | **PASS** | PVC masks image defect |
| **SEC-03** | Init Scripts Access | **FAIL** | **FAIL** | Error in logs, non-fatal |
| **SEC-04** | Pre-Init Scripts Access | **FAIL** | **FAIL** | Error in logs, non-fatal |
| **HLM-01** | Pod Running | N/A | **PASS** | Pod runs (but with errors in logs) |
| **HLM-02** | PVC Write Access | N/A | **PASS** | Data dir created on PVC |
| **HLM-03** | Liveness Probe | N/A | **PASS** | PostgreSQL responds to `pg_isready` |

### 5.5 Conclusion

- **DEF-01 (Data Dir):** Masked on K8s by PVC; still causes crash on pure Docker.
- **DEF-02 (Hook Dirs):** Visible in logs on both Docker and K8s; non-fatal on K8s.
- **Automation:** The automated test suite (`tests/test_postgresql_bugs.py`) checks for "Permission denied" in logs (Test 2) — this **passes** on K8s. Tests that expect pod failure (Tests 1, 3, 4) will **fail** on K8s because the pod is healthy.

**Recommendation for Minimus:** The image defects are real and affect Docker deployments. On K8s, DEF-01 is masked by PVC but DEF-02 is still present (logs show errors). The image should be fixed for both environments to ensure clean logs and consistent behavior.
