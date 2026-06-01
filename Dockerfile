ARG WORKDIR=/app
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
    sudo \
    && rm -rf /var/lib/apt/lists/*
ARG WORKDIR
WORKDIR ${WORKDIR}
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

FROM base AS dependencies
COPY pyproject.toml poetry.lock README.md ./
RUN poetry lock
RUN poetry install --no-root --no-interaction

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
