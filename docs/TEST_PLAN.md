# Test Plan: Minimized PostgreSQL Image Validation

## 1. Introduction

**Project:** Minimus Security – PostgreSQL Minimization
**Objective:** Validate the integrity of the minimized image (`halex1985/postgresql:latest`) and ensure strict backward compatibility with the official Bitnami Helm Chart.
**Note:** The image under test **intentionally contains defects**; the goal is to identify and document them.

**Scope:**

1.  **Manual Forensic Analysis (OCI):** Deep inspection of the image internals (Filesystem, OS, Users).

2.  **Automated Integration (Helm):** Full deployment validation via Kubernetes (covered in separate automation suite).

---

## 2. Manual Test Strategy (OCI)

**Methodology:** - Sanity Test

`docker run --rm --name minimus-test -e POSTGRESQL_PASSWORD=mysecretpassword halex1985/postgresql:latest`

Since the container crashes immediately upon startup, we will execute these tests by overriding the entrypoint

"Bypass & Inspect" Methodology

`docker run --rm -it --entrypoint /bin/sh halex1985/postgresql:latest`

Now inside the /bin/sh shell we will run the followers tests
### 2.1 detailed Test Cases

| ID | Test Name | Command to Execute | Expected Behavior (Success Criteria) |
| :--- | :--- | :--- | :--- |
| **IMG-01** | **OS Distribution Check** | `cat /etc/os-release` | Output should indicate **Debian** (or glibc-based OS). <br> *Reason: Bitnami scripts depend on glibc, not musl (Alpine).* |
| **IMG-02** | **Shell Compatibility** | `ls -l /bin/bash` | File **must exist**. <br> *Reason: Helm charts use `#!/bin/bash` shebangs.* |
| **IMG-03** | **Configuration Path** | `ls -d /opt/bitnami/postgresql/conf/conf.d` | Directory **must exist**. <br> *Reason: Helm mounts ConfigMaps to this specific path.* |
| **SEC-01** | **User Context (1001)** | `grep 1001 /etc/passwd` | User **postgres (UID 1001)** must exist. <br> *Reason: Container is configured to `runAsUser: 1001`.* |
| **SEC-02** | **Data Dir Permissions** | `ls -ld /bitnami/postgresql` | Owner must be **1001**, or if owner is root then group/others must allow write for UID 1001 (e.g. not `drwxr-x---`). <br> *Reason: Non-root user cannot write to root-owned directories on Bitnami distribution without group/other write access.* |
| **SEC-03** | **Init Scripts Access** | `ls -ld /docker-entrypoint-initdb.d/` | Directory must be readable/executable by UID 1001. |
| **SEC-04** | **Pre-Init Scripts Access** | `ls -ld /docker-entrypoint-preinitdb.d` | Directory must be readable/executable by the entrypoint user (UID 1001 or root during init). <br> *Reason: Entrypoint runs `find` on this path; "Permission denied" causes startup failure.* |

---

## 3. Automated Test Strategy (Helm)
**Methodology:** "Black-Box Testing"
We will use a Python automation suite (`tests/`) to reproduce deployment failures.

| ID | Scenario | Expected Behavior |
| :--- | :--- | :--- |
| **HLM-01** | **Standard Deployment** | `helm install` succeeds; Pod status: `Running`. |
| **HLM-02** | **PVC Write Access** | Application successfully initializes database files on the Persistent Volume. |
| **HLM-03** | **Liveness Probe** | Kubernetes health checks return `200 OK` (Container does not restart). |

---

## 4. Pass/Fail Criteria
* **FAIL:** If any **Manual Test** returns a result matching "Alpine", "Not Found", "Root Owner", or **restrictive permissions** (e.g. `drwxr-x---` on `/bitnami/postgresql`), the image is deemed incompatible.
* **FAIL:** If **Helm Deployment** enters `CrashLoopBackOff`.