# Version: 3.2.4
"""
Article Finder v3.2 Setup
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read version from VERSION file
version_file = Path(__file__).parent / "VERSION"
version = version_file.read_text().strip() if version_file.exists() else "0.0.0"

# Read long description from README
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="article_finder_v3",
    version=version,
    author="Article Finder Team",
    description="A comprehensive tool for managing neuroarchitecture research literature",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pyyaml>=6.0",
        "jsonschema>=4.0",
    ],
    extras_require={
        "full": [
            "openpyxl>=3.0",
            "pandas>=1.5",
            "streamlit>=1.20",
            "plotly>=5.0",
            "sentence-transformers>=2.2",
            "numpy>=1.21",
        ],
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "article-finder=cli.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
