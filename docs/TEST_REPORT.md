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

### 1.2 Bypass & Inspect — Forensic Analysis

Since the container crashes on startup, we override the entrypoint to inspect the image internals:

```bash
docker run --rm -it --entrypoint /bin/sh halex1985/postgresql:latest
```

#### Test Results

| Test ID | Test Name | Command | Result | Status |
|---------|-----------|---------|--------|--------|
| **IMG-01** | OS Distribution Check | `cat /etc/os-release` | `ID=minimos`, `NAME="MinimOS"`, `VERSION_ID="20241031"` | **PASS** (MinimOS is acceptable) |
| **IMG-02** | Shell Compatibility | `ls -l /bin/bash` | `-rwxr-xr-x 1 root root 1544952 Dec 17 12:25 /bin/bash` | **PASS** |
| **IMG-03** | Configuration Path | `ls -d /opt/bitnami/postgresql/conf/conf.d` | `/opt/bitnami/postgresql/conf/conf.d` (exists) | **PASS** |
| **SEC-01** | User Context (1001) | `grep 1001 /etc/passwd` | `postgresql:x:1001:0:Account created by Minimus:/home/postgresql:/bin/sh` | **PASS** |
| **SEC-02** | Data Dir Permissions | `ls -ld /bitnami/postgresql` | `drwxr-x--- 2 root root 4096 Dec 30 10:07` | **FAIL** |
| **SEC-03** | Init Scripts Access | `ls -ld /docker-entrypoint-initdb.d/` | `drwx------ 2 root root 4096 Jan  1  1970` | **FAIL** |
| **SEC-04** | Pre-Init Scripts Access | `ls -ld /docker-entrypoint-preinitdb.d` | `drwx------ 2 root root 4096 Jan  1  1970` | **FAIL** |

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

## Part 4: Manual OCI Testing Summary

| Test ID | Test Name | Status | Defect |
|---------|-----------|--------|--------|
| **IMG-01** | OS Distribution Check | **PASS** | — |
| **IMG-02** | Shell Compatibility | **PASS** | — |
| **IMG-03** | Configuration Path | **PASS** | — |
| **SEC-01** | User Context (1001) | **PASS** | — |
| **SEC-02** | Data Dir Permissions | **FAIL** | DEF-01 |
| **SEC-03** | Init Scripts Access | **FAIL** | DEF-02 |
| **SEC-04** | Pre-Init Scripts Access | **FAIL** | DEF-02 |

**Manual OCI Testing: COMPLETED**

**Total Defects Found:** 2 (DEF-01, DEF-02)

---

## Part 5: Helm Testing

*Pending — will be covered by automated test suite (`tests/test_helm_bugs.py`).*

Expected outcome: Deployment will enter `CrashLoopBackOff` due to the same permission defects (DEF-01, DEF-02).
