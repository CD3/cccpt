import os
from setuptools import setup, find_packages

__version__= '0.3'

setup(
  name = 'conan-cmake-cpp-project-tools',
  packages = ['cccpt'],
  version = __version__,
  description = "A command-line to quickly configure, build, test (and more) CMake-based C/C++ projects.",
  license='MIT',
  author = 'CD Clark III',
  author_email = 'clifton.clark@gmail.com',
  url = 'https://github.com/CD3/cccpt',
  download_url = f'https://github.com/CD3/cccpt/archive/{__version__}.tar.gz',
  install_requires = ['click','pyyaml','fspathtree','pyparsing'],
  entry_points='''
  [console_scripts]
  ccc=cccpt.cli:main
  ''',
)
