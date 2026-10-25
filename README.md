# DisruptOps

Supply-disruption decision support using typed agents, grounded tools and human approval.

This branch imports phase 1: configurable abstract agent shell and contract tests.

Use Python 3.13 and install the pinned dependencies:

```sh
python -m pip install -r requirements-gemini.txt
python -m pip install --no-build-isolation -e .
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

The tests available in this phase run without Google credentials. Further roles and
application wiring are introduced in subsequent feature branches. These phase commits
package an existing POC and use their actual creation times.
