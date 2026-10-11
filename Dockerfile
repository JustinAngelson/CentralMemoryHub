FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY src/cmh /app/src/cmh
RUN pip install --no-cache-dir /app/src/cmh
COPY migrations /app/migrations
COPY v2/alembic.ini /app/v2/alembic.ini
COPY v2/check_mcp.py /app/v2/check_mcp.py
RUN useradd --uid 10001 --create-home cmh
USER cmh
EXPOSE 8080
CMD ["uvicorn", "cmh.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
