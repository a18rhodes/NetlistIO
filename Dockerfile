ARG WORKDIR=/app
# CUDA version tag used to select the correct PyTorch wheel index.
# Override at build time: docker build --build-arg TORCH_CUDA_TAG=cu118 .
# Set to "cpu" to produce a CPU-only image.
ARG TORCH_CUDA_TAG=cu124
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_HOME="/opt/poetry"
ENV PATH="$POETRY_HOME/bin:$PATH"
RUN apt-get update && apt-get install -y \
    curl \
    git \
    vim \
    build-essential \
    graphviz \
    libgomp1 \
    sudo \
    && rm -rf /var/lib/apt/lists/*
ARG WORKDIR
WORKDIR ${WORKDIR}
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV POETRY_VIRTUALENVS_IN_PROJECT=false
ENV POETRY_VIRTUALENVS_PATH=/opt/poetry-venvs
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

FROM base AS dependencies
# Re-declare so the ARG is visible in this stage.
ARG TORCH_CUDA_TAG=cu124
COPY pyproject.toml poetry.lock README.md ./
RUN poetry lock
RUN poetry install --no-root --no-interaction
# PyTorch wheels live at a custom index that Poetry cannot target per-package.
# Install into the poetry venv directly after it is created.
RUN poetry run pip install --no-cache-dir \
    torch --index-url "https://download.pytorch.org/whl/${TORCH_CUDA_TAG}" \
    && poetry run pip install --no-cache-dir torch_geometric
# Stable symlink so the interpreter path is predictable regardless of the
# hash Poetry embeds in the venv directory name.
RUN ln -s "$(poetry env info --path)" /opt/venv

FROM dependencies AS development
COPY . .
RUN poetry lock && poetry install --only-root --no-interaction
RUN git config --system --add safe.directory /workspaces/NetlistIO \
    && chown -R vscode:vscode ${WORKDIR}
USER vscode

FROM dependencies AS production
COPY netlistio/ ./netlistio/
COPY README.md LICENSE NOTICE ./
RUN poetry install --only-root --no-interaction --without dev
