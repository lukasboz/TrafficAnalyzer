FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 libstdc++6 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend ./backend
COPY LICENSE THIRD_PARTY_NOTICES.md ./
COPY licenses ./licenses
ENV FLOWSTATE_DATA=/data
RUN mkdir /data && useradd --uid 10001 --create-home flowstate && chown -R flowstate:flowstate /data /app
ENV FLOWSTATE_REQUIRE_API_KEY=1
EXPOSE 8000
CMD ["python", "-m", "backend.serve"]
