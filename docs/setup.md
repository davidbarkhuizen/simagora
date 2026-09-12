[← README](../README.md)

# Setup

The package needs to be installed (editable is fine) before it can be imported,
since `src/` isn't on `sys.path` by default:

```
pip install -e .
```

If you'd rather not install anything, point `PYTHONPATH` at `src/` instead for any
command below, e.g. `PYTHONPATH=src python3 tests/run_tests.py -v`.
