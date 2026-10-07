#!/usr/bin/env python

"""The setup script."""

from setuptools import find_packages, setup

with open("README.md") as readme_file:
    readme = readme_file.read()

requirements = [
    "django",
    "djangorestframework",
    "django-environ",
    "PyJWT>=2.10,<3",
]

setup(
    author="Open Healthcare Network",
    author_email="info@ohc.network",
    python_requires=">=3.13",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
    ],
    description="Video appointments for CARE",
    install_requires=requirements,
    license="MIT license",
    long_description=readme,
    long_description_content_type="text/markdown",
    include_package_data=True,
    keywords="care_zoom",
    name="care_zoom",
    packages=find_packages(include=["care_zoom", "care_zoom.*"]),
    url="https://github.com/ohcnetwork/care_zoom",
    version="0.1.0",
    zip_safe=False,
)
