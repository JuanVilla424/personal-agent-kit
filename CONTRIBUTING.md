# 🤝 Contributing to personal-agent-kit

We welcome contributions to personal-agent-kit! To make sure the process goes smoothly, please follow these guidelines:

## 📋 Code of Conduct

Please note that all participants in our project are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md). Make sure to review it before contributing.

## 🛠 How to Contribute

1. **Clone the repository**:

   ```bash
   git clone https://github.com/JuanVilla424/personal-agent-kit.git
   cd personal-agent-kit
   git submodule update --init --recursive
   ```

2. **Work on the `dev` branch**:

   ```bash
   git checkout dev
   ```

3. **Set up the environment**:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -r requirements.dev.txt
   pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

4. **Make your changes**:
   Implement your feature or fix following coding standards. Include tests where applicable.

5. **Test your changes** with the [quality gates](DEVELOPMENT.md#-quality-gates) that cover them,
   at least:

   ```bash
   .venv/bin/python -m pytest -m "not integration"
   (cd .opencode && bun test)
   .venv/bin/pre-commit run --all-files
   ```

6. **Commit following the convention**, one commit per task:

   ```bash
   git commit -m "feat(core): description in lower case"
   ```

   Add `[patch candidate]`, `[minor candidate]` or `[major candidate]` at the end only when a
   release is requested.

7. **Push in two steps**:
   ```bash
   git push origin dev
   ```
   The first push lets `validate-commit` add the icon to the message, amend the commit and stop
   the push. Run the same `git push` again. `dev` merges into `main` through a Pull Request.

## 📑 Guidelines for Contributions

- **Follow the development loop** in [DEVELOPMENT.md](DEVELOPMENT.md).
- **Lint your code** before submitting — we use [pylint](https://www.pylint.org/) for Python.
- Ensure **test coverage** for your code.
- Follow the commit message format from [VERSIONING.md](VERSIONING.md).
- Never commit `.env` files or credentials.

Thank you for helping improve!

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file included in this repository.
