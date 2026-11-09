FROM python:3.11-slim-bookworm
COPY time-requirements.txt /tmp/time-requirements.txt
RUN pip install --no-cache-dir -r /tmp/time-requirements.txt
ENTRYPOINT ["python", "-m", "mcp_server_time", "--local-timezone=Asia/Shanghai"]
