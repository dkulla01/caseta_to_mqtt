FROM python:3.11-bookworm

RUN pip install poetry==1.5.1
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN touch README.md

RUN poetry install --without dev --no-root
