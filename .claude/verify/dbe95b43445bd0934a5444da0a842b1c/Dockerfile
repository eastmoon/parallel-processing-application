# 驗證環境：doc/poc/02.fastapi-response-technology-specification.md（伺服器回應格式）
FROM python:3.13.7-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN pip install "fastapi==0.141.1" "pydantic==2.13.5" "starlette==1.7.0" "httpx2==2.13.1" "uvicorn==0.54.0"

WORKDIR /work
CMD ["python", "src/verify.py"]
