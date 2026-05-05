.PHONY: install install-dev test clean build publish lint

# Install production dependencies
install:
	pip install mcp

# Install in development mode
install-dev:
	pip install -e .

# Run tests
test:
	python -m pytest tests/ -v

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__/
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -delete

# Build package for PyPI
build: clean
	python -m build

# Publish to PyPI (requires twine)
publish: build
	python -m twine upload dist/*

# Check tools are registered
check:
	python -c "from qd3_fsutils.server import TOOLS; print('Tools:', [t.name for t in TOOLS])"

# Run the MCP server (for testing)
run:
	python run.py
