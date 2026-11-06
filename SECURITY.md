# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue. Email **tfanac@cse.ust.hk** with a description, steps to reproduce and the affected version. 

## Things to know when running ChatDify

- **Credentials.** LLM keys and Dify passwords are read from `~/.chatdify/config.toml` (created with mode 600), environment variables or `.env`. They are never written to generated DSL. Logs in `~/.chatdify/logs/` contain prompts and LLM responses; treat them as sensitive.
- **Generated code is untrusted.** Workflows may contain code nodes and HTTP requests written by an LLM. Review them before importing into a production workspace.
- **Dynamic validation executes workflows.** With `--dify-url`, ChatDify imports and runs generated apps, including their code nodes (inside Dify's sandbox) and outbound HTTP calls. Use a dedicated, non-production Dify workspace and account.
- **Templates.** The knowledge base in `chatdify/kg/` contains placeholders such as `YOUR_API_KEY`. If you find a real credential in the repository, report it as above.
