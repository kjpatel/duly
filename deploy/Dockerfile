# The demo as a container, for a deployment that is not this checkout.
#
# Deliberately generic: it names no project, region or hostname, because those
# belong to whoever is deploying. It expects two things staged beside it —
# a built wheel (`uv build --wheel`) and a `content/` directory — which is what
# `.github/workflows/deploy-demo.yml` assembles, and what an adopter would
# assemble by hand.
#
# This is a reference wiring, not a deployment blueprint. The demo keeps its
# fact store in memory (see duly_demo/CLAUDE.md); a real deployment supplies a
# durable store, identity, and the retention policy the receipt cannot
# discharge for you (docs/neuro-symbolic-architecture.md, guidance item 5).

FROM python:3.12-slim

# `demo` brings fastapi + uvicorn; `report` brings reportlab, without which
# the PDF audit report is a button that 503s — the extra was missed when this
# image was first written, and the demo offered the download anyway.
# Deliberately NOT `prove`: z3 is
# the most CPU-expensive thing the rule studio can be asked to run, which is a
# poor thing to expose to anonymous callers.
#
# Copied by glob so a version bump needs no edit here. The extras suffix has to
# be applied in the shell, because a glob inside quotes will not expand.
COPY duly-*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/duly-*.whl)[demo,report]" && rm -f /tmp/duly-*.whl

# The content-root contract is flat: starters/, golden/, rulepacks/,
# ontologies/ and dmn/ sit directly under the root (duly_demo/content.py). The
# wheel ships no content on purpose, so an installed demo serves empty listings
# until it is pointed at some — which is the honest degrade, not a bug.
COPY content /content
ENV DULY_DEMO_CONTENT=/content

# Cloud Run and most PaaS hosts inject PORT; 8080 is the common default.
CMD exec uvicorn duly_demo.app:app --host 0.0.0.0 --port ${PORT:-8080}
