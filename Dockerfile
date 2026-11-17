# ASKAI backend on Render (Docker, free plan). Python standard library only.
FROM python:3.12-slim
RUN useradd -m -u 1000 askai
USER askai
WORKDIR /home/askai/app
COPY --chown=askai backend/ backend/
# Non-secret settings. Render sets PORT itself. The provider key is a Render
# environment SECRET:  ASKAI_GEMINI_API_KEY  (optional: ASKAI_GROQ_API_KEY, ASKAI_ADMIN_TOKEN)
ENV PYTHONUNBUFFERED=1 \
    ASKAI_HOST=0.0.0.0 \
    ASKAI_DB=/tmp/askai.sqlite3 \
    ASKAI_TRUST_PROXY=1 \
    ASKAI_OPEN_ENROLLMENT=1 \
    ASKAI_MAX_ENROLL_PER_IP_HOUR=30 \
    ASKAI_LIMIT_PER_MINUTE=40 \
    ASKAI_LIMIT_PER_DAY=2000 \
    ASKAI_LIMIT_PER_MONTH=50000 \
    ASKAI_GLOBAL_PER_DAY=20000
CMD ["python", "-m", "backend.main"]
