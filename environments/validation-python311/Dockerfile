FROM python:3.11

# Repository-local build definition only. Live build/push/promotion is separately
# authorization-gated by #1332. No credentials, repository source, mutable Agent
# OS state, checkpoints, leases, or production data belong in this image.
WORKDIR /opt/agent-os-dependencies

COPY requirements-dev.txt ./requirements-dev.txt
COPY 08_Tooling/workflow-scheduler/requirements.txt ./workflow-scheduler-requirements.txt

RUN python -m pip install --no-cache-dir -r requirements-dev.txt \
    && python -m pip install --no-cache-dir -r workflow-scheduler-requirements.txt

# Editable repository-local packages intentionally remain task/runtime-local.
# Their source is not baked into the stable validation dependency image.
