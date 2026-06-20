#!/bin/bash

pytest tests/ -v --cov=towncommoniq --cov-report=html
flake8 --format=html --htmldir=flake8-report towncommoniq/ tests/
