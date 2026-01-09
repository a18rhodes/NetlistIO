# Start from lightweight Python 3.11
FROM python:3.11-slim

# Keep Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_HOME="/opt/poetry"
ARG GIT_USERNAME=default_user
ARG GIT_EMAIL=default_email@example.com

# Install system utilities
RUN apt-get update && apt-get install -y \
    curl \
    git \
    vim \
    build-essential \
    graphviz \
    && rm -rf /var/lib/apt/lists/*


RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /workspaces/NetlistIO

# Configure poetry to install to the system python (skipping .venv creation)
# This avoids the issue where the volume mount hides the .venv created during build
RUN poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --no-root
RUN git config --global --add safe.directory /workspaces/NetlistIO
RUN git config --global user.email "${GIT_EMAIL}"
RUN git config --global user.name "${GIT_USERNAME}"
