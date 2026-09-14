.PHONY: install test docs serve clean

install:
	pip install -e ".[dev,docs]"

test:
	pytest

docs:
	great-docs build

serve:
	great-docs preview

clean:
	rm -rf dist build *.egg-info great-docs/
