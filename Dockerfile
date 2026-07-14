FROM python:3.12-slim
 
# uv 설치 (공식 이미지에서 바이너리 복사)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
 
WORKDIR /app
 
# 의존성 파일만 먼저 복사 → 레이어 캐시 최대 활용
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project
 
# 소스 복사
COPY app/ ./app/
 
# pyproject.toml의 packages.find.where = ["app"]와 대응
ENV PYTHONPATH=/app/app
ENV PYTHONUNBUFFERED=1
 
CMD ["uv", "run", "--no-dev", "python", "-m", "bot.main"]
