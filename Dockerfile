ARG WORKDIR=/app
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=false \
    POETRY_VIRTUALENVS_PATH=/opt/poetry-venvs
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
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

FROM base AS dependencies
# Cache third-party deps on the lock alone; the project itself is installed
# later so source edits don't bust this layer.
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction --without dev \
    && ln -s "$(poetry env info --path)" /opt/venv

FROM dependencies AS development
ARG WORKDIR
# Pass e.g. "--with extra-group" from devcontainer.json build args.
# Empty string (the default) installs the default dev group.
ARG POETRY_EXTRA_ARGS=""
COPY . .
RUN poetry install --no-interaction ${POETRY_EXTRA_ARGS} \
    && chown -R vscode:vscode ${WORKDIR} /opt/poetry-venvs
USER vscode

FROM dependencies AS production
COPY netlistio ./netlistio/
COPY README.md LICENSE NOTICE ./
RUN poetry install --only-root --no-interaction
