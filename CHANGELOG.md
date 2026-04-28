# Release notes

<!-- do not remove -->

## 0.1.0 — Initial scaffolding

* Project layout (hatchling, src, pyproject.toml, bump-my-version config).
* Public API stub: `cubegenpy.build_cube(...)` raising `NotImplementedError`.
* `docs/index.qmd` mapping every IDL `.pro` file to its Python target (or
  noting that the functionality is replaced by `pyuvis` / external geometry
  / dropped GUI). Will become the homepage of the docs site.
* `refs/` preserves the FITS layout proposal (Mark Showalter, 2026-02) and
  the team meeting notes that motivate the design.

No functional code yet — see `PORT_PLAN.md` for the implementation roadmap.
