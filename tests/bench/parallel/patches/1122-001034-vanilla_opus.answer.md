`click.Choice` now adds a "Did you mean ...?" hint when a value isn't one of the options but is close to one. Tests pass, and I committed it as `932eeef`.

**What you'll see**
```
Error: Invalid value for '--fruit': 'aple' is not one of 'apple', 'banana', 'cherry'. Did you mean 'apple'?
```
When several options are close, it prints `(Did you mean one of: 'bar', 'baz'?)`. When nothing is close, the message is the same as before, so the existing tests that check the exact error text still pass.

**How it works**
- The change is in `Choice.get_invalid_choice_message` in `src/click/types.py`. It finds close matches with `difflib.get_close_matches`, using the same default similarity cutoff as the existing hints for unknown options and commands.
- It reuses `_format_possibilities` from `exceptions.py`, so the hint is worded and formatted exactly like the "Did you mean" hint for unknown options.
- The typed value is compared after the same normalization Choice already applies. With `case_sensitive=False`, `APLE` still matches `Apple`, and the hint shows the lowercased form `'apple'`, the same way the list of options does.

**Tests** (`tests/test_basic.py`)
- `test_choice_suggestion` covers one match, several matches, no match, and a case-insensitive choice.
- `test_choice_suggestion_enum` covers an Enum choice (`GREN` → `'GREEN'`).
- The 5 new tests and the full test suite pass. The full run reported 2633 passed, 24 skipped, 1 xfailed, and also 31000 tests deselected. I didn't look into why, but my own run didn't deselect anything, so it's presumably the project's pytest settings.
- ruff and mypy report no issues.

I also added an entry to `CHANGES.md` under 8.6.0 and a `versionchanged:: 8.6` note to the method's docstring.