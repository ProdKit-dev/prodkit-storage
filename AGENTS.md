# Agents

Project conventions for human and agent contributors.

## Git

- Do not commit directly to `main` after initial setup.
- Use focused branches and pull requests.
- Do not commit secrets, `.env` files, generated credentials, or private keys.
- Use Conventional Commits for every commit and pull-request title:
  `<type>(<optional-scope>): <imperative lowercase summary>`.
- Use one of these types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, or `revert`.
- Use `feat` for user-facing capabilities, `fix` for defects, `ci` for CI
  workflow changes, and `chore(deps)` for dependency-only maintenance.
- Keep the summary concise, omit a trailing period, and do not use an
  untyped plain-text commit title. Example:
  `feat(demo): add production storage demo`.
- Do not rewrite commits already merged into the default branch. Amend an
  unmerged commit only when it is safe to update its pull-request branch;
  use `--force-with-lease`, never an unconditional force push.
