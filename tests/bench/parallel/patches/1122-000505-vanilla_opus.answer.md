I fixed the bug and committed it as `dd28a25`, but the tests haven't been run. Running pytest needed permission and the request was denied.

**Cause:** In `_describe_range` (`src/click/types.py:695`), the operator for a range with only a minimum was the wrong way round. A closed minimum showed as `x>1` and an open minimum (`min_open=True`) showed as `x>=1`. `IntRange` and `FloatRange` share this code, so `FloatRange` had the same bug. I swapped the two operators.

**Tests:** There was already a test expecting `IntRange(1)` to show `x>=1` (`tests/test_options.py:787`), so it should have been catching this. I added these cases to the same test:
- `IntRange`: open minimum `x>1` and open maximum `x<32`
- `FloatRange`: both bounds, closed and open minimum, closed and open maximum

To check it, run:

```
pytest tests -q
```