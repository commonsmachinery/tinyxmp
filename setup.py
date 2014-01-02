#! /usr/bin/env python
from setuptools import setup

setup(
    name='tinyxmp',
    author='Artem Popov (Commons Machinery)',
    author_email='artfwo@commonsmachinery.se',
    url='https://github.com/commonsmachinery/tinyxmp',
    description='Module for reading and writing metadata as raw XMP packets.',
    version='0.1',
    py_modules=['tinyxmp'],
    include_package_data=True,
    license='GPLv2',
)
