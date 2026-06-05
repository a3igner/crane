# Contributing to CRANE

Thank you for your interest in CRANE! This document outlines the guidelines for contributing.

## Development Setup

```bash
git clone https://github.com/a3igner/crane.git
cd crane
pip install -r requirements.txt
export CRANE_DB_TYPE=sqlite  # Use SQLite for development
python -m crane.pipeline --all
```

## Code Style

- Follow PEP 8
- Use type hints for all function signatures
- Write docstrings for all public methods (Google style)
- Keep functions focused and single-purpose

## Testing

```bash
python -m pytest tests/
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
