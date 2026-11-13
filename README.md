# GEF Mobile — full project download (v4, extras round 3)

Layout:
- verification-portal/  the working product (Weeks 1-3 + extras rounds 1-3)
    features: six-check verification, RAG chat, hardening, QR codes, public
    (persisted) log, IsolationForest anomaly watch, verifiable diploma PDFs,
    student self-service lookup, multi-signer admin, email notifier,
    responsive UI, + person-in-context AI (masked profile cards, session
    memory) and web research (Wikipedia/DuckDuckGo; demo-fixture mode).
    run: cd verification-portal && .venv/bin/python -m uvicorn app.main:app --port 8000
    (fresh install: python3 -m venv --system-site-packages .venv, then
     .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
     and .venv/bin/pip install -r requirements.txt)
    tests: python -m unittest tests.test_api tests.test_hardening tests.test_rag
           tests.test_features tests.test_extra2 tests.test_person   (72 tests)
    demo video: demo.mp4 (rebuild: python3 scripts/build_demo_video.py)
- original-repo/        the Gef26 hash-chain repo as uploaded (source of truth)
