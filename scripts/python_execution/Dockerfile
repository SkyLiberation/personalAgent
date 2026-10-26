FROM python@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ENV PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir pandas==2.3.3 numpy==2.4.4
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT []
CMD ["python", "-I", "/inputs/program.py", "/inputs"]
