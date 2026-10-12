# Upgrading

How to move a project to a newer `sweatstack` release, from any older one. Until 1.0 a minor
release may contain breaking changes, and every one ships with its upgrade path in the
[CHANGELOG](CHANGELOG.md): an **Upgrading** section with a table from old to new, and for the
larger releases a prompt for a coding agent. This page is also at
https://docs.sweatstack.no/learn/python/upgrading/, with every release's section inline.

<!-- --8<-- [start:procedure] -->
## Procedure

1. **Find your version.** `uv pip show sweatstack`, or your lockfile.
2. **Inventory your SDK usage** before changing anything: every call on a `Client` or on the
   `sweatstack` module (`import sweatstack as ss` is common), `StreamlitAuth` and
   `sweatstack.fastapi`, the model fields you read, the frame columns and indexes you rely on,
   the exceptions you catch, and the install line with its extras.
3. **Read the Upgrading section of every release** between your version and the target; a
   release without one has nothing to do. Work oldest first: each table uses the names of the
   release before it.
   `adaptive_sampling_on` became `nlec_on` in 0.86 and `segmentation_on` in 0.87, so a name may
   change more than once; follow the chain.
4. **Change the pin and run your code and tests.** A removed name raises an `AttributeError`
   naming its replacement, a renamed or keyword-only argument raises `TypeError`, and
   `from sweatstack import <removed name>` raises Python's plain `ImportError`. The rows marked
   **Silent** don't fail at all: check each one by hand.
5. **Don't add compatibility shims.** Move every call site to the new name.

The install line changes too: Python 3.10 or later (0.78), the frame library as an extra
(`sweatstack[pandas]`, `[polars]` or `[arrow]`; `[streamlit]` includes pandas) and pyarrow 20 or
later (0.84, 0.89), and no `[jupyter]` extra (0.91).
<!-- --8<-- [end:procedure] -->

<!-- --8<-- [start:prompt] -->
## Prompt for a coding agent

Fill in the two versions and paste it into your agent. It works for any distance between them.

```text
Upgrade this project from sweatstack <OLD> to sweatstack <NEW>.

1. Inventory. Before changing anything, list every use of the SDK: calls on a Client or on the
   sweatstack module (also as "ss"), StreamlitAuth and sweatstack.fastapi, model fields read
   from responses, frame columns and indexes, exceptions caught, and the dependency line with
   its extras.
2. Plan. Read https://docs.sweatstack.no/learn/python/upgrading/ (the same content is
   UPGRADING.md and the "Upgrading" sections of CHANGELOG.md in
   https://github.com/SweatStack/sweatstack-python). Take every release between <OLD> and <NEW>
   that has an Upgrading section, oldest first, and map each row of its table onto the
   inventory. A name may be renamed more than once across releases; follow the chain to the
   final name.
3. Apply the changes, oldest release first. Do not add compatibility shims.
4. Install: uv add "sweatstack[<extras>]==<NEW>". The frame library is an extra ([pandas],
   [polars] or [arrow]); [streamlit] includes pandas.
5. Run the code and the tests. Fix every AttributeError (its message names the replacement),
   ImportError and TypeError. Then check every row marked "Silent" against the inventory:
   those change behaviour without raising.
6. For the current API, install the SDK's agent skill (npx skills add
   SweatStack/sweatstack-python) or read https://docs.sweatstack.no/llms.txt.

Report what you changed, and every item of the inventory you could not map to a table row.
```
<!-- --8<-- [end:prompt] -->
