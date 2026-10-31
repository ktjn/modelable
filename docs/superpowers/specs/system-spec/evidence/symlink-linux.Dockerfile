FROM python@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97
RUN python -m pip install --no-cache-dir uv==0.13.6
COPY source/ /source/
WORKDIR /source/cli
RUN uv sync --frozen --extra dev
COPY run-checks.py /run-checks.py
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["/source/cli/.venv/bin/python", "/run-checks.py"]
