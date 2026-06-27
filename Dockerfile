FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QUANT_TRADER_ENV=dev \
    PYTHONPATH=/app:/app/sim/fake_xtquant

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY src ./src
COPY sim ./sim
COPY README.md ./

RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

CMD ["python", "-m", "sim.run_simulated_quant_trader"]
