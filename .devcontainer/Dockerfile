# Start from lightweight Python 3.11
FROM python:3.11-slim

# Keep Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system utilities
RUN apt-get update && apt-get install -y \
    curl \
    git \
    vim \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_HOME="/opt/poetry"
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

# Tell Poetry to create virtual environments inside the project folder
# This makes it easier for VS Code to find your installed packages
RUN poetry config virtualenvs.in-project true
